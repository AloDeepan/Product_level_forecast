from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable, Sequence

import duckdb
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data" / "processed"
FILES = {
    "fact": DATA_DIR / "product_daily.parquet",
    "products": DATA_DIR / "product_dimension.parquet",
    "membership": DATA_DIR / "product_drop_membership.parquet",
    "drops": DATA_DIR / "drop_calendar.parquet",
    "context": DATA_DIR / "daily_context.parquet",
    "excluded": DATA_DIR / "excluded_family_tags.parquet",
    "quality": DATA_DIR / "data_quality.json",
}

FALLBACK_COLORS = [
    "#2563EB",
    "#7C3AED",
    "#DB2777",
    "#EA580C",
    "#16A34A",
    "#0891B2",
    "#4F46E5",
    "#C026D3",
    "#D97706",
    "#0F766E",
]
CORE_COLOR = "#334155"
REST_COLOR = "#CBD5E1"


st.set_page_config(
    page_title="Alo Family Performance",
    page_icon="◒",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(
    """
    <style>
      .block-container {padding-top: 1.4rem; padding-bottom: 2.5rem; max-width: 1550px;}
      [data-testid="stMetric"] {background:#F8FAFC; border:1px solid #E2E8F0; border-radius:12px; padding:14px 16px;}
      [data-testid="stMetricLabel"] {color:#475569;}
      div[data-testid="stDataFrame"] {border:1px solid #E2E8F0; border-radius:10px; overflow:hidden;}
      .eyebrow {font-size:.76rem; text-transform:uppercase; letter-spacing:.12em; color:#64748B; font-weight:700;}
      .subtle {color:#64748B; font-size:.92rem;}
      .definition {background:#F8FAFC; border-left:4px solid #94A3B8; padding:10px 14px; border-radius:4px; color:#475569;}
    </style>
    """,
    unsafe_allow_html=True,
)


def sql_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


FACT = f"read_parquet('{sql_path(FILES['fact'])}')"
PRODUCTS = f"read_parquet('{sql_path(FILES['products'])}')"
MEMBERSHIP = f"read_parquet('{sql_path(FILES['membership'])}')"
DROPS = f"read_parquet('{sql_path(FILES['drops'])}')"
CONTEXT = f"read_parquet('{sql_path(FILES['context'])}')"
EXCLUDED = f"read_parquet('{sql_path(FILES['excluded'])}')"


def data_version() -> int:
    """Version all cached reads by the manifest published last by the builder."""

    return FILES["quality"].stat().st_mtime_ns


@st.cache_data(show_spinner=False)
def _query_frame(
    sql: str, params: tuple[Any, ...], generation: int
) -> pd.DataFrame:
    with duckdb.connect() as connection:
        connection.execute("PRAGMA threads=4")
        return connection.execute(sql, list(params)).fetchdf()


def query_frame(sql: str, params: tuple[Any, ...] = ()) -> pd.DataFrame:
    return _query_frame(sql, params, data_version())


@st.cache_data(show_spinner=False)
def _load_small_data(
    generation: int,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    quality = json.loads(FILES["quality"].read_text())
    drops = pd.read_parquet(FILES["drops"])
    products = pd.read_parquet(FILES["products"])
    context = pd.read_parquet(FILES["context"])
    for column in ["early_access_date", "launch_date", "anchor_date"]:
        drops[column] = pd.to_datetime(drops[column])
    context["order_date"] = pd.to_datetime(context["order_date"])
    return quality, drops, products, context


def load_small_data() -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    return _load_small_data(data_version())


def load_taxonomy_options() -> dict[str, list[str]]:
    values = query_frame(
        f"""
        SELECT 'business_line' AS dimension, business_line AS value FROM {FACT} GROUP BY 2
        UNION ALL
        SELECT 'category', category FROM {FACT} GROUP BY 2
        UNION ALL
        SELECT 'subcategory', subcategory FROM {FACT} GROUP BY 2
        UNION ALL
        SELECT 'item_class', item_class FROM {FACT} GROUP BY 2
        ORDER BY dimension, value
        """
    )
    return {
        dimension: group["value"].dropna().astype(str).tolist()
        for dimension, group in values.groupby("dimension", sort=False)
    }


def placeholders(values: Sequence[Any]) -> str:
    return ",".join("?" for _ in values)


def metric_label(metric: str) -> str:
    return "Revenue" if metric == "revenue" else "Units"


def format_metric(value: float, metric: str, compact: bool = False) -> str:
    if pd.isna(value):
        return "—"
    if metric == "units":
        return f"{value / 1_000_000:.1f}M" if compact and abs(value) >= 1_000_000 else f"{value:,.0f}"
    if compact:
        absolute = abs(value)
        if absolute >= 1_000_000_000:
            return f"${value / 1_000_000_000:.2f}B"
        if absolute >= 1_000_000:
            return f"${value / 1_000_000:.1f}M"
        if absolute >= 1_000:
            return f"${value / 1_000:.1f}K"
    return f"${value:,.0f}"


def family_name(tag: str, drop_lookup: dict[str, dict[str, Any]], include_color: bool = False) -> str:
    if tag == "core":
        return "Core"
    if tag == "rest":
        return "Rest of Families"
    record = drop_lookup.get(tag, {})
    label = record.get("drop_label", tag.removesuffix("-family").upper())
    color = record.get("color_story")
    if include_color and pd.notna(color) and str(color).strip():
        return f"{label} · {color}"
    return label


def family_palette(tags: Iterable[str], drop_lookup: dict[str, dict[str, Any]]) -> dict[str, str]:
    palette = {"Core": CORE_COLOR, "Rest of Families": REST_COLOR}
    for index, tag in enumerate(tags):
        record = drop_lookup.get(tag, {})
        color = record.get("primary_hex")
        if not isinstance(color, str) or not color.startswith("#") or len(color) != 7:
            color = FALLBACK_COLORS[index % len(FALLBACK_COLORS)]
        palette[family_name(tag, drop_lookup)] = color
    return palette


def dimension_conditions(
    selections: dict[str, list[str]], alias: str = "f"
) -> tuple[list[str], list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    for column, values in selections.items():
        if values:
            clauses.append(f"{alias}.{column} IN ({placeholders(values)})")
            params.extend(values)
    return clauses, params


def sale_condition(mode: str, alias: str = "c") -> str | None:
    if mode == "Exclude configured sale periods":
        return f"NOT {alias}.is_configured_sale"
    if mode == "Exclude sale periods + volume spikes":
        return f"NOT {alias}.is_configured_sale AND NOT {alias}.is_volume_spike"
    return None


def make_calendar_grid(
    frame: pd.DataFrame,
    groups: Sequence[str],
    group_column: str,
    start: date,
    end: date,
    granularity: str,
    context: pd.DataFrame,
    sale_mode: str,
    value_columns: Sequence[str],
) -> pd.DataFrame:
    """Complete a calendar series and expose excluded/partial bucket coverage."""

    unique_groups = list(dict.fromkeys(groups))
    start_ts = pd.Timestamp(start).normalize()
    end_ts = pd.Timestamp(end).normalize()
    if not unique_groups or end_ts < start_ts:
        return frame

    calendar = pd.DataFrame({"order_date": pd.date_range(start_ts, end_ts, freq="D")})
    context_flags = context[
        ["order_date", "is_configured_sale", "is_volume_spike"]
    ].copy()
    context_flags["order_date"] = context_flags["order_date"].dt.normalize()
    calendar = calendar.merge(context_flags, how="left", on="order_date")
    calendar[["is_configured_sale", "is_volume_spike"]] = calendar[
        ["is_configured_sale", "is_volume_spike"]
    ].fillna(False)
    if sale_mode == "Exclude configured sale periods":
        calendar["is_excluded"] = calendar["is_configured_sale"]
    elif sale_mode == "Exclude sale periods + volume spikes":
        calendar["is_excluded"] = (
            calendar["is_configured_sale"] | calendar["is_volume_spike"]
        )
    else:
        calendar["is_excluded"] = False

    if granularity == "Weekly":
        calendar["period"] = calendar["order_date"] - pd.to_timedelta(
            calendar["order_date"].dt.weekday, unit="D"
        )
        expected_days = 7
    else:
        calendar["period"] = calendar["order_date"]
        expected_days = 1

    coverage = calendar.groupby("period", as_index=False).agg(
        range_days=("order_date", "size"),
        included_days=("is_excluded", lambda values: int((~values).sum())),
    )
    coverage["expected_days"] = expected_days
    grid = coverage[["period"]].merge(
        pd.DataFrame({group_column: unique_groups}), how="cross"
    )
    prepared = frame.copy()
    if "period" in prepared:
        prepared["period"] = pd.to_datetime(prepared["period"]).dt.normalize()
    completed = grid.merge(prepared, how="left", on=["period", group_column])
    completed = completed.merge(coverage, how="left", on="period")
    has_included_days = completed["included_days"].gt(0)
    for column in value_columns:
        if column not in completed:
            completed[column] = np.nan
        completed.loc[has_included_days, column] = completed.loc[
            has_included_days, column
        ].fillna(0)
        completed.loc[~has_included_days, column] = np.nan
    return completed.sort_values(["period", group_column]).reset_index(drop=True)


def add_context_bands(
    figure: go.Figure,
    context: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    show_spikes: bool = True,
) -> None:
    view = context[context["order_date"].between(start, end)].copy()
    sale_rows = view[view["is_configured_sale"]]
    for period_name, group in sale_rows.groupby("sale_period_name", dropna=True):
        figure.add_vrect(
            x0=group["order_date"].min(),
            x1=group["order_date"].max() + pd.Timedelta(days=1),
            fillcolor="#F59E0B",
            opacity=0.10,
            line_width=0,
            annotation_text=str(period_name),
            annotation_position="top left",
        )
    if show_spikes:
        spikes = view[view["is_volume_spike"] & ~view["is_configured_sale"]]
        for spike_date in spikes["order_date"]:
            figure.add_vrect(
                x0=spike_date,
                x1=spike_date + pd.Timedelta(days=1),
                fillcolor="#FB7185",
                opacity=0.10,
                line_width=0,
            )
    incomplete = view[view["is_incomplete_date"]]
    for incomplete_date in incomplete["order_date"]:
        figure.add_vline(
            x=incomplete_date,
            line_color="#DC2626",
            line_dash="dash",
        )
        figure.add_annotation(
            x=incomplete_date,
            y=1,
            yref="paper",
            text="Partial day",
            showarrow=False,
            xanchor="right",
            yanchor="bottom",
            font=dict(color="#DC2626", size=11),
        )


def style_figure(figure: go.Figure, height: int = 480) -> go.Figure:
    figure.update_layout(
        height=height,
        margin=dict(l=20, r=20, t=55, b=25),
        paper_bgcolor="white",
        plot_bgcolor="white",
        hovermode="x unified",
        legend_title_text="",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        font=dict(family="Inter, Arial, sans-serif", color="#0F172A"),
    )
    figure.update_xaxes(showgrid=False, linecolor="#CBD5E1")
    figure.update_yaxes(gridcolor="#E2E8F0", zeroline=False)
    return figure


def overview_data(
    latest_three: list[str],
    start: date,
    end: date,
    granularity: str,
    selections: dict[str, list[str]],
    sale_mode: str,
) -> pd.DataFrame:
    bucket_case = "'rest'"
    params: list[Any] = []
    if latest_three:
        bucket_case = (
            "CASE WHEN f.planning_status = 'Core' THEN 'core' "
            f"WHEN f.assigned_family IN ({placeholders(latest_three)}) THEN f.assigned_family "
            "ELSE 'rest' END"
        )
        params.extend(latest_three)
    date_bucket = "f.order_date" if granularity == "Daily" else "date_trunc('week', f.order_date)::DATE"
    clauses = ["f.order_date BETWEEN ? AND ?"]
    params.extend([start, end])
    dimension_clauses, dimension_params = dimension_conditions(selections)
    clauses.extend(dimension_clauses)
    params.extend(dimension_params)
    sale_clause = sale_condition(sale_mode)
    if sale_clause:
        clauses.append(sale_clause)
    sql = f"""
        SELECT
            {date_bucket} AS period,
            {bucket_case} AS bucket,
            sum(f.revenue) AS revenue,
            sum(f.units) AS units
        FROM {FACT} f
        JOIN {PRODUCTS} d USING (product_key)
        JOIN {CONTEXT} c ON c.order_date = f.order_date
        WHERE {' AND '.join(clauses)}
        GROUP BY period, bucket
        ORDER BY period, bucket
    """
    return query_frame(sql, tuple(params))


def assigned_family_trend(
    tags: list[str],
    start: date,
    cutoff: date,
    granularity: str,
    metric: str,
    selections: dict[str, list[str]],
    sale_mode: str,
) -> pd.DataFrame:
    if not tags:
        return pd.DataFrame()
    period = "f.order_date" if granularity == "Daily" else "date_trunc('week', f.order_date)::DATE"
    bucket_case = (
        "CASE WHEN f.planning_status = 'Core' THEN 'core' "
        f"WHEN f.assigned_family IN ({placeholders(tags)}) THEN f.assigned_family "
        "ELSE 'rest' END"
    )
    clauses = ["f.order_date BETWEEN ? AND ?"]
    params: list[Any] = [*tags, start, cutoff]
    dim_clauses, dim_params = dimension_conditions(selections)
    clauses.extend(dim_clauses)
    params.extend(dim_params)
    sale_clause = sale_condition(sale_mode)
    if sale_clause:
        clauses.append(sale_clause)
    return query_frame(
        f"""
        SELECT {period} AS period, {bucket_case} AS family_tag,
               sum(f.{metric}) AS metric_value
        FROM {FACT} f
        JOIN {PRODUCTS} d USING (product_key)
        JOIN {CONTEXT} c ON c.order_date = f.order_date
        WHERE {' AND '.join(clauses)}
        GROUP BY period, family_tag
        ORDER BY period, family_tag
        """,
        tuple(params),
    )


def cohort_daily(
    tags: list[str],
    cutoff: date,
    window_days: int,
    anchor_choice: str,
    selections: dict[str, list[str]],
    sale_mode: str,
    extra_dimension: tuple[str, str] | None = None,
    product_name: str | None = None,
    colors: list[str] | None = None,
    group_color: bool = False,
) -> pd.DataFrame:
    if not tags:
        return pd.DataFrame()
    anchor = "coalesce(r.early_access_date, r.launch_date)" if anchor_choice == "Early access" else "r.launch_date"
    clauses = [
        f"m.family_tag IN ({placeholders(tags)})",
        "f.planning_status <> 'Core'",
        "f.order_date <= ?",
        f"date_diff('day', {anchor}, f.order_date) BETWEEN 0 AND ?",
        f"f.order_date >= greatest({anchor}, m.first_tag_observed_date - INTERVAL 1 DAY)",
    ]
    params: list[Any] = [*tags, cutoff, window_days - 1]
    dim_clauses, dim_params = dimension_conditions(selections)
    clauses.extend(dim_clauses)
    params.extend(dim_params)
    if extra_dimension:
        column, value = extra_dimension
        if column not in {"business_line", "category", "subcategory", "item_class"}:
            raise ValueError("Unsupported dimension")
        clauses.append(f"f.{column} = ?")
        params.append(value)
    if product_name:
        clauses.append("d.product_name = ?")
        params.append(product_name)
    if colors is not None:
        if colors:
            clauses.append(f"d.color IN ({placeholders(colors)})")
            params.extend(colors)
        else:
            clauses.append("FALSE")
    sale_clause = sale_condition(sale_mode)
    if sale_clause:
        clauses.append(sale_clause)
    color_select = ", d.color" if group_color else ""
    color_group = ", d.color" if group_color else ""
    return query_frame(
        f"""
        SELECT
            m.family_tag,
            date_diff('day', {anchor}, f.order_date)::INTEGER AS launch_day
            {color_select},
            sum(f.revenue) AS revenue,
            sum(f.units) AS units,
            sum(f.revenue) FILTER (WHERE c.is_configured_sale) AS configured_sale_revenue,
            sum(f.units) FILTER (WHERE c.is_configured_sale) AS configured_sale_units,
            sum(f.revenue) FILTER (WHERE c.is_volume_spike AND NOT c.is_configured_sale) AS spike_revenue,
            sum(f.units) FILTER (WHERE c.is_volume_spike AND NOT c.is_configured_sale) AS spike_units,
            count(DISTINCT f.product_key) AS active_products
        FROM {FACT} f
        JOIN {MEMBERSHIP} m USING (product_key)
        JOIN {DROPS} r USING (family_tag)
        JOIN {PRODUCTS} d USING (product_key)
        JOIN {CONTEXT} c ON c.order_date = f.order_date
        WHERE {' AND '.join(clauses)}
        GROUP BY m.family_tag, launch_day {color_group}
        ORDER BY m.family_tag, launch_day {color_group}
        """,
        tuple(params),
    )


def product_performance(
    tags: list[str],
    cutoff: date,
    window_days: int,
    anchor_choice: str,
    selections: dict[str, list[str]],
    sale_mode: str,
) -> pd.DataFrame:
    if not tags:
        return pd.DataFrame()
    anchor = "coalesce(r.early_access_date, r.launch_date)" if anchor_choice == "Early access" else "r.launch_date"
    clauses = [
        f"m.family_tag IN ({placeholders(tags)})",
        "f.planning_status <> 'Core'",
        "f.order_date <= ?",
        f"date_diff('day', {anchor}, f.order_date) BETWEEN 0 AND ?",
        f"f.order_date >= greatest({anchor}, m.first_tag_observed_date - INTERVAL 1 DAY)",
    ]
    params: list[Any] = [*tags, cutoff, window_days - 1]
    dim_clauses, dim_params = dimension_conditions(selections)
    clauses.extend(dim_clauses)
    params.extend(dim_params)
    sale_clause = sale_condition(sale_mode)
    if sale_clause:
        clauses.append(sale_clause)
    return query_frame(
        f"""
        SELECT
            m.family_tag,
            d.product_name,
            d.product_title,
            d.color,
            CASE WHEN count(DISTINCT f.business_line) = 1
                 THEN min(f.business_line) ELSE 'Mixed / multiple' END AS business_line,
            CASE WHEN count(DISTINCT f.category) = 1
                 THEN min(f.category) ELSE 'Mixed / multiple' END AS category,
            CASE WHEN count(DISTINCT f.subcategory) = 1
                 THEN min(f.subcategory) ELSE 'Mixed / multiple' END AS subcategory,
            CASE WHEN count(DISTINCT f.item_class) = 1
                 THEN min(f.item_class) ELSE 'Mixed / multiple' END AS item_class,
            sum(f.revenue) AS revenue,
            sum(f.units) AS units,
            sum(f.revenue) FILTER (
                WHERE date_diff('day', {anchor}, f.order_date) BETWEEN 0 AND 6
            ) AS week_1_revenue,
            sum(f.revenue) FILTER (
                WHERE date_diff('day', {anchor}, f.order_date) BETWEEN 7 AND 13
            ) AS week_2_revenue,
            sum(f.units) FILTER (
                WHERE date_diff('day', {anchor}, f.order_date) BETWEEN 0 AND 6
            ) AS week_1_units,
            sum(f.units) FILTER (
                WHERE date_diff('day', {anchor}, f.order_date) BETWEEN 7 AND 13
            ) AS week_2_units,
            count(DISTINCT f.order_date) AS active_days
        FROM {FACT} f
        JOIN {MEMBERSHIP} m USING (product_key)
        JOIN {DROPS} r USING (family_tag)
        JOIN {PRODUCTS} d USING (product_key)
        JOIN {CONTEXT} c ON c.order_date = f.order_date
        WHERE {' AND '.join(clauses)}
        GROUP BY
            m.family_tag, d.product_name, d.product_title, d.color
        ORDER BY revenue DESC
        """,
        tuple(params),
    )


def category_performance(
    tags: list[str],
    cutoff: date,
    window_days: int,
    anchor_choice: str,
    selections: dict[str, list[str]],
    sale_mode: str,
    level_column: str,
) -> pd.DataFrame:
    """Aggregate a cohort directly from fact taxonomy, preserving SKU splits."""

    if not tags:
        return pd.DataFrame()
    if level_column not in {"business_line", "category", "subcategory", "item_class"}:
        raise ValueError("Unsupported dimension")
    anchor = "coalesce(r.early_access_date, r.launch_date)" if anchor_choice == "Early access" else "r.launch_date"
    clauses = [
        f"m.family_tag IN ({placeholders(tags)})",
        "f.planning_status <> 'Core'",
        "f.order_date <= ?",
        f"date_diff('day', {anchor}, f.order_date) BETWEEN 0 AND ?",
        f"f.order_date >= greatest({anchor}, m.first_tag_observed_date - INTERVAL 1 DAY)",
    ]
    params: list[Any] = [*tags, cutoff, window_days - 1]
    dimension_clauses, dimension_params = dimension_conditions(selections)
    clauses.extend(dimension_clauses)
    params.extend(dimension_params)
    sale_clause = sale_condition(sale_mode)
    if sale_clause:
        clauses.append(sale_clause)
    return query_frame(
        f"""
        SELECT
            m.family_tag,
            f.{level_column} AS dimension_value,
            sum(f.revenue) AS revenue,
            sum(f.units) AS units
        FROM {FACT} f
        JOIN {MEMBERSHIP} m USING (product_key)
        JOIN {DROPS} r USING (family_tag)
        JOIN {CONTEXT} c ON c.order_date = f.order_date
        WHERE {' AND '.join(clauses)}
        GROUP BY m.family_tag, f.{level_column}
        ORDER BY m.family_tag, revenue DESC
        """,
        tuple(params),
    )


def make_aligned_grid(
    frame: pd.DataFrame,
    selected_drops: pd.DataFrame,
    cutoff: pd.Timestamp,
    window_days: int,
    anchor_choice: str,
    context: pd.DataFrame,
    sale_mode: str,
) -> pd.DataFrame:
    if selected_drops.empty:
        return frame
    rows: list[pd.DataFrame] = []
    anchor_column = "anchor_date" if anchor_choice == "Early access" else "launch_date"
    numeric = [
        "revenue",
        "units",
        "configured_sale_revenue",
        "configured_sale_units",
        "spike_revenue",
        "spike_units",
        "active_products",
    ]
    if sale_mode == "Exclude configured sale periods":
        excluded_dates = set(context.loc[context["is_configured_sale"], "order_date"].dt.normalize())
    elif sale_mode == "Exclude sale periods + volume spikes":
        excluded_dates = set(
            context.loc[
                context["is_configured_sale"] | context["is_volume_spike"], "order_date"
            ].dt.normalize()
        )
    else:
        excluded_dates = set()
    for drop in selected_drops.itertuples(index=False):
        anchor = pd.Timestamp(getattr(drop, anchor_column))
        available = max(0, min(window_days, (cutoff - anchor).days + 1))
        grid = pd.DataFrame({"launch_day": np.arange(available, dtype=int)})
        grid["calendar_date"] = anchor + pd.to_timedelta(grid["launch_day"], unit="D")
        grid["is_excluded"] = grid["calendar_date"].isin(excluded_dates)
        family = frame[frame["family_tag"].eq(drop.family_tag)].copy()
        family = grid.merge(family, how="left", on="launch_day")
        family["family_tag"] = drop.family_tag
        for column in numeric:
            if column in family:
                family.loc[~family["is_excluded"], column] = family.loc[
                    ~family["is_excluded"], column
                ].fillna(0)
                family.loc[family["is_excluded"], column] = np.nan
        rows.append(family)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def make_product_series_grid(
    frame: pd.DataFrame,
    selected_drops: pd.DataFrame,
    cutoff: pd.Timestamp,
    window_days: int,
    anchor_choice: str,
    context: pd.DataFrame,
    sale_mode: str,
) -> pd.DataFrame:
    """Insert zero-sales days so product lines do not bridge missing dates."""

    if frame.empty:
        return frame
    anchor_column = "anchor_date" if anchor_choice == "Early access" else "launch_date"
    anchors = selected_drops.set_index("family_tag")[anchor_column].to_dict()
    numeric = [
        "revenue",
        "units",
        "configured_sale_revenue",
        "configured_sale_units",
        "spike_revenue",
        "spike_units",
        "active_products",
    ]
    if sale_mode == "Exclude configured sale periods":
        excluded_dates = set(context.loc[context["is_configured_sale"], "order_date"].dt.normalize())
    elif sale_mode == "Exclude sale periods + volume spikes":
        excluded_dates = set(
            context.loc[
                context["is_configured_sale"] | context["is_volume_spike"], "order_date"
            ].dt.normalize()
        )
    else:
        excluded_dates = set()
    rows: list[pd.DataFrame] = []
    for (family_tag, color), series in frame.groupby(["family_tag", "color"], dropna=False):
        anchor = pd.Timestamp(anchors[family_tag])
        available = max(0, min(window_days, (cutoff - anchor).days + 1))
        grid = pd.DataFrame({"launch_day": np.arange(available, dtype=int)})
        grid["calendar_date"] = anchor + pd.to_timedelta(grid["launch_day"], unit="D")
        grid["is_excluded"] = grid["calendar_date"].isin(excluded_dates)
        series = grid.merge(series, how="left", on="launch_day")
        series["family_tag"] = family_tag
        series["color"] = color
        for column in numeric:
            if column in series:
                series.loc[~series["is_excluded"], column] = series.loc[
                    ~series["is_excluded"], column
                ].fillna(0)
                series.loc[series["is_excluded"], column] = np.nan
        rows.append(series)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def aligned_chart(
    daily: pd.DataFrame,
    selected_drops: pd.DataFrame,
    metric: str,
    granularity: str,
    cumulative: bool,
    drop_lookup: dict[str, dict[str, Any]],
) -> go.Figure:
    if granularity == "Weekly":
        daily = daily.assign(period=(daily["launch_day"] // 7).astype(int) + 1)
        grouped = daily.groupby(["family_tag", "period"], as_index=False).agg(
            metric_value=(metric, lambda values: values.sum(min_count=1)),
            configured_sale=(f"configured_sale_{metric}", lambda values: values.sum(min_count=1)),
            spike=(f"spike_{metric}", lambda values: values.sum(min_count=1)),
            calendar_days=("launch_day", "nunique"),
            included_days=("is_excluded", lambda values: int((~values).sum())),
        )
        grouped["x_label"] = grouped["period"].map(lambda value: f"Week {value}")
        grouped["expected_days"] = 7
        x_column = "period"
        x_title = "Week since release"
    else:
        grouped = daily.rename(
            columns={
                metric: "metric_value",
                f"configured_sale_{metric}": "configured_sale",
                f"spike_{metric}": "spike",
            }
        )
        grouped["x_label"] = grouped["launch_day"].map(lambda value: f"Day {value}")
        grouped["calendar_days"] = 1
        grouped["included_days"] = (~grouped["is_excluded"]).astype(int)
        grouped["expected_days"] = 1
        x_column = "launch_day"
        x_title = "Day since release"
    if cumulative:
        grouped["metric_value"] = grouped.groupby("family_tag")["metric_value"].cumsum()
        grouped["configured_sale"] = grouped.groupby("family_tag")["configured_sale"].cumsum()
        grouped["spike"] = grouped.groupby("family_tag")["spike"].cumsum()
    grouped["context_share"] = np.where(
        grouped["metric_value"].ne(0),
        (grouped["configured_sale"].fillna(0) + grouped["spike"].fillna(0))
        / grouped["metric_value"].abs(),
        0,
    )
    palette = family_palette(selected_drops["family_tag"].tolist(), drop_lookup)
    figure = go.Figure()
    for tag in selected_drops["family_tag"]:
        family = grouped[grouped["family_tag"].eq(tag)]
        name = family_name(tag, drop_lookup)
        figure.add_trace(
            go.Scatter(
                x=family[x_column],
                y=family["metric_value"],
                mode="lines+markers",
                name=name,
                line=dict(color=palette[name], width=2.5),
                marker=dict(
                    size=np.where(
                        family["context_share"].gt(0)
                        | family["included_days"].lt(family["calendar_days"])
                        | ((granularity == "Weekly") & family["calendar_days"].lt(7)),
                        7,
                        4,
                    ),
                    symbol=np.where(
                        family["context_share"].gt(0),
                        "diamond",
                        np.where(
                            family["included_days"].lt(family["calendar_days"])
                            | ((granularity == "Weekly") & family["calendar_days"].lt(7)),
                            "square-open",
                            "circle",
                        ),
                    ),
                ),
                customdata=np.column_stack(
                    [
                        family["x_label"],
                        family["configured_sale"].fillna(0),
                        family["spike"].fillna(0),
                        family["included_days"],
                        family["expected_days"],
                    ]
                ),
                hovertemplate=(
                    "%{customdata[0]}<br>"
                    + ("Cumulative " if cumulative else "")
                    + metric_label(metric)
                    + ": %{y:,.0f}<br>Configured-sale portion: %{customdata[1]:,.0f}"
                    "<br>Other volume-spike portion: %{customdata[2]:,.0f}"
                    "<br>Included coverage: %{customdata[3]:.0f}/%{customdata[4]:.0f} days"
                    "<extra>%{fullData.name}</extra>"
                ),
                connectgaps=False,
            )
        )
    figure.update_layout(
        title=f"{'Cumulative ' if cumulative else ''}{metric_label(metric)} by release age",
        xaxis_title=x_title,
        yaxis_title=metric_label(metric),
    )
    return style_figure(figure, 520)


def family_summary(
    daily: pd.DataFrame,
    selected_drops: pd.DataFrame,
    metric: str,
    cutoff: pd.Timestamp,
    anchor_choice: str,
) -> pd.DataFrame:
    anchor_column = "anchor_date" if anchor_choice == "Early access" else "launch_date"
    rows = []
    for drop in selected_drops.itertuples(index=False):
        family = daily[daily["family_tag"].eq(drop.family_tag)]
        anchor = pd.Timestamp(getattr(drop, anchor_column))
        available = int(family["launch_day"].nunique())
        included_days = int((~family["is_excluded"]).sum())
        week_1_included = int(
            ((~family["is_excluded"]) & family["launch_day"].between(0, 6)).sum()
        )
        week_2_included = int(
            ((~family["is_excluded"]) & family["launch_day"].between(7, 13)).sum()
        )
        first_28_included = int(
            ((~family["is_excluded"]) & family["launch_day"].between(0, 27)).sum()
        )
        week_1 = family.loc[family["launch_day"].between(0, 6), metric].sum(min_count=1)
        week_2 = family.loc[family["launch_day"].between(7, 13), metric].sum(min_count=1)
        first_28 = family.loc[family["launch_day"].between(0, 27), metric].sum(min_count=1)
        total = family[metric].sum(min_count=1)
        context_value = (
            family[f"configured_sale_{metric}"].fillna(0).sum()
            + family[f"spike_{metric}"].fillna(0).sum()
        )
        rows.append(
            {
                "Family": drop.drop_label,
                "Color story": drop.color_story,
                "Release anchor": anchor.date(),
                "Days available": available,
                "Days included": included_days,
                "W1 included days": week_1_included,
                "W2 included days": week_2_included,
                f"Week 1 {metric_label(metric)}": week_1,
                f"Week 2 {metric_label(metric)}": week_2,
                "W2 vs W1": (
                    week_2 / week_1 - 1
                    if week_1 and week_1_included == 7 and week_2_included == 7
                    else np.nan
                ),
                f"First 28D {metric_label(metric)}": first_28,
                f"Window {metric_label(metric)}": total,
                "Sale / spike share": context_value / total if total else 0,
                "Week 1 complete": available >= 7 and week_1_included == 7,
                "Week 2 complete": available >= 14 and week_2_included == 7,
                "28D complete": available >= 28 and first_28_included == 28,
            }
        )
    return pd.DataFrame(rows)


missing_files = [path for path in FILES.values() if not path.exists()]
if missing_files:
    st.error("The prepared dashboard data is missing. Build it before starting Streamlit.")
    st.code("python3 build_dashboard_data.py\nstreamlit run app.py", language="bash")
    st.stop()

quality, drops, products, context = load_small_data()
taxonomy_options = load_taxonomy_options()
drop_lookup = drops.set_index("family_tag").to_dict(orient="index")
source_max = pd.Timestamp(quality["daily_context"]["latest_source_date"])
complete_max = pd.Timestamp(quality["daily_context"]["latest_complete_date"])
source_min = pd.Timestamp(quality["raw"]["min_order_date"])

st.markdown('<div class="eyebrow">Merchandising intelligence</div>', unsafe_allow_html=True)
st.title("Family Performance")
st.markdown(
    "Track contribution, compare drop cohorts at the same release age, and inspect which products and categories repeat across families."
)

with st.sidebar:
    st.header("Analysis controls")
    reference_date = st.date_input(
        "Family reference date",
        value=source_max.date(),
        min_value=source_min.date(),
        max_value=source_max.date(),
        help="Selects the latest validated drops available on this date.",
    )
    anchor_choice = st.radio(
        "Release anchor",
        ["Early access", "Public launch"],
        horizontal=True,
        help="Controls latest-family eligibility and day 0 in cohort comparisons.",
    )
    analysis_through = st.date_input(
        "Performance through",
        value=complete_max.date(),
        min_value=source_min.date(),
        max_value=source_max.date(),
        help="Cuts off every performance view without changing which family set is selected.",
    )
    analysis_cutoff = pd.Timestamp(analysis_through)
    reference_anchor_column = "anchor_date" if anchor_choice == "Early access" else "launch_date"
    eligible_drops = drops[drops[reference_anchor_column].dt.date <= reference_date].sort_values(
        [reference_anchor_column, "launch_date", "family_tag"], ascending=[False, False, False]
    )
    latest_ten = eligible_drops.head(10).copy()
    latest_three = latest_ten.head(3).copy()

    metric = st.radio("Measure", ["revenue", "units"], format_func=metric_label, horizontal=True)
    granularity = st.radio("Time grain", ["Daily", "Weekly"], horizontal=True)
    sale_mode = st.selectbox(
        "Promotional treatment",
        [
            "Keep and flag",
            "Exclude configured sale periods",
            "Exclude sale periods + volume spikes",
        ],
        help="Volume spikes are statistical flags, not assumed sale dates.",
    )

    st.divider()
    st.subheader("Product filters")
    selections: dict[str, list[str]] = {}
    filter_labels = {
        "business_line": "Business line",
        "category": "Category",
        "subcategory": "Subcategory",
        "item_class": "Item class",
    }
    for column, label in filter_labels.items():
        values = taxonomy_options.get(column, [])
        selections[column] = st.multiselect(label, values, default=[])

    st.divider()
    st.caption(f"Source through {source_max:%b %-d, %Y}")
    if complete_max < source_max:
        st.warning(
            f"{source_max:%b %-d} is partial. Comparisons default through {complete_max:%b %-d}."
        )

if latest_ten.empty:
    st.error("No validated conventional drops exist on or before the selected reference date.")
    st.stop()

default_start = max(source_min, latest_ten[reference_anchor_column].min())
default_range_start = min(default_start.date(), analysis_through)
with st.sidebar:
    calendar_range = st.date_input(
        "Overview calendar range",
        value=(default_range_start, analysis_through),
        min_value=source_min.date(),
        max_value=source_max.date(),
    )
if isinstance(calendar_range, (tuple, list)) and len(calendar_range) == 2:
    calendar_start, calendar_end = calendar_range
else:
    calendar_start = calendar_end = calendar_range  # type: ignore[assignment]
calendar_query_end = min(calendar_end, analysis_through)
calendar_query_start = min(calendar_start, calendar_query_end)

if calendar_end > analysis_through:
    st.info(f"Overview is capped at the Performance through date: {analysis_through:%B %-d, %Y}.")

if calendar_end > complete_max.date() or analysis_through > complete_max.date():
    st.warning(
        f"The selected range includes partial source date {source_max:%B %-d}; use directional results with care."
    )

latest_labels = {
    row.family_tag: family_name(row.family_tag, drop_lookup, include_color=True)
    for row in latest_ten.itertuples(index=False)
}

tab_overview, tab_drops, tab_products, tab_category, tab_context = st.tabs(
    ["Overview", "Drop comparison", "Products", "Category", "Data context"]
)

with tab_overview:
    st.subheader("Latest three contribution")
    st.markdown(
        '<div class="definition">Mutually exclusive view: Core + the three latest validated drops + every other row in Rest of Families.</div>',
        unsafe_allow_html=True,
    )
    overview = overview_data(
        latest_three["family_tag"].tolist(),
        calendar_query_start,
        calendar_query_end,
        granularity,
        selections,
        sale_mode,
    )
    overview = make_calendar_grid(
        overview,
        ["rest", "core", *latest_three["family_tag"].tolist()],
        "bucket",
        calendar_query_start,
        calendar_query_end,
        granularity,
        context,
        sale_mode,
        ["revenue", "units"],
    )
    overview["Family"] = overview["bucket"].map(lambda value: family_name(value, drop_lookup))
    total_value = overview[metric].sum()
    bucket_totals = overview.groupby("Family")[metric].sum()
    columns = st.columns(6)
    ordered_kpis = [
        ("Total", total_value),
        ("Core", bucket_totals.get("Core", 0)),
        *[
            (family_name(tag, drop_lookup), bucket_totals.get(family_name(tag, drop_lookup), 0))
            for tag in latest_three["family_tag"]
        ],
        ("Rest of Families", bucket_totals.get("Rest of Families", 0)),
    ]
    for column, (label, value) in zip(columns, ordered_kpis):
        share = value / total_value if total_value else 0
        column.metric(label, format_metric(value, metric, compact=True), None if label == "Total" else f"{share:.1%} share")

    view_mode = st.radio("Chart display", ["Value", "Share"], horizontal=True, key="overview_mode")
    palette = family_palette(latest_three["family_tag"].tolist(), drop_lookup)
    bucket_order = ["Rest of Families", "Core"] + [
        family_name(tag, drop_lookup) for tag in reversed(latest_three["family_tag"].tolist())
    ]
    figure = go.Figure()
    for family in bucket_order:
        family_data = overview[overview["Family"].eq(family)].sort_values("period")
        if family_data.empty:
            continue
        if view_mode == "Share":
            period_total = overview.groupby("period")[metric].transform(
                lambda values: values.sum(min_count=1)
            )
            overview_share = overview.assign(
                plot_value=overview[metric].div(period_total.where(period_total.ne(0)))
            )
            family_data = overview_share[overview_share["Family"].eq(family)].sort_values("period")
        else:
            family_data = family_data.assign(plot_value=family_data[metric])
        is_partial = family_data["included_days"].lt(family_data["expected_days"])
        figure.add_trace(
            go.Scatter(
                x=family_data["period"],
                y=family_data["plot_value"],
                mode="lines+markers",
                stackgroup="one",
                name=family,
                line=dict(width=1.2, color=palette.get(family, REST_COLOR)),
                marker=dict(
                    size=np.where(is_partial, 6, 0),
                    symbol=np.where(is_partial, "square-open", "circle"),
                ),
                customdata=np.column_stack(
                    [family_data["included_days"], family_data["expected_days"]]
                ),
                hovertemplate=(
                    "%{x|%b %d, %Y}<br>"
                    + ("Share: %{y:.1%}" if view_mode == "Share" else f"{metric_label(metric)}: %{{y:,.0f}}")
                    + "<br>Included coverage: %{customdata[0]:.0f}/%{customdata[1]:.0f} days"
                    + "<extra>%{fullData.name}</extra>"
                ),
                connectgaps=False,
            )
        )
    figure.update_layout(
        title=f"{metric_label(metric)} contribution over calendar time",
        xaxis_title="Date",
        yaxis_title="Share" if view_mode == "Share" else metric_label(metric),
    )
    if view_mode == "Share":
        figure.update_yaxes(tickformat=".0%", range=[0, 1])
    add_context_bands(
        figure,
        context,
        pd.Timestamp(calendar_query_start),
        pd.Timestamp(calendar_query_end),
        show_spikes=sale_mode == "Keep and flag",
    )
    st.plotly_chart(style_figure(figure, 540), key="overview_contribution_chart")
    if granularity == "Weekly":
        st.caption(
            "Open-square points are partial Monday-start weeks; hover shows included days out of 7. "
            "Fully excluded weeks remain gaps."
        )

    overview_table = (
        overview.groupby("Family", as_index=False)
        .agg(Revenue=("revenue", "sum"), Units=("units", "sum"))
        .sort_values("Revenue", ascending=False)
    )
    overview_table["Revenue share"] = overview_table["Revenue"] / overview_table["Revenue"].sum()
    overview_table["Unit share"] = overview_table["Units"] / overview_table["Units"].sum()
    st.dataframe(
        overview_table,
        hide_index=True,
        width="stretch",
        column_config={
            "Revenue": st.column_config.NumberColumn(format="dollar"),
            "Units": st.column_config.NumberColumn(format="localized"),
            "Revenue share": st.column_config.NumberColumn(format="percent"),
            "Unit share": st.column_config.NumberColumn(format="percent"),
        },
    )

with tab_drops:
    st.subheader("Compare the latest ten validated drops")
    selected_tags = st.multiselect(
        "Families",
        options=latest_ten["family_tag"].tolist(),
        default=latest_ten["family_tag"].tolist(),
        format_func=lambda tag: latest_labels[tag],
        key="drop_family_selection",
    )
    controls = st.columns([1, 1.25, 1, 1.2])
    window_days = controls[0].select_slider("Cohort window", options=[14, 28, 56, 84, 120], value=56, format_func=lambda x: f"{x} days")
    horizon_policy = controls[1].radio("Cohort exposure", ["Available by family", "Common completed age"])
    comparison_grain = controls[2].radio("Comparison grain", ["Daily", "Weekly"])
    comparison_mode = controls[3].radio("View", ["Launch-aligned cohort", "Assigned calendar contribution"])
    selected_drop_rows = latest_ten[latest_ten["family_tag"].isin(selected_tags)].copy()
    comparison_window_days = window_days
    if horizon_policy == "Common completed age" and not selected_drop_rows.empty:
        anchor_column = "anchor_date" if anchor_choice == "Early access" else "launch_date"
        common_available = int(
            (analysis_cutoff - selected_drop_rows[anchor_column].max()).days + 1
        )
        comparison_window_days = max(0, min(window_days, common_available))
        if comparison_mode == "Launch-aligned cohort":
            st.caption(
                f"Common-age mode compares the first {comparison_window_days} complete calendar days for every selected family."
            )
        else:
            st.caption(
                f"The {comparison_window_days}-day common-age setting applies to the Products and Category cohort views. "
                "The assigned chart below uses the Overview calendar range."
            )
    elif comparison_mode == "Assigned calendar contribution":
        st.caption(
            "Cohort window and exposure apply to the Products and Category tabs. "
            "The assigned chart below uses the Overview calendar range."
        )

    if not selected_tags:
        st.info("Select at least one family.")
    elif comparison_mode == "Assigned calendar contribution":
        assigned = assigned_family_trend(
            selected_tags,
            calendar_query_start,
            calendar_query_end,
            comparison_grain,
            metric,
            selections,
            sale_mode,
        )
        assigned = make_calendar_grid(
            assigned,
            ["rest", "core", *selected_tags],
            "family_tag",
            calendar_query_start,
            calendar_query_end,
            comparison_grain,
            context,
            sale_mode,
            ["metric_value"],
        )
        assigned["Family"] = assigned["family_tag"].map(lambda value: family_name(value, drop_lookup))
        palette = family_palette(selected_tags, drop_lookup)
        figure = go.Figure()
        display_tags = ["rest", "core", *reversed(selected_tags)]
        for tag in display_tags:
            family = assigned[assigned["family_tag"].eq(tag)]
            name = family_name(tag, drop_lookup)
            is_partial = family["included_days"].lt(family["expected_days"])
            figure.add_trace(
                go.Scatter(
                    x=family["period"],
                    y=family["metric_value"],
                    mode="lines+markers",
                    name=name,
                    line=dict(
                        color=palette[name],
                        width=3 if tag == "core" else 2.4,
                        dash="dash" if tag == "rest" else "solid",
                    ),
                    marker=dict(
                        size=np.where(is_partial, 7, 0),
                        symbol=np.where(is_partial, "square-open", "circle"),
                    ),
                    customdata=np.column_stack(
                        [family["included_days"], family["expected_days"]]
                    ),
                    hovertemplate=(
                        "%{x|%b %d, %Y}<br>"
                        + f"{metric_label(metric)}: %{{y:,.0f}}"
                        + "<br>Included coverage: %{customdata[0]:.0f}/%{customdata[1]:.0f} days"
                        + "<extra>%{fullData.name}</extra>"
                    ),
                    connectgaps=False,
                )
            )
        figure.update_layout(
            title="Reconciled selected-family contribution",
            xaxis_title="Date",
            yaxis_title=metric_label(metric),
        )
        if not assigned.empty:
            add_context_bands(
                figure,
                context,
                pd.Timestamp(calendar_query_start),
                pd.Timestamp(calendar_query_end),
                show_spikes=sale_mode == "Keep and flag",
            )
        st.plotly_chart(style_figure(figure, 540), key="assigned_contribution_chart")
        st.caption(
            "This view is additive: Core + selected families + Rest of Families reconciles to the filtered total. "
            "Open squares mark partial Monday-start weeks; fully excluded periods remain gaps."
        )
    else:
        aligned = cohort_daily(
            selected_tags,
            analysis_cutoff.date(),
            comparison_window_days,
            anchor_choice,
            selections,
            sale_mode,
        )
        aligned = make_aligned_grid(
            aligned,
            selected_drop_rows,
            analysis_cutoff,
            comparison_window_days,
            anchor_choice,
            context,
            sale_mode,
        )
        cumulative = st.toggle("Cumulative", value=False)
        if aligned.empty:
            st.info("No cohort sales match the current filters.")
        else:
            st.plotly_chart(
                aligned_chart(
                    aligned,
                    selected_drop_rows,
                    metric,
                    comparison_grain,
                    cumulative,
                    drop_lookup,
                ),
                key="drop_cohort_chart",
            )
            st.caption(
                "Diamond markers include configured sale-period or statistically flagged high-volume revenue. "
                "Cohorts are product memberships and may overlap, so do not add family lines together."
            )
            summary = family_summary(
                aligned, selected_drop_rows, metric, analysis_cutoff, anchor_choice
            )
            st.dataframe(
                summary,
                hide_index=True,
                width="stretch",
                column_config={
                    f"Week 1 {metric_label(metric)}": st.column_config.NumberColumn(
                        format="dollar" if metric == "revenue" else "localized"
                    ),
                    f"Week 2 {metric_label(metric)}": st.column_config.NumberColumn(
                        format="dollar" if metric == "revenue" else "localized"
                    ),
                    f"First 28D {metric_label(metric)}": st.column_config.NumberColumn(
                        format="dollar" if metric == "revenue" else "localized"
                    ),
                    f"Window {metric_label(metric)}": st.column_config.NumberColumn(
                        format="dollar" if metric == "revenue" else "localized"
                    ),
                    "W2 vs W1": st.column_config.NumberColumn(format="percent"),
                    "Sale / spike share": st.column_config.NumberColumn(format="percent"),
                },
            )

# Product and category views use the same selected family set and comparison
# semantics, keeping every tab consistent with the drop comparison.
shared_tags = selected_tags
shared_anchor = anchor_choice
shared_window = comparison_window_days
shared_cutoff = analysis_cutoff
product_detail = product_performance(
    shared_tags,
    shared_cutoff.date(),
    shared_window,
    shared_anchor,
    selections,
    sale_mode,
)

with tab_products:
    st.subheader("Products across selected families")
    st.caption(
        f"Using {len(shared_tags)} selected families, a {shared_window}-day window, and {shared_anchor.lower()} as day 0."
    )
    search = st.text_input("Find a product", placeholder="e.g. Accolade 1/4 Zip Pullover")
    visible_products = product_detail.copy()
    if search and not visible_products.empty:
        visible_products = visible_products[
            visible_products["product_name"].str.contains(search, case=False, na=False, regex=False)
            | visible_products["color"].str.contains(search, case=False, na=False, regex=False)
        ]
    value_column = metric
    week_1_column = f"week_1_{metric}"
    week_2_column = f"week_2_{metric}"
    if visible_products.empty:
        st.info("No products match the current search and filters.")
    else:
        product_anchor_column = "anchor_date" if shared_anchor == "Early access" else "launch_date"
        available_by_family = {
            row.family_tag: max(
                0,
                min(
                    shared_window,
                    (shared_cutoff - pd.Timestamp(getattr(row, product_anchor_column))).days + 1,
                ),
            )
            for row in latest_ten[latest_ten["family_tag"].isin(shared_tags)].itertuples(index=False)
        }
        if sale_mode == "Exclude configured sale periods":
            product_excluded_dates = set(
                context.loc[context["is_configured_sale"], "order_date"].dt.normalize()
            )
        elif sale_mode == "Exclude sale periods + volume spikes":
            product_excluded_dates = set(
                context.loc[
                    context["is_configured_sale"] | context["is_volume_spike"], "order_date"
                ].dt.normalize()
            )
        else:
            product_excluded_dates = set()
        first_14_included_by_family: dict[str, int] = {}
        for row in latest_ten[latest_ten["family_tag"].isin(shared_tags)].itertuples(index=False):
            anchor = pd.Timestamp(getattr(row, product_anchor_column))
            first_14_included_by_family[row.family_tag] = sum(
                (anchor + pd.Timedelta(days=day)).normalize() not in product_excluded_dates
                for day in range(min(14, available_by_family[row.family_tag]))
            )
        visible_products["Days available"] = visible_products["family_tag"].map(available_by_family).fillna(0).astype(int)
        visible_products["First 14 included"] = (
            visible_products["family_tag"].map(first_14_included_by_family).fillna(0).astype(int)
        )
        recurrence = (
            visible_products.groupby("product_name", as_index=False)
            .agg(
                Drops=("family_tag", "nunique"),
                Colors=("color", lambda values: ", ".join(sorted(set(map(str, values))))),
                Families=("family_tag", lambda values: ", ".join(
                    family_name(tag, drop_lookup) for tag in shared_tags if tag in set(values)
                )),
                Window_value=(value_column, lambda values: values.sum(min_count=1)),
                Week_1=(week_1_column, lambda values: values.sum(min_count=1)),
                Week_2=(week_2_column, lambda values: values.sum(min_count=1)),
                Minimum_days=("Days available", "min"),
                Minimum_first_14_included=("First 14 included", "min"),
            )
            .sort_values(["Drops", "Window_value"], ascending=[False, False])
        )
        recurrence = recurrence.rename(
            columns={
                "product_name": "Product",
                "Window_value": f"Window {metric_label(metric)}",
                "Week_1": f"Week 1 {metric_label(metric)}",
                "Week_2": f"Week 2 {metric_label(metric)}",
                "Minimum_days": "Minimum days available",
                "Minimum_first_14_included": "Minimum first-14 days included",
            }
        )
        recurrence["Week 2 complete"] = (
            recurrence["Minimum days available"].ge(14)
            & recurrence["Minimum first-14 days included"].eq(14)
        )
        st.dataframe(
            recurrence,
            hide_index=True,
            width="stretch",
            height=390,
            column_config={
                f"Window {metric_label(metric)}": st.column_config.NumberColumn(
                    format="dollar" if metric == "revenue" else "localized"
                ),
                f"Week 1 {metric_label(metric)}": st.column_config.NumberColumn(
                    format="dollar" if metric == "revenue" else "localized"
                ),
                f"Week 2 {metric_label(metric)}": st.column_config.NumberColumn(
                    format="dollar" if metric == "revenue" else "localized"
                ),
            },
        )

        product_options = recurrence["Product"].tolist()
        selected_product = st.selectbox("Product trend", product_options)
        product_color_options = sorted(
            visible_products.loc[
                visible_products["product_name"].eq(selected_product), "color"
            ].dropna().astype(str).unique().tolist()
        )
        selected_product_colors = st.multiselect(
            "Product colors",
            product_color_options,
            default=product_color_options,
            help="Use one color for an isolated product-color trend, or keep several to compare drops.",
        )
        product_daily = cohort_daily(
            shared_tags,
            shared_cutoff.date(),
            shared_window,
            shared_anchor,
            selections,
            sale_mode,
            product_name=selected_product,
            colors=selected_product_colors,
            group_color=True,
        )
        if not product_daily.empty:
            product_daily = make_product_series_grid(
                product_daily,
                latest_ten[latest_ten["family_tag"].isin(shared_tags)],
                shared_cutoff,
                shared_window,
                shared_anchor,
                context,
                sale_mode,
            )
            product_daily["Series"] = product_daily.apply(
                lambda row: f"{family_name(row['family_tag'], drop_lookup)} · {row['color']}", axis=1
            )
            product_x = "launch_day"
            product_x_title = "Day since release"
            if comparison_grain == "Weekly":
                product_daily["release_week"] = product_daily["launch_day"] // 7 + 1
                product_daily = (
                    product_daily.groupby(["Series", "release_week"], as_index=False)
                    .agg(
                        metric_value=(metric, lambda values: values.sum(min_count=1)),
                        calendar_days=("launch_day", "nunique"),
                        included_days=("is_excluded", lambda values: int((~values).sum())),
                    )
                )
                product_daily["expected_days"] = 7
                product_x = "release_week"
                product_x_title = "Week since release"
                product_y = "metric_value"
            else:
                product_daily["calendar_days"] = 1
                product_daily["included_days"] = (~product_daily["is_excluded"]).astype(int)
                product_daily["expected_days"] = 1
                product_y = metric
            product_figure = go.Figure()
            for series, group in product_daily.groupby("Series", sort=False):
                product_figure.add_trace(
                    go.Scatter(
                        x=group[product_x],
                        y=group[product_y],
                        mode="lines+markers",
                        name=series,
                        connectgaps=False,
                        marker=dict(
                            symbol=np.where(
                                group["included_days"].lt(group["expected_days"]),
                                "square-open",
                                "circle",
                            )
                        ),
                        customdata=np.column_stack(
                            [group["included_days"], group["expected_days"]]
                        ),
                        hovertemplate=(
                            f"{metric_label(metric)}: %{{y:,.0f}}"
                            "<br>Included coverage: %{customdata[0]:.0f}/%{customdata[1]:.0f} days"
                            "<extra>%{fullData.name}</extra>"
                        ),
                    )
                )
            product_figure.update_layout(
                title=f"{selected_product}: {metric_label(metric)} by release age",
                xaxis_title=product_x_title,
                yaxis_title=metric_label(metric),
            )
            st.plotly_chart(
                style_figure(product_figure, 480), key="product_trend_chart"
            )

        detail_view = visible_products.copy()
        detail_view["Family"] = detail_view["family_tag"].map(lambda value: family_name(value, drop_lookup))
        detail_columns = [
            "Family",
            "product_name",
            "color",
            "business_line",
            "category",
            "subcategory",
            "item_class",
            "revenue",
            "units",
            "week_1_revenue",
            "week_2_revenue",
        ]
        with st.expander("Product × family detail"):
            st.dataframe(
                detail_view[detail_columns].rename(
                    columns={
                        "product_name": "Product",
                        "color": "Color",
                        "business_line": "Business line",
                        "category": "Category",
                        "subcategory": "Subcategory",
                        "item_class": "Item class",
                        "revenue": "Revenue",
                        "units": "Units",
                        "week_1_revenue": "Week 1 revenue",
                        "week_2_revenue": "Week 2 revenue",
                    }
                ),
                hide_index=True,
                width="stretch",
                column_config={
                    "Revenue": st.column_config.NumberColumn(format="dollar"),
                    "Units": st.column_config.NumberColumn(format="localized"),
                    "Week 1 revenue": st.column_config.NumberColumn(format="dollar"),
                    "Week 2 revenue": st.column_config.NumberColumn(format="dollar"),
                },
            )

with tab_category:
    st.subheader("Category and subcategory comparison")
    level_label = st.radio(
        "Breakdown",
        ["Category", "Subcategory", "Item class", "Business line"],
        horizontal=True,
    )
    level_column = {
        "Category": "category",
        "Subcategory": "subcategory",
        "Item class": "item_class",
        "Business line": "business_line",
    }[level_label]
    category_detail = category_performance(
        shared_tags,
        shared_cutoff.date(),
        shared_window,
        shared_anchor,
        selections,
        sale_mode,
        level_column,
    )
    if category_detail.empty:
        st.info("No category data matches the current filters.")
    else:
        category_summary_all = category_detail.rename(
            columns={"dimension_value": level_column, metric: "metric_value"}
        )[[level_column, "family_tag", "metric_value"]]
        totals = category_summary_all.groupby(level_column)["metric_value"].sum().nlargest(18)
        category_summary = category_summary_all[
            category_summary_all[level_column].isin(totals.index)
        ]
        matrix = category_summary.pivot_table(
            index=level_column,
            columns="family_tag",
            values="metric_value",
            aggfunc="sum",
            fill_value=0,
        ).reindex(index=totals.index, columns=shared_tags, fill_value=0)
        heatmap_mode = st.radio("Heatmap value", ["Absolute", "Share of family"], horizontal=True)
        plot_matrix = matrix.copy()
        if heatmap_mode == "Share of family":
            family_totals = category_summary_all.groupby("family_tag")["metric_value"].sum()
            plot_matrix = plot_matrix.div(family_totals.replace(0, np.nan), axis=1).fillna(0)
        category_figure = go.Figure(
            go.Heatmap(
                z=plot_matrix.values,
                x=[family_name(tag, drop_lookup) for tag in plot_matrix.columns],
                y=plot_matrix.index,
                colorscale="Blues",
                colorbar_title="Share" if heatmap_mode == "Share of family" else metric_label(metric),
                hovertemplate=(
                    f"{level_label}: %{{y}}<br>Family: %{{x}}<br>"
                    + ("Share: %{z:.1%}" if heatmap_mode == "Share of family" else f"{metric_label(metric)}: %{{z:,.0f}}")
                    + "<extra></extra>"
                ),
            )
        )
        category_figure.update_layout(
            title=f"{level_label} performance by family",
            xaxis_title="Family",
            yaxis_title=level_label,
        )
        st.plotly_chart(
            style_figure(category_figure, max(500, 30 * len(plot_matrix) + 160)),
            key="category_heatmap_chart",
        )

        selected_category = st.selectbox(
            f"{level_label} trend",
            options=totals.index.tolist(),
            format_func=str,
        )
        category_daily = cohort_daily(
            shared_tags,
            shared_cutoff.date(),
            shared_window,
            shared_anchor,
            selections,
            sale_mode,
            extra_dimension=(level_column, str(selected_category)),
        )
        category_daily = make_aligned_grid(
            category_daily,
            latest_ten[latest_ten["family_tag"].isin(shared_tags)],
            shared_cutoff,
            shared_window,
            shared_anchor,
            context,
            sale_mode,
        )
        if not category_daily.empty:
            st.plotly_chart(
                aligned_chart(
                    category_daily,
                    latest_ten[latest_ten["family_tag"].isin(shared_tags)],
                    metric,
                    comparison_grain if "comparison_grain" in locals() else "Daily",
                    False,
                    drop_lookup,
                ),
                key="category_trend_chart",
            )

with tab_context:
    st.subheader("Sales context and data quality")
    st.markdown(
        '<div class="definition">Configured sale periods are business rules copied from the legacy analysis. Volume-spike dates are statistical alerts only; verify them before calling them promotions.</div>',
        unsafe_allow_html=True,
    )
    context_figure = go.Figure()
    context_figure.add_trace(
        go.Scatter(
            x=context["order_date"],
            y=context["daily_revenue"],
            mode="lines",
            name="Daily revenue",
            line=dict(color="#0F172A", width=1.8),
        )
    )
    context_figure.add_trace(
        go.Scatter(
            x=context["order_date"],
            y=context["trailing_28d_median_revenue"],
            mode="lines",
            name="Prior 28-day median",
            line=dict(color="#64748B", width=1.5, dash="dash"),
        )
    )
    context_figure.update_layout(
        title="Daily revenue with sale and anomaly context",
        xaxis_title="Date",
        yaxis_title="Revenue",
    )
    add_context_bands(context_figure, context, source_min, source_max, show_spikes=True)
    st.plotly_chart(style_figure(context_figure, 520), key="sales_context_chart")

    quality_columns = st.columns(4)
    quality_columns[0].metric("Source rows", f"{quality['raw']['rows']:,}")
    quality_columns[1].metric("Prepared fact rows", f"{quality['processed']['fact_rows']:,}")
    quality_columns[2].metric("Product-color groups", f"{quality['processed']['products']:,}")
    quality_columns[3].metric(
        "Revenue reconciliation",
        f"${quality['processed']['revenue_delta_vs_raw']:,.4f}",
    )
    duplicate_review = quality["raw"].get("apparent_duplicate_review", {})
    if duplicate_review.get("groups", 0):
        st.warning(
            f"Source QA: {duplicate_review['groups']:,} date/SKU/measure groups repeat across distinct "
            f"source keys (up to {format_metric(duplicate_review['possible_extra_revenue'], 'revenue', compact=True)} "
            "of possible join fan-out). They are preserved and flagged—not deleted—because some may be valid partitions."
        )
    taxonomy_review = quality["processed"].get("taxonomy_conflicts", {})
    if taxonomy_review.get("mixed_business_line_products", 0):
        st.info(
            f"Taxonomy QA: {taxonomy_review['mixed_business_line_products']:,} product-color groups span "
            f"multiple business lines across {format_metric(taxonomy_review['mixed_business_line_revenue'], 'revenue', compact=True)} "
            "of history. Category views preserve each SKU's taxonomy allocation; Product summaries label these Mixed / multiple."
        )

    st.markdown("#### Family rules")
    st.markdown(
        f"""
        - Accepted only complete tags matching `{quality['methodology']['canonical_regex']}`.
        - `{quality['methodology']['family_assignment']}`
        - Product cohorts use normalized product name + color. Cohort lines can overlap; assigned contribution cannot.
        - One coherent most-complete/latest metadata record per SKU is used for product identity and taxonomy across history; source changes are reported in the build QA.
        - Source `price` and supplied rolling seven-day fields are intentionally not used. Realized average selling price is Revenue ÷ Units.
        """
    )
    excluded = query_frame(
        f"""
        SELECT exclusion_reason, family_tag, token_rows, sku_count,
               token_associated_revenue, first_observed_date, last_observed_date
        FROM {EXCLUDED}
        ORDER BY token_associated_revenue DESC NULLS LAST
        """
    )
    reason_summary = (
        excluded.groupby("exclusion_reason", as_index=False)
        .agg(Tags=("family_tag", "nunique"), Token_rows=("token_rows", "sum"), SKUs=("sku_count", "sum"))
        .sort_values("Token_rows", ascending=False)
        .rename(columns={"exclusion_reason": "Reason", "Token_rows": "Token occurrences"})
    )
    st.dataframe(reason_summary, hide_index=True, width="stretch")
    with st.expander("Inspect ignored family tags"):
        st.caption("Token-associated revenue is non-additive because a sales row can contain several tags.")
        st.dataframe(
            excluded,
            hide_index=True,
            width="stretch",
            column_config={
                "token_associated_revenue": st.column_config.NumberColumn(format="dollar"),
                "token_rows": st.column_config.NumberColumn(format="localized"),
                "sku_count": st.column_config.NumberColumn(format="localized"),
            },
        )

st.caption(
    f"Prepared {pd.Timestamp(quality['built_at_utc']):%b %-d, %Y at %-I:%M %p UTC} · "
    f"{len(latest_ten)} validated conventional drops as of {reference_date:%b %-d, %Y}"
)
