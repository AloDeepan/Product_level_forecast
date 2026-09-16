#!/usr/bin/env python3
"""Build the compact, auditable data layer used by the family dashboard.

The raw extract is intentionally never loaded into pandas. DuckDB scans it and
writes a small set of Parquet facts/dimensions that Streamlit can query lazily.
"""

from __future__ import annotations

import argparse
import json
import re
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd


CANONICAL_FAMILY_RE = re.compile(
    r"^(?P<season>SP|SU|FA|HO|WT)(?P<year>\d{2})D(?P<drop>\d+)-family$",
    re.IGNORECASE,
)
SCHEMA_VERSION = 2
OUTPUT_FILES = {
    "fact": "product_daily.parquet",
    "products": "product_dimension.parquet",
    "membership": "product_drop_membership.parquet",
    "drops": "drop_calendar.parquet",
    "context": "daily_context.parquet",
    "excluded_tags": "excluded_family_tags.parquet",
    "quality": "data_quality.json",
}


def is_canonical_family(value: object) -> bool:
    """Return True only for a complete conventional drop tag."""

    if value is None or pd.isna(value):
        return False
    normalized = unicodedata.normalize("NFKC", str(value)).strip()
    return CANONICAL_FAMILY_RE.fullmatch(normalized) is not None


def _sql_string(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def _clean_text(series: pd.Series) -> pd.Series:
    return (
        series.astype("string")
        .map(lambda value: unicodedata.normalize("NFKC", value) if pd.notna(value) else value)
        .str.strip()
        .replace({"": pd.NA})
    )


def _find_column(frame: pd.DataFrame, name: str) -> str:
    lookup = {str(column).strip().casefold(): column for column in frame.columns}
    try:
        return lookup[name.casefold()]
    except KeyError as exc:
        raise ValueError(f"Release workbook is missing required column: {name}") from exc


def load_drop_calendar(path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Load and strictly filter the release workbook to conventional drops."""

    source = pd.read_excel(path)
    tag_col = _find_column(source, "Tag")
    launch_col = _find_column(source, "Launch Date")
    early_col = _find_column(source, "Early Access")

    optional = {str(column).strip().casefold(): column for column in source.columns}
    color_col = optional.get("oliver")
    hex_codes_col = optional.get("hex codes")
    hex_code_col = optional.get("hex code")
    note_col = optional.get("notes")

    work = pd.DataFrame(
        {
            "family_tag": _clean_text(source[tag_col]).str.lower(),
            "early_access_date": pd.to_datetime(source[early_col], errors="coerce").dt.date,
            "launch_date": pd.to_datetime(source[launch_col], errors="coerce").dt.date,
            "color_story": _clean_text(source[color_col]) if color_col else pd.NA,
            "notes": _clean_text(source[note_col]) if note_col else pd.NA,
        }
    )

    raw_hex = pd.Series(pd.NA, index=source.index, dtype="string")
    if hex_codes_col:
        raw_hex = _clean_text(source[hex_codes_col])
    if hex_code_col:
        raw_hex = raw_hex.fillna(_clean_text(source[hex_code_col]))
    work["hex_codes"] = raw_hex
    work["primary_hex"] = raw_hex.str.extract(r"(#[0-9a-fA-F]{6})", expand=False).str.lower()

    parsed = work["family_tag"].str.extract(CANONICAL_FAMILY_RE)
    valid_name = parsed["season"].notna()
    missing_date = work["early_access_date"].isna() & work["launch_date"].isna()
    calendar = work.loc[valid_name & ~missing_date].copy()
    parsed = parsed.loc[calendar.index]

    calendar["season_code"] = parsed["season"].str.upper()
    calendar["season_year"] = 2000 + parsed["year"].astype(int)
    calendar["drop_number"] = parsed["drop"].astype(int)
    calendar["drop_label"] = calendar["family_tag"].str.removesuffix("-family").str.upper()
    calendar["anchor_date"] = calendar["early_access_date"].fillna(calendar["launch_date"])
    calendar = calendar.sort_values(["launch_date", "family_tag"]).drop_duplicates(
        "family_tag", keep="last"
    )
    calendar = calendar[
        [
            "family_tag",
            "drop_label",
            "season_code",
            "season_year",
            "drop_number",
            "early_access_date",
            "launch_date",
            "anchor_date",
            "color_story",
            "primary_hex",
            "hex_codes",
            "notes",
        ]
    ].reset_index(drop=True)

    diagnostics = {
        "release_rows": int(len(source)),
        "populated_tags": int(_clean_text(source[tag_col]).notna().sum()),
        "canonical_rows": int(valid_name.sum()),
        "canonical_rows_with_dates": int(len(calendar)),
        "canonical_rows_missing_dates": int((valid_name & missing_date).sum()),
    }
    return calendar, diagnostics


def load_sale_periods(path: Path | None) -> pd.DataFrame:
    columns = ["period_name", "start_date", "end_date", "source"]
    if path is None:
        return pd.DataFrame(columns=columns)
    if not path.exists():
        raise FileNotFoundError(
            f"Sale-period configuration does not exist: {path}. Pass None only to opt out explicitly."
        )

    periods = pd.read_csv(path)
    missing = set(columns) - set(periods.columns)
    if missing:
        raise ValueError(f"Sale-period file is missing columns: {sorted(missing)}")
    periods = periods[columns].copy()
    periods["period_name"] = _clean_text(periods["period_name"])
    periods["source"] = _clean_text(periods["source"])
    periods["start_date"] = pd.to_datetime(periods["start_date"], errors="raise").dt.date
    periods["end_date"] = pd.to_datetime(periods["end_date"], errors="raise").dt.date
    if (periods["end_date"] < periods["start_date"]).any():
        raise ValueError("Every sale period must end on or after its start date")
    return periods.sort_values("start_date").reset_index(drop=True)


def _build_daily_context(
    daily: pd.DataFrame, sale_periods: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, Any]]:
    daily = daily.sort_values("order_date").reset_index(drop=True)
    daily["order_date"] = pd.to_datetime(daily["order_date"])

    prior = daily["daily_revenue"].shift(1)
    baseline = prior.rolling(28, min_periods=7).median()
    fallback = prior.expanding(min_periods=1).median()
    daily["trailing_28d_median_revenue"] = baseline.fillna(fallback)
    daily["revenue_index"] = (
        daily["daily_revenue"] / daily["trailing_28d_median_revenue"].replace(0, np.nan)
    )
    high_volume_floor = float(daily["daily_revenue"].quantile(0.90))
    daily["is_volume_spike"] = (
        (daily["revenue_index"] >= 3.0) & (daily["daily_revenue"] >= high_volume_floor)
    )

    daily["sale_period_name"] = pd.Series(pd.NA, index=daily.index, dtype="string")
    daily["sale_period_source"] = pd.Series(pd.NA, index=daily.index, dtype="string")
    for row in sale_periods.itertuples(index=False):
        mask = daily["order_date"].dt.date.between(row.start_date, row.end_date)
        existing_name = daily.loc[mask, "sale_period_name"].fillna("")
        existing_source = daily.loc[mask, "sale_period_source"].fillna("")
        daily.loc[mask, "sale_period_name"] = np.where(
            existing_name.eq(""), row.period_name, existing_name + "; " + row.period_name
        )
        daily.loc[mask, "sale_period_source"] = np.where(
            existing_source.eq(""), row.source, existing_source + "; " + row.source
        )
    daily["is_configured_sale"] = daily["sale_period_name"].notna()

    # Only the extract's trailing date is classified as incomplete. Revenue can
    # legitimately be low on older days, so applying this rule historically
    # would create false positives.
    daily["is_incomplete_date"] = False
    if len(daily) >= 8:
        last_idx = daily.index[-1]
        prior_rows = daily.loc[daily.index[-8:-1], "source_rows"].median()
        prior_revenue = daily.loc[daily.index[-8:-1], "daily_revenue"].median()
        last_is_thin = (
            daily.at[last_idx, "source_rows"] < 0.60 * prior_rows
            and daily.at[last_idx, "daily_revenue"] < 0.60 * prior_revenue
        )
        daily.at[last_idx, "is_incomplete_date"] = bool(last_is_thin)

    latest_date = daily["order_date"].max()
    complete_dates = daily.loc[~daily["is_incomplete_date"], "order_date"]
    latest_complete = complete_dates.max() if not complete_dates.empty else latest_date
    diagnostics = {
        "latest_source_date": latest_date.date().isoformat(),
        "latest_complete_date": latest_complete.date().isoformat(),
        "latest_source_date_flagged_incomplete": bool(
            daily.loc[daily["order_date"].eq(latest_date), "is_incomplete_date"].iloc[0]
        ),
        "configured_sale_days": int(daily["is_configured_sale"].sum()),
        "automated_volume_spike_days": int(daily["is_volume_spike"].sum()),
        "volume_spike_rule": "daily revenue >= 3x trailing 28-day median and >= global p90",
    }
    return daily, diagnostics


def _fetch_scalar(connection: duckdb.DuckDBPyConnection, query: str) -> Any:
    return connection.execute(query).fetchone()[0]


def build_data(
    sales_path: Path,
    releases_path: Path,
    output_dir: Path,
    sale_periods_path: Path | None,
    threads: int = 4,
    memory_limit: str = "4GB",
) -> dict[str, Any]:
    if not sales_path.exists():
        raise FileNotFoundError(sales_path)
    if not releases_path.exists():
        raise FileNotFoundError(releases_path)

    output_dir.mkdir(parents=True, exist_ok=True)
    calendar, release_diagnostics = load_drop_calendar(releases_path)
    sale_periods = load_sale_periods(sale_periods_path)

    # Build alongside the live artifacts. Each completed file replaces its
    # predecessor atomically, with the quality manifest published last so the
    # dashboard can use its timestamp as a generation/cache version.
    with tempfile.TemporaryDirectory(
        prefix=".family_dashboard_build_", dir=output_dir
    ) as staging_text:
        staging_dir = Path(staging_text)
        temp_dir = staging_dir / "duckdb_work"
        temp_dir.mkdir()
        database_path = temp_dir / "build.duckdb"
        connection = duckdb.connect(str(database_path))
        connection.execute(f"PRAGMA threads={max(1, threads)}")
        connection.execute(f"SET memory_limit='{memory_limit}'")
        connection.execute(f"SET temp_directory='{_sql_string(Path(temp_dir))}'")
        connection.register("release_calendar_df", calendar)

        sales_sql = (
            f"read_csv_auto('{_sql_string(sales_path)}', header=true, "
            "all_varchar=true, null_padding=true)"
        )
        ingest_diagnostics = connection.execute(
            f"""
            SELECT
                count(*)::BIGINT AS source_file_rows,
                count(*) FILTER (WHERE nullif(trim(order_date), '') IS NULL)::BIGINT
                    AS missing_order_date_rows,
                count(*) FILTER (
                    WHERE nullif(trim(order_date), '') IS NOT NULL
                      AND TRY_CAST(order_date AS DATE) IS NULL
                )::BIGINT AS invalid_order_date_rows,
                count(*) FILTER (WHERE nullif(trim(revenue), '') IS NULL)::BIGINT
                    AS missing_revenue_rows,
                count(*) FILTER (
                    WHERE nullif(trim(revenue), '') IS NOT NULL
                      AND TRY_CAST(revenue AS DOUBLE) IS NULL
                )::BIGINT AS invalid_revenue_rows,
                count(*) FILTER (WHERE nullif(trim(ordered_quantities), '') IS NULL)::BIGINT
                    AS missing_unit_rows,
                count(*) FILTER (
                    WHERE nullif(trim(ordered_quantities), '') IS NOT NULL
                      AND TRY_CAST(ordered_quantities AS BIGINT) IS NULL
                )::BIGINT AS invalid_unit_rows
            FROM {sales_sql}
            """
        ).fetchdf().iloc[0].to_dict()
        parse_failures = {
            key: int(value)
            for key, value in ingest_diagnostics.items()
            if key != "source_file_rows" and int(value) > 0
        }
        if parse_failures:
            connection.close()
            details = ", ".join(f"{key}={value:,}" for key, value in parse_failures.items())
            raise ValueError(
                "Sales input contains missing or malformed required measures; no artifacts were published. "
                + details
            )
        connection.execute(
            f"""
            CREATE TABLE raw AS
            SELECT
                TRY_CAST(order_date AS DATE) AS order_date,
                nullif(trim(CAST(product_title AS VARCHAR)), '') AS product_title,
                nullif(trim(CAST(sku AS VARCHAR)), '') AS sku,
                TRY_CAST(product_id AS BIGINT) AS product_id,
                TRY_CAST(price AS DOUBLE) AS source_price,
                nullif(trim(CAST(color_group AS VARCHAR)), '') AS color_group,
                nullif(trim(CAST(color AS VARCHAR)), '') AS color,
                nullif(trim(CAST(item_class AS VARCHAR)), '') AS item_class,
                nullif(trim(CAST(subcategory AS VARCHAR)), '') AS subcategory,
                nullif(trim(CAST(category AS VARCHAR)), '') AS category,
                nullif(trim(CAST(business_line AS VARCHAR)), '') AS business_line,
                nullif(trim(CAST(size AS VARCHAR)), '') AS size,
                coalesce(nullif(trim(CAST(families AS VARCHAR)), ''), 'NO_FAM') AS families,
                CASE lower(trim(CAST(planning_status AS VARCHAR)))
                    WHEN 'core' THEN 'Core'
                    WHEN 'seasonal' THEN 'Seasonal'
                    WHEN 'carryover' THEN 'Carryover'
                    WHEN 'fpphaseout' THEN 'FPPhaseOut'
                    WHEN 'markdown' THEN 'Markdown'
                    WHEN 'not-mapped' THEN 'NOT-MAPPED'
                    WHEN 'beautywellness' THEN 'BeautyWellness'
                    ELSE coalesce(nullif(trim(CAST(planning_status AS VARCHAR)), ''), 'Unknown')
                END AS planning_status,
                coalesce(TRY_CAST(revenue AS DOUBLE), 0.0) AS revenue,
                coalesce(TRY_CAST(ordered_quantities AS BIGINT), 0) AS units,
                nullif(trim(CAST(unique_key AS VARCHAR)), '') AS unique_key
            FROM {sales_sql}
            WHERE TRY_CAST(order_date AS DATE) IS NOT NULL
            """
        )

        raw_rows = int(_fetch_scalar(connection, "SELECT count(*) FROM raw"))
        raw_revenue = float(_fetch_scalar(connection, "SELECT sum(revenue) FROM raw") or 0)
        raw_units = int(_fetch_scalar(connection, "SELECT sum(units) FROM raw") or 0)
        unique_key_duplicates = int(
            _fetch_scalar(
                connection,
                """
                SELECT coalesce(sum(key_count - 1), 0)::BIGINT
                FROM (
                    SELECT unique_key, count(*) key_count
                    FROM raw WHERE unique_key IS NOT NULL
                    GROUP BY unique_key HAVING count(*) > 1
                )
                """,
            )
        )
        apparent_duplicate_review = connection.execute(
            """
            WITH repeated AS (
                SELECT order_date, sku, revenue, units, count(*) AS row_count
                FROM raw
                WHERE sku IS NOT NULL
                GROUP BY order_date, sku, revenue, units
                HAVING count(*) > 1
            )
            SELECT
                count(*)::BIGINT AS groups,
                coalesce(sum(row_count - 1), 0)::BIGINT AS possible_extra_rows,
                coalesce(sum(revenue * (row_count - 1)), 0) AS possible_extra_revenue
            FROM repeated
            """
        ).fetchdf().iloc[0].to_dict()
        metadata_instability = connection.execute(
            """
            WITH by_sku AS (
                SELECT sku,
                       count(DISTINCT product_title) FILTER (WHERE product_title IS NOT NULL) AS titles,
                       count(DISTINCT color) FILTER (WHERE color IS NOT NULL) AS colors,
                       count(DISTINCT category) FILTER (WHERE category IS NOT NULL) AS categories
                FROM raw WHERE sku IS NOT NULL GROUP BY sku
            )
            SELECT
                count(*) FILTER (WHERE titles > 1)::BIGINT AS skus_with_multiple_titles,
                count(*) FILTER (WHERE colors > 1)::BIGINT AS skus_with_multiple_colors,
                count(*) FILTER (WHERE categories > 1)::BIGINT AS skus_with_multiple_categories
            FROM by_sku
            """
        ).fetchdf().iloc[0].to_dict()

        # Select one coherent static record per SKU without changing revenue.
        # Completeness wins first, then recency; this avoids constructing a
        # synthetic product by taking individual fields from different rows.
        connection.execute(
            """
            CREATE TABLE sku_dimension AS
            WITH ranked AS (
                SELECT
                    sku, product_title, product_id, source_price, color_group, color,
                    item_class, subcategory, category, business_line, order_date,
                    row_number() OVER (
                        PARTITION BY sku
                        ORDER BY
                            ((product_title IS NOT NULL)::INT
                             + (product_id IS NOT NULL)::INT
                             + (color_group IS NOT NULL)::INT
                             + (color IS NOT NULL)::INT
                             + (item_class IS NOT NULL)::INT
                             + (subcategory IS NOT NULL)::INT
                             + (category IS NOT NULL)::INT
                             + (business_line IS NOT NULL)::INT) DESC,
                            order_date DESC,
                            product_title,
                            color
                    ) AS record_rank
                FROM raw
                WHERE sku IS NOT NULL
            ), observed AS (
                SELECT sku, min(order_date) AS first_seen_date,
                       max(order_date) AS last_seen_date
                FROM raw WHERE sku IS NOT NULL GROUP BY sku
            )
            SELECT
                r.sku, r.product_title, r.product_id, r.source_price,
                r.color_group, r.color, r.item_class, r.subcategory,
                r.category, r.business_line,
                o.first_seen_date, o.last_seen_date
            FROM ranked r
            JOIN observed o USING (sku)
            WHERE r.record_rank = 1
            """
        )

        # Product identity deliberately ignores product_id: the audit found it
        # changes for many SKUs. Product name + color is stable across sizes and
        # is the grain merchandisers expect in the product view.
        connection.execute(
            """
            CREATE TABLE sku_product AS
            WITH prepared AS (
                SELECT
                    *,
                    coalesce(
                        color,
                        nullif(regexp_extract(product_title, '\\s+-\\s+(.+)$', 1), '')
                    ) AS resolved_color,
                    CASE
                        WHEN product_title IS NULL THEN concat('Unknown SKU ', sku)
                        WHEN color IS NOT NULL
                             AND ends_with(lower(product_title), lower(concat(' - ', color)))
                            THEN rtrim(left(product_title, length(product_title) - length(color) - 3))
                        WHEN regexp_matches(product_title, '\\s+-\\s+')
                            THEN regexp_replace(product_title, '\\s+-\\s+.*$', '')
                        ELSE product_title
                    END AS product_name
                FROM sku_dimension
            )
            SELECT
                *,
                concat(
                    'product:',
                    md5(
                        regexp_replace(lower(coalesce(product_name, concat('Unknown SKU ', sku))), '[^a-z0-9]+', ' ', 'g')
                        || '|'
                        || regexp_replace(lower(coalesce(resolved_color, 'Unknown')), '[^a-z0-9]+', ' ', 'g')
                    )
                ) AS product_key
            FROM prepared
            """
        )

        # One fallback product key preserves the single known null-SKU row and
        # any future equivalents, keeping the fact fully reconcilable.
        connection.execute(
            """
            CREATE TABLE raw_enriched AS
            SELECT
                r.*,
                coalesce(sp.item_class, r.item_class, 'Unknown') AS fact_item_class,
                coalesce(sp.subcategory, r.subcategory, 'Unknown') AS fact_subcategory,
                coalesce(sp.category, r.category, 'Unknown') AS fact_category,
                coalesce(sp.business_line, r.business_line, 'Unknown') AS fact_business_line,
                coalesce(
                    sp.product_key,
                    concat(
                        'unmapped:',
                        md5(
                            lower(coalesce(r.product_title, 'Unknown product')) || '|'
                            || lower(coalesce(r.color, 'Unknown'))
                        )
                    )
                ) AS product_key
            FROM raw r
            LEFT JOIN sku_product sp USING (sku)
            """
        )

        # Tokenize before removing "-family". This is the key guardrail that
        # prevents D3-1, men's, capsule, and bespoke tags from being folded into
        # the conventional parent drop.
        connection.execute(
            """
            CREATE TABLE family_tokens AS
            SELECT
                product_key,
                sku,
                order_date,
                revenue,
                units,
                trim(lower(token)) AS family_tag
            FROM raw_enriched,
            UNNEST(string_split(lower(families), ',')) AS split(token)
            WHERE trim(token) <> ''
            """
        )
        connection.execute(
            """
            CREATE TABLE valid_release_calendar AS
            SELECT * FROM release_calendar_df
            """
        )
        connection.execute(
            """
            CREATE TABLE sku_membership AS
            SELECT
                t.sku,
                t.family_tag,
                min(t.order_date) AS first_tag_observed_date,
                max(t.order_date) AS last_tag_observed_date
            FROM family_tokens t
            INNER JOIN valid_release_calendar r USING (family_tag)
            WHERE t.sku IS NOT NULL
              AND regexp_full_match(t.family_tag, '(sp|su|fa|ho|wt)[0-9]{2}d[0-9]+-family')
            GROUP BY t.sku, t.family_tag
            """
        )
        connection.execute(
            """
            CREATE TABLE product_membership AS
            SELECT
                sp.product_key,
                m.family_tag,
                count(DISTINCT m.sku) AS member_sku_count,
                min(m.first_tag_observed_date) AS first_tag_observed_date,
                max(m.last_tag_observed_date) AS last_tag_observed_date
            FROM sku_membership m
            JOIN sku_product sp USING (sku)
            GROUP BY sp.product_key, m.family_tag
            """
        )

        # A sale belongs to at most one family: the most recently launched
        # validated family attached to that product and eligible on that date.
        connection.execute(
            """
            CREATE TABLE product_date_assignment AS
            SELECT
                pd.product_key,
                pd.order_date,
                first(m.family_tag ORDER BY r.anchor_date DESC, m.family_tag DESC)
                    FILTER (
                        WHERE greatest(
                            r.anchor_date,
                            m.first_tag_observed_date - INTERVAL 1 DAY
                        ) <= pd.order_date
                    ) AS assigned_family
            FROM (SELECT DISTINCT product_key, order_date FROM raw_enriched) pd
            LEFT JOIN product_membership m USING (product_key)
            LEFT JOIN valid_release_calendar r USING (family_tag)
            GROUP BY pd.product_key, pd.order_date
            """
        )

        connection.execute(
            """
            CREATE TABLE product_fact AS
            SELECT
                e.order_date,
                e.product_key,
                e.planning_status,
                a.assigned_family,
                CASE
                    WHEN e.planning_status = 'Core' THEN 'core'
                    WHEN a.assigned_family IS NOT NULL THEN a.assigned_family
                    ELSE 'rest'
                END AS contribution_family,
                e.fact_business_line AS business_line,
                e.fact_category AS category,
                e.fact_subcategory AS subcategory,
                e.fact_item_class AS item_class,
                sum(e.revenue) AS revenue,
                sum(e.units)::BIGINT AS units,
                count(*)::BIGINT AS source_rows
            FROM raw_enriched e
            LEFT JOIN product_date_assignment a USING (product_key, order_date)
            GROUP BY
                e.order_date,
                e.product_key,
                e.planning_status,
                a.assigned_family,
                contribution_family,
                e.fact_business_line,
                e.fact_category,
                e.fact_subcategory,
                e.fact_item_class
            """
        )

        # Pick a coherent representative record for each normalized product.
        connection.execute(
            """
            CREATE TABLE product_dimension AS
            WITH ranked AS (
                SELECT
                    product_key,
                    product_name,
                    product_title,
                    product_id,
                    coalesce(resolved_color, 'Unknown') AS color,
                    coalesce(color_group, 'Unknown') AS color_group,
                    coalesce(item_class, 'Unknown') AS item_class,
                    coalesce(subcategory, 'Unknown') AS subcategory,
                    coalesce(category, 'Unknown') AS category,
                    coalesce(business_line, 'Unknown') AS business_line,
                    source_price,
                    first_seen_date,
                    last_seen_date,
                    sku,
                    row_number() OVER (
                        PARTITION BY product_key
                        ORDER BY
                            ((product_title IS NOT NULL)::INT
                             + (resolved_color IS NOT NULL)::INT
                             + (category IS NOT NULL)::INT
                             + (subcategory IS NOT NULL)::INT
                             + (item_class IS NOT NULL)::INT
                             + (business_line IS NOT NULL)::INT) DESC,
                            last_seen_date DESC,
                            sku
                    ) AS row_rank
                FROM sku_product
            ), product_dates AS (
                SELECT product_key, min(first_seen_date) AS first_seen_date,
                       max(last_seen_date) AS last_seen_date,
                       count(*) AS sku_count
                FROM sku_product GROUP BY product_key
            ), product_taxonomy AS (
                SELECT
                    product_key,
                    CASE WHEN count(DISTINCT coalesce(color_group, 'Unknown')) = 1
                         THEN min(coalesce(color_group, 'Unknown'))
                         ELSE 'Mixed / multiple' END AS color_group,
                    CASE WHEN count(DISTINCT coalesce(item_class, 'Unknown')) = 1
                         THEN min(coalesce(item_class, 'Unknown'))
                         ELSE 'Mixed / multiple' END AS item_class,
                    CASE WHEN count(DISTINCT coalesce(subcategory, 'Unknown')) = 1
                         THEN min(coalesce(subcategory, 'Unknown'))
                         ELSE 'Mixed / multiple' END AS subcategory,
                    CASE WHEN count(DISTINCT coalesce(category, 'Unknown')) = 1
                         THEN min(coalesce(category, 'Unknown'))
                         ELSE 'Mixed / multiple' END AS category,
                    CASE WHEN count(DISTINCT coalesce(business_line, 'Unknown')) = 1
                         THEN min(coalesce(business_line, 'Unknown'))
                         ELSE 'Mixed / multiple' END AS business_line
                FROM sku_product
                GROUP BY product_key
            )
            SELECT
                r.product_key,
                coalesce(r.product_name, 'Unknown product') AS product_name,
                coalesce(r.product_title, r.product_name, 'Unknown product') AS product_title,
                r.product_id,
                r.color,
                t.color_group,
                t.item_class,
                t.subcategory,
                t.category,
                t.business_line,
                r.source_price,
                d.first_seen_date,
                d.last_seen_date,
                d.sku_count
            FROM ranked r
            JOIN product_dates d USING (product_key)
            JOIN product_taxonomy t USING (product_key)
            WHERE r.row_rank = 1
            UNION ALL
            SELECT
                product_key,
                coalesce(max(product_title), 'Unknown product'),
                coalesce(max(product_title), 'Unknown product'),
                max(product_id),
                coalesce(max(color), 'Unknown'),
                coalesce(max(color_group), 'Unknown'),
                coalesce(max(item_class), 'Unknown'),
                coalesce(max(subcategory), 'Unknown'),
                coalesce(max(category), 'Unknown'),
                coalesce(max(business_line), 'Unknown'),
                max(source_price),
                min(order_date),
                max(order_date),
                0
            FROM raw_enriched
            WHERE sku IS NULL
            GROUP BY product_key
            """
        )

        daily = connection.execute(
            """
            SELECT
                order_date,
                count(*)::BIGINT AS source_rows,
                count(DISTINCT sku)::BIGINT AS active_skus,
                sum(revenue) AS daily_revenue,
                sum(units)::BIGINT AS daily_units
            FROM raw
            GROUP BY order_date
            ORDER BY order_date
            """
        ).fetchdf()
        daily_context, context_diagnostics = _build_daily_context(daily, sale_periods)

        # Auditable list of everything intentionally excluded by the exact-tag
        # rule. Revenue here is token-associated and therefore non-additive.
        connection.execute(
            """
            CREATE TABLE excluded_tags AS
            SELECT
                family_tag,
                CASE
                    WHEN family_tag = 'no_fam' THEN 'No family tag'
                    WHEN regexp_full_match(family_tag, '(sp|su|fa|ho|wt)[0-9]{2}d[0-9]+-family')
                         AND r.family_tag IS NULL THEN 'Canonical-looking tag absent from release calendar'
                    WHEN regexp_full_match(family_tag, '(sp|su|fa|ho|wt)[0-9]{2}d[0-9]+-[0-9]+-family')
                        THEN 'Drop extension / spotlight / capsule'
                    WHEN regexp_matches(family_tag, '(sp|su|fa|ho|wt)[0-9]{2}drops-family')
                        THEN 'Season rollup tag'
                    WHEN regexp_matches(family_tag, '(sp|su|fa|ho|wt)[0-9]{2}m')
                        THEN 'M-prefixed / men-specific family'
                    ELSE 'Other non-conventional family'
                END AS exclusion_reason,
                count(*)::BIGINT AS token_rows,
                count(DISTINCT sku)::BIGINT AS sku_count,
                sum(revenue) AS token_associated_revenue,
                min(order_date) AS first_observed_date,
                max(order_date) AS last_observed_date
            FROM family_tokens t
            LEFT JOIN valid_release_calendar r USING (family_tag)
            WHERE r.family_tag IS NULL
               OR NOT regexp_full_match(t.family_tag, '(sp|su|fa|ho|wt)[0-9]{2}d[0-9]+-family')
            GROUP BY family_tag, exclusion_reason
            """
        )

        copy_targets = {
            "product_fact": staging_dir / OUTPUT_FILES["fact"],
            "product_dimension": staging_dir / OUTPUT_FILES["products"],
            "product_membership": staging_dir / OUTPUT_FILES["membership"],
            "valid_release_calendar": staging_dir / OUTPUT_FILES["drops"],
            "excluded_tags": staging_dir / OUTPUT_FILES["excluded_tags"],
        }
        for table, target in copy_targets.items():
            connection.execute(
                f"COPY (SELECT * FROM {table}) TO '{_sql_string(target)}' "
                "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)"
            )
        daily_context.to_parquet(
            staging_dir / OUTPUT_FILES["context"], index=False, compression="zstd"
        )

        processed_revenue = float(
            _fetch_scalar(connection, "SELECT sum(revenue) FROM product_fact") or 0
        )
        processed_units = int(_fetch_scalar(connection, "SELECT sum(units) FROM product_fact") or 0)
        contribution = connection.execute(
            """
            SELECT
                CASE WHEN contribution_family = 'core' THEN 'Core'
                     WHEN contribution_family = 'rest' THEN 'Rest / no eligible conventional drop'
                     ELSE 'Eligible conventional drop' END AS bucket_type,
                sum(revenue) AS revenue,
                sum(units)::BIGINT AS units
            FROM product_fact GROUP BY 1 ORDER BY 1
            """
        ).fetchdf()
        membership_stats = connection.execute(
            """
            SELECT count(*) AS product_family_pairs,
                   count(DISTINCT product_key) AS member_products,
                   count(DISTINCT family_tag) AS represented_drops
            FROM product_membership
            """
        ).fetchdf().iloc[0].to_dict()
        taxonomy_conflicts = connection.execute(
            """
            WITH by_product AS (
                SELECT
                    product_key,
                    count(DISTINCT business_line) AS business_lines,
                    count(DISTINCT category) AS categories,
                    count(DISTINCT subcategory) AS subcategories,
                    count(DISTINCT item_class) AS item_classes,
                    sum(revenue) AS revenue
                FROM product_fact
                GROUP BY product_key
            )
            SELECT
                count(*) FILTER (WHERE business_lines > 1)::BIGINT
                    AS mixed_business_line_products,
                coalesce(sum(revenue) FILTER (WHERE business_lines > 1), 0)
                    AS mixed_business_line_revenue,
                count(*) FILTER (WHERE categories > 1)::BIGINT
                    AS mixed_category_products,
                coalesce(sum(revenue) FILTER (WHERE categories > 1), 0)
                    AS mixed_category_revenue,
                count(*) FILTER (WHERE subcategories > 1)::BIGINT
                    AS mixed_subcategory_products,
                coalesce(sum(revenue) FILTER (WHERE subcategories > 1), 0)
                    AS mixed_subcategory_revenue,
                count(*) FILTER (WHERE item_classes > 1)::BIGINT
                    AS mixed_item_class_products,
                coalesce(sum(revenue) FILTER (WHERE item_classes > 1), 0)
                    AS mixed_item_class_revenue
            FROM by_product
            """
        ).fetchdf().iloc[0].to_dict()

        quality: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "built_at_utc": datetime.now(timezone.utc).isoformat(),
            "sources": {
                "sales": str(sales_path.resolve()),
                "sales_bytes": sales_path.stat().st_size,
                "releases": str(releases_path.resolve()),
                "sale_periods": str(sale_periods_path.resolve())
                if sale_periods_path and sale_periods_path.exists()
                else None,
            },
            "raw": {
                "rows": raw_rows,
                "revenue": raw_revenue,
                "units": raw_units,
                "ingest_parse": {
                    key: int(value) for key, value in ingest_diagnostics.items()
                },
                "unique_key_duplicates": unique_key_duplicates,
                "apparent_duplicate_review": {
                    key: (float(value) if "revenue" in key else int(value))
                    for key, value in apparent_duplicate_review.items()
                },
                "metadata_instability": {
                    key: int(value) for key, value in metadata_instability.items()
                },
                "min_order_date": str(_fetch_scalar(connection, "SELECT min(order_date) FROM raw")),
                "max_order_date": str(_fetch_scalar(connection, "SELECT max(order_date) FROM raw")),
                "null_sku_rows": int(
                    _fetch_scalar(connection, "SELECT count(*) FROM raw WHERE sku IS NULL")
                ),
            },
            "processed": {
                "fact_rows": int(_fetch_scalar(connection, "SELECT count(*) FROM product_fact")),
                "products": int(
                    _fetch_scalar(connection, "SELECT count(*) FROM product_dimension")
                ),
                "revenue": processed_revenue,
                "units": processed_units,
                "revenue_delta_vs_raw": processed_revenue - raw_revenue,
                "units_delta_vs_raw": processed_units - raw_units,
                **{key: int(value) for key, value in membership_stats.items()},
                "taxonomy_conflicts": {
                    key: (float(value) if key.endswith("_revenue") else int(value))
                    for key, value in taxonomy_conflicts.items()
                },
            },
            "release_calendar": release_diagnostics,
            "daily_context": context_diagnostics,
            "methodology": {
                "canonical_regex": CANONICAL_FAMILY_RE.pattern,
                "family_assignment": (
                    "Core planning-status rows take precedence; otherwise choose the most recently "
                    "anchored validated conventional family attached to the product-color. Membership "
                    "starts no earlier than one day before its first observed exact tag (and never before "
                    "Early Access/Launch), then persists forward; all unmatched rows remain Rest."
                ),
                "product_key": (
                    "normalized product name + color using one coherent most-complete/latest "
                    "metadata record per SKU; product_id is retained but not trusted as identity"
                ),
                "taxonomy": (
                    "business line/category/subcategory/item class are retained from each SKU's "
                    "coherent metadata record in the additive fact; multi-taxonomy product-color "
                    "summaries are labeled Mixed / multiple instead of choosing one SKU arbitrarily"
                ),
                "revenue": "source revenue is preserved; supplied rolling fields and source price are not used",
                "source_duplicates": (
                    "distinct source unique keys are preserved; identical date/SKU/revenue/unit groups "
                    "are flagged for review rather than deleted"
                ),
            },
            "contribution_reconciliation": contribution.to_dict(orient="records"),
        }
        quality_path = staging_dir / OUTPUT_FILES["quality"]
        quality_path.write_text(json.dumps(quality, indent=2, default=str) + "\n")
        connection.close()

        publish_order = [key for key in OUTPUT_FILES if key != "quality"] + ["quality"]
        for key in publish_order:
            (staging_dir / OUTPUT_FILES[key]).replace(output_dir / OUTPUT_FILES[key])

    return quality


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sales", type=Path, default=Path("inputs.csv"))
    parser.add_argument("--releases", type=Path, default=Path("Product Release Dates.xlsx"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--sale-periods", type=Path, default=Path("config/sale_periods.csv"))
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--memory-limit", default="4GB")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    quality = build_data(
        sales_path=args.sales,
        releases_path=args.releases,
        output_dir=args.output_dir,
        sale_periods_path=args.sale_periods,
        threads=args.threads,
        memory_limit=args.memory_limit,
    )
    print(
        "Built family dashboard data: "
        f"{quality['processed']['fact_rows']:,} fact rows, "
        f"{quality['processed']['products']:,} products, "
        f"through {quality['daily_context']['latest_source_date']}."
    )
    print(
        "Revenue reconciliation delta: "
        f"${quality['processed']['revenue_delta_vs_raw']:,.6f}"
    )


if __name__ == "__main__":
    main()
