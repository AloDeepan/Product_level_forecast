# Alo family performance dashboard

This project rebuilds the legacy family analysis as a reproducible data pipeline and Streamlit dashboard. It uses only the two supplied source files:

- `inputs.csv` — daily SKU revenue and units
- `Product Release Dates.xlsx` — family release calendar and color story

The missing buy, price, fiscal-calendar, and SKU-map files from the old notebook are not required. Buy/depletion metrics are intentionally out of scope.

## Run it

```bash
python3 -m pip install -r requirements.txt
python3 build_dashboard_data.py
streamlit run app.py
```

The current prepared data is already in `data/processed`, so the final command is enough until either source file changes. Re-run the builder whenever you replace the sales extract or release workbook.
Refreshes stage new artifacts beside the live generation and publish the QA manifest last. A supplied-but-missing sale-period file, malformed date, or malformed/missing revenue or units stops the build instead of silently changing totals.

## Dashboard views

- **Overview** — Core + latest three validated drops + Rest of Families, with an additive calendar trend and contribution table.
- **Drop comparison** — choose any of the latest ten drops and switch between mutually exclusive calendar contribution and release-aligned product cohorts. Daily/weekly, cumulative, early-access/public-launch, and 14–120 day controls are included.
- **Products** — find styles across drops, see colors and week-one/week-two results, then compare their release-aligned trends. For example, `Accolade 1/4 Zip Pullover` appears in three of the current latest ten: SU26D5, FA26D2, and FA26D3.
- **Category** — category, subcategory, item-class, or business-line heatmaps and release-aligned trends.
- **Data context** — sale/anomaly overlays, source completeness, exact ignored-tag audit, and reconciliation QA.

Global filters cover measure, time grain, promotional treatment, business line, category, subcategory, and item class.
Taxonomy filters and category heatmaps allocate revenue using the coherent SKU-level taxonomy retained in the fact. If one normalized product-color spans multiple taxonomies, the Product view labels it `Mixed / multiple` instead of arbitrarily choosing one size/SKU's label.

## Family definitions

Only complete, case-normalized tags matching the following pattern are valid:

```text
^(SP|SU|FA|HO|WT)\d{2}D\d+-family$
```

Validation happens before removing `-family`. This excludes season rollups, numeric extensions/spotlights/capsules, men-specific tags, atelier/bridge/sneaker families, and other custom names. A canonical-looking sales tag must also exist in the validated release workbook; this prevents preloaded FA26D4/D5 tags from entering the September family set.

The current latest ten as of September 15, 2026 are FA26D3, FA26D2, FA26D1, and SU26D7 through SU26D1. The latest-three view is FA26D3, FA26D2, and FA26D1.

## Two intentionally different revenue views

**Assigned contribution is additive.** Core is determined from each source row's `planning_status` and takes precedence. Every remaining product-color/date is assigned to its most recently anchored, eligible conventional family. Membership can backfill one day before the first observed exact tag—but never before Early Access/Launch—to capture the consistent one-day early-access/public-launch tagging lag, then persists forward. This bounded rule avoids unrestricted retroactive relabeling. Anything outside the displayed latest set becomes Rest. These buckets reconcile to source revenue and units.

**Product cohorts are exploratory and non-additive.** A product-color can belong to more than one family. Cohort views include its post-release performance in each applicable family so merchandising can compare the same style across drops. Do not add cohort lines together.

Early Access is the default day 0 because that is when selling begins; Public Launch is available in the dashboard. Launch ordering also uses the eligible Early Access date, with Public Launch as fallback.

## Sales-period treatment

`config/sale_periods.csv` contains the two explicit windows found in the legacy notebook. Edit this file to add business-confirmed periods, then rebuild.

The builder separately flags a day when revenue is at least 3× its prior 28-day median and above the extract's 90th percentile. This catches the May 2026 surge but is labeled a statistical volume spike—not assumed to be a promotion. The dashboard can keep and flag dates, exclude configured periods, or exclude both configured periods and volume spikes.

## Prepared data contract

| File | Purpose |
|---|---|
| `product_daily.parquet` | Additive daily product-color × SKU-taxonomy fact with Core/family/Rest attribution |
| `product_dimension.parquet` | Normalized product-color lookup with honest mixed-taxonomy labels |
| `product_drop_membership.parquet` | Non-additive product-color × conventional-family cohort bridge |
| `drop_calendar.parquet` | Valid conventional releases and color metadata |
| `daily_context.parquet` | Daily totals, partial-day flag, sale periods, and anomaly index |
| `excluded_family_tags.parquet` | Audit of every ignored family token |
| `data_quality.json` | Source/build counts, reconciliation, and modeling assumptions |

The source `price` field is not used because it contains mixed scaling regimes. Average realized selling price, if needed, should be calculated as Revenue ÷ Units. The supplied rolling seven-day fields are also ignored and should be recomputed only after filtering/aggregation.

The source contains distinct-key records that look like possible join fan-out: the build reports them but does not delete them. Revenue reconciliation proves source preservation, not that those upstream records are genuine.

September 15, 2026 is retained but flagged as partial; default comparisons stop at September 14, the latest complete date.

## Validation

```bash
PYTHONPYCACHEPREFIX=/tmp/family_dashboard_pycache python3 -m unittest discover -s tests -v
```

The tests verify exact family parsing, release eligibility, mutually exclusive attribution, source reconciliation, partial-date behavior, and the current Accolade recurrence example.
