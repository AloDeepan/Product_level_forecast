from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import duckdb
import pandas as pd

from build_dashboard_data import (
    CANONICAL_FAMILY_RE,
    build_data,
    is_canonical_family,
    load_sale_periods,
)


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
FACT = DATA / "product_daily.parquet"
PRODUCTS = DATA / "product_dimension.parquet"
MEMBERSHIP = DATA / "product_drop_membership.parquet"
DROPS = DATA / "drop_calendar.parquet"
CONTEXT = DATA / "daily_context.parquet"
QUALITY = DATA / "data_quality.json"


def parquet(path: Path) -> str:
    return f"read_parquet('{str(path).replace(chr(39), chr(39) * 2)}')"


def test_exact_family_parser() -> None:
    accepted = ["FA26D3-family", "su26d1-family", " WT25D8-family "]
    rejected = [
        "FA26D3-1-family",
        "FA26MD3-family",
        "FA26Drops-family",
        "FA26Atelier-family",
        "FA26D3",
        "NO_FAM",
    ]
    assert all(is_canonical_family(value) for value in accepted)
    assert not any(is_canonical_family(value) for value in rejected)
    assert CANONICAL_FAMILY_RE.fullmatch("FA26D3-family")


def test_required_artifacts_and_reconciliation() -> None:
    required = [FACT, PRODUCTS, MEMBERSHIP, DROPS, CONTEXT, QUALITY]
    assert all(path.exists() for path in required)
    quality = json.loads(QUALITY.read_text())
    with duckdb.connect() as connection:
        revenue, units, source_rows = connection.execute(
            f"SELECT sum(revenue), sum(units), sum(source_rows) FROM {parquet(FACT)}"
        ).fetchone()
    assert abs(revenue - quality["raw"]["revenue"]) < 0.01
    assert units == quality["raw"]["units"]
    assert source_rows == quality["raw"]["rows"]
    assert quality["raw"]["unique_key_duplicates"] == 0


def test_attribution_is_exclusive_and_release_eligible() -> None:
    with duckdb.connect() as connection:
        violations = connection.execute(
            f"""
            SELECT count(*)
            FROM {parquet(FACT)} f
            LEFT JOIN {parquet(DROPS)} r ON r.family_tag = f.assigned_family
            LEFT JOIN {parquet(MEMBERSHIP)} m
              ON m.product_key = f.product_key AND m.family_tag = f.assigned_family
            WHERE (f.planning_status = 'Core' AND f.contribution_family <> 'core')
               OR (f.planning_status <> 'Core' AND f.assigned_family IS NULL
                   AND f.contribution_family <> 'rest')
               OR (f.planning_status <> 'Core' AND f.assigned_family IS NOT NULL
                   AND f.contribution_family <> f.assigned_family)
               OR (f.assigned_family IS NOT NULL AND (
                    m.family_tag IS NULL
                    OR f.order_date < greatest(
                        r.anchor_date, m.first_tag_observed_date - INTERVAL 1 DAY
                    )
               ))
            """
        ).fetchone()[0]
        conflicting_non_core = connection.execute(
            f"""
            SELECT count(*) FROM (
                SELECT product_key, order_date,
                       count(DISTINCT assigned_family) FILTER (WHERE assigned_family IS NOT NULL) families
                FROM {parquet(FACT)}
                WHERE planning_status <> 'Core'
                GROUP BY product_key, order_date
                HAVING families > 1
            )
            """
        ).fetchone()[0]
    assert violations == 0
    assert conflicting_non_core == 0


def test_product_keys_are_normalized_name_color_unique() -> None:
    with duckdb.connect() as connection:
        duplicated_identity = connection.execute(
            f"""
            SELECT count(*) FROM (
                SELECT
                    regexp_replace(lower(product_name), '[^a-z0-9]+', ' ', 'g') AS name_norm,
                    regexp_replace(lower(color), '[^a-z0-9]+', ' ', 'g') AS color_norm,
                    count(*) records
                FROM {parquet(PRODUCTS)}
                GROUP BY name_norm, color_norm
                HAVING records > 1
            )
            """
        ).fetchone()[0]
    assert duplicated_identity == 0


def test_taxonomy_is_preserved_without_dimension_fanout() -> None:
    with duckdb.connect() as connection:
        fact_totals = connection.execute(
            f"SELECT sum(revenue), sum(units), sum(source_rows) FROM {parquet(FACT)}"
        ).fetchone()
        joined_totals = connection.execute(
            f"""
            SELECT sum(f.revenue), sum(f.units), sum(f.source_rows)
            FROM {parquet(FACT)} f
            JOIN {parquet(PRODUCTS)} d USING (product_key)
            """
        ).fetchone()
        mixed_label_violations = connection.execute(
            f"""
            WITH mixed AS (
                SELECT product_key
                FROM {parquet(FACT)}
                GROUP BY product_key
                HAVING count(DISTINCT business_line) > 1
            )
            SELECT count(*)
            FROM mixed m
            JOIN {parquet(PRODUCTS)} d USING (product_key)
            WHERE d.business_line <> 'Mixed / multiple'
            """
        ).fetchone()[0]
        null_taxonomy_rows = connection.execute(
            f"""
            SELECT count(*) FROM {parquet(FACT)}
            WHERE business_line IS NULL OR category IS NULL
               OR subcategory IS NULL OR item_class IS NULL
            """
        ).fetchone()[0]
    assert abs(fact_totals[0] - joined_totals[0]) < 0.01
    assert fact_totals[1:] == joined_totals[1:]
    assert mixed_label_violations == 0
    assert null_taxonomy_rows == 0


def test_current_september_snapshot_and_partial_day() -> None:
    quality = json.loads(QUALITY.read_text())
    if quality["raw"]["max_order_date"] != "2026-09-15":
        return
    drops = pd.read_parquet(DROPS)
    latest = (
        drops[pd.to_datetime(drops["anchor_date"]) <= pd.Timestamp("2026-09-15")]
        .sort_values(["anchor_date", "launch_date", "family_tag"], ascending=False)
        .head(10)["drop_label"]
        .tolist()
    )
    assert latest == [
        "FA26D3",
        "FA26D2",
        "FA26D1",
        "SU26D7",
        "SU26D6",
        "SU26D5",
        "SU26D4",
        "SU26D3",
        "SU26D2",
        "SU26D1",
    ]
    context = pd.read_parquet(CONTEXT)
    partial = context.loc[context["is_incomplete_date"], "order_date"].astype(str).tolist()
    assert partial == ["2026-09-15"]
    assert quality["daily_context"]["latest_complete_date"] == "2026-09-14"


def test_requested_accolade_recurrence_example() -> None:
    with duckdb.connect() as connection:
        families = connection.execute(
            f"""
            WITH latest AS (
                SELECT family_tag FROM {parquet(DROPS)}
                WHERE anchor_date <= DATE '2026-09-15'
                ORDER BY anchor_date DESC, launch_date DESC, family_tag DESC
                LIMIT 10
            )
            SELECT list_sort(list(DISTINCT m.family_tag))
            FROM {parquet(PRODUCTS)} d
            JOIN {parquet(MEMBERSHIP)} m USING (product_key)
            JOIN latest l USING (family_tag)
            WHERE d.product_name = 'Accolade 1/4 Zip Pullover'
            """
        ).fetchone()[0]
    assert families == ["fa26d2-family", "fa26d3-family", "su26d5-family"]


def test_refresh_fails_closed_on_bad_measures_and_missing_sale_config() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        missing_config = root / "missing_sale_periods.csv"
        try:
            load_sale_periods(missing_config)
        except FileNotFoundError:
            pass
        else:
            raise AssertionError("A supplied-but-missing sale config must fail closed")

        sales = root / "sales.csv"
        pd.DataFrame(
            [
                {
                    "order_date": "2026-01-01",
                    "product_title": "Test Product - Black",
                    "sku": "TEST-1",
                    "product_id": "1",
                    "price": "100",
                    "color_group": "Black",
                    "color": "Black",
                    "item_class": "Tops",
                    "subcategory": "Shirts",
                    "category": "Tops",
                    "business_line": "Women",
                    "size": "S",
                    "families": "SP26D1-family",
                    "planning_status": "Seasonal",
                    "revenue": "malformed",
                    "ordered_quantities": "1",
                    "unique_key": "test-key",
                }
            ]
        ).to_csv(sales, index=False)
        releases = root / "releases.xlsx"
        pd.DataFrame(
            [
                {
                    "Tag": "SP26D1-family",
                    "Launch Date": "2026-01-01",
                    "Early Access": "2025-12-31",
                }
            ]
        ).to_excel(releases, index=False)
        output = root / "output"
        try:
            build_data(sales, releases, output, None)
        except ValueError as error:
            assert "invalid_revenue_rows=1" in str(error)
        else:
            raise AssertionError("Malformed revenue must stop the refresh")
        assert not any(output.iterdir())


class DataContractTests(unittest.TestCase):
    def test_parser(self) -> None:
        test_exact_family_parser()

    def test_artifacts_and_reconciliation(self) -> None:
        test_required_artifacts_and_reconciliation()

    def test_exclusive_attribution(self) -> None:
        test_attribution_is_exclusive_and_release_eligible()

    def test_product_identity(self) -> None:
        test_product_keys_are_normalized_name_color_unique()

    def test_taxonomy_contract(self) -> None:
        test_taxonomy_is_preserved_without_dimension_fanout()

    def test_current_snapshot(self) -> None:
        test_current_september_snapshot_and_partial_day()

    def test_accolade_example(self) -> None:
        test_requested_accolade_recurrence_example()

    def test_refresh_input_guards(self) -> None:
        test_refresh_fails_closed_on_bad_measures_and_missing_sale_config()


if __name__ == "__main__":
    unittest.main()
