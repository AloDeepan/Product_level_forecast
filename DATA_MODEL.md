# Data Model & Data Dictionary

**Project:** `Product_level_forecast` — product-level family/drop performance analytics for an
apparel retailer.

**Purpose of this document.** A complete, self-contained reference to every input file, every
processed table, every generated report, and every transformation rule in between. It is written
to be pasted into a chat session as context so that solutions can be designed without first
reading the source code.

**Last verified:** 2026-09-18, against a build of `2026-09-17T17:16:38Z` covering source dates
`2025-01-01` → `2026-09-15`.

> **Conventions used below.** "Grain" = what one row uniquely represents. "Additive" = you may
> `SUM` the measures across any combination of dimensions without double counting.
> "Non-additive" = summing across the listed dimension double counts.

---

## 1. Quick orientation

| | |
|---|---|
| Runtime | Python 3.14.7 in `.venv` (single venv; Jupyter kernel `Python 3.14 (Product_level_forecast)`) |
| Dependencies | `to_share/requirements.txt` — duckdb, pandas, numpy, pyarrow, plotly, streamlit, openpyxl |
| Build command | `cd to_share && ../.venv/bin/python build_dashboard_data.py` (~10 s) |
| Dashboard | `cd to_share && ../.venv/bin/streamlit run app.py` |
| Tests | `cd to_share && PYTHONPATH=. ../.venv/bin/python -m unittest tests.test_data_contract` (8 tests) |

The raw extract is **never loaded into pandas**. DuckDB scans the 919 MB CSV and writes small
Parquet facts/dimensions that Streamlit queries lazily. Preserve this pattern in new work.

---

## 2. Lineage

```
INPUTS                          BUILD                      PROCESSED (Parquet)
──────────────────────────────  ─────────────────────────  ──────────────────────────────
to_share/inputs.csv         ─┐
  3,485,426 rows, 919 MB     │
                             ├─► build_dashboard_data.py ─► product_daily.parquet       (fact)
Product Release Dates.xlsx  ─┤   • normalise text             product_dimension.parquet
  441 rows, 10 cols          │   • derive product_key         product_drop_membership.parquet
                             │   • validate release cal.      drop_calendar.parquet
config/sale_periods.csv     ─┘   • assign families            daily_context.parquet
  2 rows                         • flag sale / spike days     excluded_family_tags.parquet
                                 • reconcile revenue          data_quality.json (audit)
                                          │
                                          ▼
                                    to_share/app.py  (Streamlit)
                                          │
        01_EDA_*.ipynb / 02_EDA_*.ipynb ──┴──► 0*_*.csv  (ad-hoc analyst reports)
```

**Reconciliation guarantee.** `product_daily` sums to the raw extract:
`$2,831,081,580.32` revenue and `31,761,946` units, delta `-$0.000009` (float noise only).
Any change that breaks this is a bug — `tests/test_data_contract.py` asserts it.

---

## 3. Input files

### 3.1 `to_share/inputs.csv` — raw sales extract

Daily SKU-level sales, exported from Redshift (`gold.gold_revenue_by_planning_category`; see
`explore_vscode.ipynb` for the pull). **Read-only. Never edit in place.**

| | |
|---|---|
| Grain | one row per `unique_key` — effectively date × SKU × metadata-snapshot |
| Rows | 3,485,426 |
| Date range | 2025-01-01 → 2026-09-15 (623 distinct days) |
| Size | 919,178,533 bytes |

| Column | Type | Description | Example |
|---|---|---|---|
| `order_date` | DATE | Sale date. Never null, never unparseable (verified: 0 bad rows). | `2025-01-01` |
| `product_title` | VARCHAR | Full merchandising title, **usually including a trailing `" - <colour>"` suffix**. Source of the derived `product_name`. | `Grounded No-Slip Towel - Jungle` |
| `sku` | VARCHAR | SKU code. 1 row in the whole extract has a null SKU. | `A0029U016641` |
| `product_id` | BIGINT | Upstream product id. **Unstable — do not use as identity** (see §5.1). | `4594792136822` |
| `price` | DOUBLE | List price snapshot. Not used by the build. | `68.0` |
| `color_group` | VARCHAR | Coarse colour rollup (16 values, see §6.2). | `Green` |
| `color` | VARCHAR | Colour name. **Nullable** — when null the build recovers it from the title. | `Jungle` |
| `item_class` | VARCHAR | Narrowest taxonomy level (77 values incl. null). | `Towels` |
| `subcategory` | VARCHAR | Mid taxonomy level (71 values incl. null). Not a clean parent of `item_class` — see §8.4. | `Towels` |
| `category` | VARCHAR | Broad taxonomy level (29 values incl. null). | `Equipment` |
| `business_line` | VARCHAR | Women / Men / Accessories / Beauty / Wellness / Unknown / Books / Internal. | `Accessories` |
| `size` | VARCHAR | Size label (140 values). Not carried into the fact. | `One Size` |
| `families` | VARCHAR | **Comma-separated** drop-family tags, or the literal `NO_FAM`. One row often carries both a specific drop and a season rollup. | `wt25d1-family,wt25drops-family` |
| `planning_status` | VARCHAR | Merchandising lifecycle status; normalised by the build (§5.3). | `Carryover` |
| `revenue` | DOUBLE | Revenue for the row. **The only revenue measure used.** | `340.0` |
| `ordered_quantities` | BIGINT | Units for the row. | `5` |
| `revenue_last_7d` | DOUBLE | Supplied rolling metric. **Ignored by the build** — recompute if needed. | `340.0` |
| `qty_ordered_last_7d` | BIGINT | Supplied rolling metric. Ignored. | `5` |
| `avg_daily_qty_ordered_last_7d` | DOUBLE | Supplied rolling metric. Ignored. | `0.7142` |
| `avg_daily_sales_last_7d` | DOUBLE | Supplied rolling metric. Ignored. | `48.5714` |
| `dbt_updated_at` | TIMESTAMPTZ | dbt build timestamp of the source model. | `2026-08-12 01:21:23.215-07:00` |
| `unique_key` | VARCHAR | Source row hash. 0 exact duplicates. | `76b5e136b8cdcafd4fde974f9072105c` |

### 3.2 `to_share/Product Release Dates.xlsx` — drop release calendar

Hand-maintained workbook. 441 rows, 10 columns. Only 103 rows survive validation (§5.4).

| Column | Maps to | Notes |
|---|---|---|
| `Tag` | `family_tag` | Lowercased. Must match the canonical regex to be used. |
| `Early Access` | `early_access_date` | Nullable — 7 canonical rows have none. |
| `Launch Date` | `launch_date` | Public launch. |
| `Hex Code` / `Hex Codes` | `primary_hex`, `hex_codes` | Coalesced; first `#rrggbb` extracted. Only 21/103 populated. |
| `oliver` | `color_story` | Colour story name — column name is a person's name, not a typo to fix. |
| `Spotlight / Capsule` | — | Drives the "spotlight/capsule" exclusion reason. |
| `Spotlight #` | — | Not carried through. |
| `Revenue Investment $ (Total Color Drop)` | — | Not carried through. |
| `Notes` | `notes` | **Always null** in the output (typed INTEGER). |

### 3.3 `to_share/config/sale_periods.csv` — promotional windows

Two rows; drives `is_configured_sale` in `daily_context` (68 days flagged).

| Column | Example |
|---|---|
| `period_name` | `Holiday promotional window` |
| `start_date` | `2025-10-26` |
| `end_date` | `2025-12-25` |
| `source` | `Legacy notebook exclusion window` |

---

## 4. Processed tables (`to_share/data/processed/`)

### 4.1 Relationship map

```
product_dimension (7,117)          drop_calendar (103)
   product_key  ─── PK                family_tag ─── PK
        │                                  │
        │                                  │
        ├── product_daily (1,379,103)      │
        │      product_key  (FK)           │
        │      order_date   (FK) ──────────┼──► daily_context (623)
        │      assigned_family (FK) ───────┤        order_date ─── PK
        │                                  │
        └── product_drop_membership (4,114)│
               product_key (FK)            │
               family_tag  (FK) ───────────┘

excluded_family_tags (460)  — audit only, no joins
```

### 4.2 `product_daily.parquet` — the fact table

| | |
|---|---|
| Grain | `order_date` × `product_key` × `planning_status` × `assigned_family` × taxonomy |
| Rows | 1,379,103 |
| **Additive** | Yes — `SUM(revenue)`, `SUM(units)` across any dimensions |
| Compression | ZSTD, row group 100,000 |

| Column | Type | Description | Example |
|---|---|---|---|
| `order_date` | DATE | Sale date. Join to `daily_context.order_date`. | `2025-07-06` |
| `product_key` | VARCHAR | `product:` + md5 of normalised name+colour. Join to `product_dimension`. | `product:e31889e1abbc25716f332375ed19bc68` |
| `planning_status` | VARCHAR | Normalised lifecycle status (§5.3). | `Seasonal` |
| `assigned_family` | VARCHAR | The single winning drop family for this product on this date, else NULL (§5.5). | `wt25d3-family` |
| `contribution_family` | VARCHAR | Mutually exclusive bucket: `core`, a `family_tag`, or `rest` (§5.6). | `rest` |
| `business_line` | VARCHAR | Taxonomy carried from the SKU's coherent metadata record. | `Women` |
| `category` | VARCHAR | Broad taxonomy. `Unknown` when the source was null. | `Tops` |
| `subcategory` | VARCHAR | Mid taxonomy. | `Tanks` |
| `item_class` | VARCHAR | Narrow taxonomy. | `Tanks` |
| `revenue` | DOUBLE | Summed source revenue. | `1247.95` |
| `units` | BIGINT | Summed source units. | `11` |
| `source_rows` | BIGINT | How many raw rows collapsed into this one. Audit aid. | `5` |

### 4.3 `product_dimension.parquet` — product lookup

| | |
|---|---|
| Grain | one row per `product_key` |
| Rows | 7,117 |

| Column | Type | Description | Example |
|---|---|---|---|
| `product_key` | VARCHAR | **PK.** | `product:5827db54ff925022bc72147087b1c043` |
| `product_name` | VARCHAR | Title with the trailing colour stripped (§5.2). | `Grounded No-Slip Mat Towel` |
| `product_title` | VARCHAR | Original title, preserved verbatim. | `Grounded No-Slip Mat Towel - Gravel` |
| `product_id` | BIGINT | Representative id. **Not identity.** | `8419936337954` |
| `color` | VARCHAR | `resolved_color` — source colour, else recovered from title (§5.2). | `Gravel` |
| `color_group` | VARCHAR | Coarse rollup, or `Mixed / multiple` if the product's SKUs disagree. | `Beige` |
| `item_class` / `subcategory` / `category` / `business_line` | VARCHAR | Taxonomy, or `Mixed / multiple` when SKUs disagree (§8.3). | `Towels` / `Towels` / `Equipment` / `Accessories` |
| `source_price` | DOUBLE | Representative price. Unvalidated — see §8.7. | `5970.0` |
| `first_seen_date` | DATE | First sale date for the product. | `2026-04-30` |
| `last_seen_date` | DATE | Last sale date. | `2026-09-14` |
| `sku_count` | BIGINT | Distinct SKUs rolling into this product. | `1` |

### 4.4 `product_drop_membership.parquet` — product ↔ drop bridge

| | |
|---|---|
| Grain | `product_key` × `family_tag` |
| Rows | 4,114 (3,933 distinct products across 100 drops) |
| **Non-additive** | A product can belong to several families; summing across `family_tag` double counts. |

| Column | Type | Description | Example |
|---|---|---|---|
| `product_key` | VARCHAR | FK → `product_dimension`. | `product:72b4c7d9…` |
| `family_tag` | VARCHAR | FK → `drop_calendar`. | `sp25d3-family` |
| `member_sku_count` | BIGINT | SKUs carrying the tag. | `1` |
| `first_tag_observed_date` | DATE | First date the tag was seen on this product. Drives eligibility (§5.5). | `2025-02-24` |
| `last_tag_observed_date` | DATE | Last date the tag was seen. | `2026-09-04` |

### 4.5 `drop_calendar.parquet` — validated releases

| | |
|---|---|
| Grain | one row per `family_tag` |
| Rows | 103 (FA21D1 2021-07-06 → FA26D3 2026-09-06) |

| Column | Type | Description | Example |
|---|---|---|---|
| `family_tag` | VARCHAR | **PK.** Lowercase canonical tag. | `fa26d3-family` |
| `drop_label` | VARCHAR | Uppercase, `-family` removed. | `FA26D3` |
| `season_code` | VARCHAR | `SP` \| `SU` \| `FA` \| `HO` \| `WT` | `FA` |
| `season_year` | BIGINT | 2000 + 2-digit year from the tag. | `2026` |
| `drop_number` | BIGINT | Drop index. **Not chronological in SP22** (§8.6). | `3` |
| `early_access_date` | DATE | Nullable (7 rows). | `2026-09-06` |
| `launch_date` | DATE | Public launch. | `2026-09-07` |
| `anchor_date` | DATE | `early_access_date` else `launch_date`. **The default ordering key.** | `2026-09-06` |
| `color_story` | VARCHAR | Colour story. Casing is inconsistent (§8.5). | `Warm Butter` |
| `primary_hex` | VARCHAR | First `#rrggbb`. Only 21/103 populated. | `#2b907f` |
| `hex_codes` | VARCHAR | Raw hex text. | `#2b907f` |
| `notes` | INTEGER | **Always null.** | `NULL` |

### 4.6 `daily_context.parquet` — calendar context

| | |
|---|---|
| Grain | one row per `order_date` |
| Rows | 623 |

| Column | Type | Description | Example |
|---|---|---|---|
| `order_date` | TIMESTAMP | **PK.** Note: TIMESTAMP here, DATE in the fact — cast when joining. | `2025-01-01` |
| `source_rows` | BIGINT | Raw rows that day. | `4084` |
| `active_skus` | BIGINT | Distinct SKUs that day. | `4084` |
| `daily_revenue` | DOUBLE | Total revenue. | `2230604.43` |
| `daily_units` | BIGINT | Total units. | `21440` |
| `trailing_28d_median_revenue` | DOUBLE | Rolling median; null for the first day. | `2230604.43` |
| `revenue_index` | DOUBLE | `daily_revenue / trailing_28d_median_revenue`. | `1.079763` |
| `is_volume_spike` | BOOLEAN | Rule: revenue ≥ 3× trailing 28-day median **and** ≥ global p90. 32 days. | `false` |
| `sale_period_name` | VARCHAR | From `sale_periods.csv`, else null. | `Holiday promotional window` |
| `sale_period_source` | VARCHAR | Provenance of the window. | `Legacy notebook exclusion window` |
| `is_configured_sale` | BOOLEAN | Inside a configured window. 68 days. | `false` |
| `is_incomplete_date` | BOOLEAN | Partial day. **`2026-09-15` is flagged true** — the last complete date is `2026-09-14`. | `false` |

### 4.7 `excluded_family_tags.parquet` — audit of ignored tags

Every family token seen in `inputs.csv` that did **not** become a validated drop. Audit only.

| | |
|---|---|
| Grain | one row per excluded `family_tag` |
| Rows | 460 |

| Column | Type | Example |
|---|---|---|
| `family_tag` | VARCHAR | `wt25drops-family` |
| `exclusion_reason` | VARCHAR | `Season rollup tag` |
| `token_rows` | BIGINT | `278697` |
| `sku_count` | BIGINT | `2983` |
| `token_associated_revenue` | DOUBLE | `212518006.94` |
| `first_observed_date` | DATE | `2025-10-21` |
| `last_observed_date` | DATE | `2026-09-15` |

**Exclusion reasons** (revenue is *associated*, not additive — a row can carry several tags):

| Reason | Tags | Associated revenue |
|---|---|---|
| Other non-conventional family | 255 | $478.0M |
| Drop extension / spotlight / capsule | 107 | $216.4M |
| M-prefixed / men-specific family | 80 | $391.0M |
| Season rollup tag | 13 | $1,461.4M |
| Canonical-looking tag absent from release calendar | 4 | $0.28M |
| No family tag | 1 | $346.3M |

### 4.8 `data_quality.json` — build audit

Not a table; a nested audit document written every build. Key paths:

| Path | Meaning | Current |
|---|---|---|
| `schema_version` | Bumped on breaking change | `2` |
| `built_at_utc` | Build timestamp | `2026-09-17T17:16:38Z` |
| `sources.*` | **Absolute paths** of the three inputs — machine-specific, see §8.8 | — |
| `raw.rows` / `raw.revenue` / `raw.units` | Source totals | 3,485,426 / $2,831,081,580.32 / 31,761,946 |
| `raw.ingest_parse.*` | Parse failures by kind | all `0` |
| `raw.unique_key_duplicates` | Exact dupes | `0` |
| `raw.apparent_duplicate_review.*` | Same date/SKU/revenue/units groups — **flagged, not deleted** | 2,578 groups, $3,192,610.49 |
| `raw.metadata_instability.*` | SKUs whose metadata drifts | 2,116 titles / 2,983 colours / 615 categories |
| `processed.revenue_delta_vs_raw` | Reconciliation | `-9.06e-06` |
| `processed.taxonomy_conflicts.*` | Products with mixed taxonomy | 380 business line ($341.8M), 98 category, 102 subcategory, 79 item class |
| `release_calendar.canonical_rows` | Validated drops | `103` of `441` |
| `daily_context.latest_complete_date` | Last trustworthy date | `2026-09-14` |
| `methodology.*` | Prose statements of every rule below | — |
| `contribution_reconciliation` | Core / Eligible drop / Rest totals | see §5.6 |

---

## 5. Transformation rules

### 5.1 Product identity — why not `product_id`

`product_id` **changes for many SKUs** over time, so it is retained but never trusted as
identity. Identity is `product_name + resolved_color`, which is stable across sizes and matches
the grain merchandisers expect.

```
product_key = 'product:' || md5(
    regexp_replace(lower(product_name),     '[^a-z0-9]+', ' ', 'g') || '|' ||
    regexp_replace(lower(resolved_color),   '[^a-z0-9]+', ' ', 'g')
)
```

Rows with no matching SKU fall back to `'unmapped:' || md5(lower(title) || '|' || lower(colour))`
so the fact stays fully reconcilable.

### 5.2 Deriving `product_name` and `resolved_color` from `product_title`

Applied in priority order:

| # | Condition | Result |
|---|---|---|
| 1 | `product_title` is NULL | `'Unknown SKU ' || sku` |
| 2 | title ends with `" - <color>"` (case-insensitive) | `rtrim(left(title, len(title) - len(color) - 3))` |
| 3 | title contains any `" - "` | `regexp_replace(title, '\s+-\s+.*$', '')` — cuts at the **first** separator |
| 4 | otherwise | title unchanged |

And the inverse: `resolved_color = coalesce(color, regexp_extract(title, '\s+-\s+(.+)$', 1))`.

Measured effect: 5,093 titles collapse to 1,418 products (~3.6 titles per product) in a 1% sample.
**Caveats in §8.1–§8.2.**

### 5.3 `planning_status` normalisation

`lower(trim(x))` mapped to canonical casing; anything unrecognised passes through, null → `Unknown`.

| Value | Fact rows | Revenue |
|---|---|---|
| `Core` | 134,424 | $863.1M |
| `Seasonal` | 231,788 | $803.7M |
| `Carryover` | 280,432 | $692.8M |
| `FPPhaseOut` | 652,729 | $444.1M |
| `Markdown` | 44,818 | $11.2M |
| `NOT-MAPPED` | 14,736 | $9.8M |
| `BeautyWellness` | 20,176 | $6.4M |

### 5.4 What makes a drop "validated"

Both must hold, else the tag lands in `excluded_family_tags`:

1. Tag matches `^(SP|SU|FA|HO|WT)\d{2}D\d+-family$` (case-insensitive)
2. It has at least one of `Early Access` / `Launch Date` in the workbook

441 workbook rows → **103 validated**.

### 5.5 Family assignment — one family per sale

A sale belongs to **at most one** family: the most recently anchored validated family attached to
that product and already eligible on that date.

```
eligible(family, date)  ⟺  greatest(anchor_date, first_tag_observed_date - 1 day) <= order_date
winner                  =  first(family_tag ORDER BY anchor_date DESC, family_tag DESC)
                             FILTER (WHERE eligible)
```

Membership starts no earlier than one day before the tag was first observed, and never before
Early Access / Launch. It then persists forward. Unmatched rows stay `rest`.

### 5.6 `contribution_family` — the mutually exclusive bucket

First match wins:

| Order | Test | Bucket |
|---|---|---|
| 1 | `planning_status = 'Core'` | `core` |
| 2 | `assigned_family IS NOT NULL` | that `family_tag` |
| 3 | otherwise | `rest` |

**Core outranks drop membership.** A Core product inside FA26D3 counts as Core, so a drop bucket
shows only its non-Core portion. This is the price of the buckets summing exactly to the total.

| Bucket type | Revenue | Units |
|---|---|---|
| Core | $863,098,913.11 | 10,338,376 |
| Eligible conventional drop | $1,337,126,953.72 | 14,648,154 |
| Rest / no eligible drop | $630,855,713.49 | 6,775,416 |

### 5.7 Measures policy

- Source `revenue` and `ordered_quantities` are preserved exactly.
- Supplied rolling fields (`*_last_7d`) and `price` are **not used**.
- Distinct `unique_key`s are preserved; apparent duplicates are flagged, never deleted.

---

## 6. Reference enumerations

### 6.1 `business_line`

| Value | Fact rows | Revenue |
|---|---|---|
| Women | 927,672 | $2,039.7M |
| Men | 283,277 | $545.7M |
| Accessories | 145,509 | $238.5M |
| Beauty | 15,562 | $5.8M |
| Wellness | 4,906 | $0.71M |
| Unknown | 2,105 | $0.59M |
| Books | 69 | $5,950.66 |
| Internal | 3 | $72.00 |

### 6.2 `color_group` (products in dimension)

`Black` 1475 · `Blue` 865 · `White` 756 · `Brown` 682 · `Grey` 679 · `Green` 602 · `Beige` 592 ·
`Pink` 568 · `Red` 321 · `Unknown` 244 · `Yellow` 118 · `Purple` 111 · `Mixed / multiple` 75 ·
`Orange` 27 · `Solid` 1 · `Misc` 1

### 6.3 `category` (top, by revenue)

`Bottoms` $1,076.1M · `Outerwear` $853.3M · `Tops` $338.5M · `Bras` $153.7M · `Shoes` $107.0M ·
**`NULL` $67.9M** · `One Piece` $56.9M · `Accessories` $53.0M

---

## 7. Generated analyst reports (repo root)

Produced by the EDA notebooks. **Not** part of the dashboard pipeline; safe to regenerate.

| File | Grain | Rows | Cols | Source |
|---|---|---|---|---|
| `01_product_color_pivot.csv` | product (wide: colour × 4 metrics) | 1,418 | 1,702 | pt1 §7–8, **1% sample** |
| `01_product_color_changes.csv` | title/product/colour triples | 34,562 | 4 | exported manually |
| `02_product_bestsellers.csv` | product | 1,981 | 89 | pt2 §2 |
| `02_color_summary.csv` | raw `color` | 585 | 89 | pt2 §3 |
| `02_resolved_color_summary.csv` | `resolved_color` | 625 | 89 | pt2 §4 |
| `02_color_vs_resolved_color.csv` | (`color`, `resolved_color`) mismatches | 393 | 92 | pt2 §5 |
| `02_multi_color_split.csv` | multi-colour `color` values | 227 | 92 | pt2 §6 |
| `02_primary_color_summary.csv` | `primary_color` | 107 | 87 | pt2 §7 |
| `02_item_class_summary.csv` | `item_class` | 77 | 87 | pt2 §8 |
| `02_subcategory_summary.csv` | `subcategory` | 71 | 87 | pt2 §9 |
| `02_category_summary.csv` | `category` | 29 | 87 | pt2 §10 |

### 7.1 Monthly column blocks (all `02_*` reports)

Every `02_*` report carries **four ordered blocks of 21 columns**, `2025-01` … `2026-09`:

| Prefix | Meaning |
|---|---|
| `sales_<YYYY-MM>` | revenue that month |
| `sales_chg_<YYYY-MM>` | **absolute** $ change vs prior month |
| `units_<YYYY-MM>` | units that month |
| `units_pct_chg_<YYYY-MM>` | **percent** change vs prior month |

Rules: a month with no activity is `0` (a real zero, not missing); the first month of each change
block is blank; a `%` change from a zero base is blank rather than infinite.

### 7.2 Multi-colour split (`02_multi_color_split.csv`)

`/` is the **only** separator in `color` (no commas, ampersands, "and", `+`, `|`).
`primary_color` = text before the first `/`; `secondary_colors` = everything after, kept whole
so 3-part values survive (`Light Provence Blue/Navy/White` → `Light Provence Blue` + `Navy/White`).
227 of 584 non-null colours are multi-colour (207 two-part, 20 three-part) = $170.2M, 6.0% of sales.

---

## 8. Known issues and gotchas

Read this section before trusting any number.

### 8.1 `resolved_color` contains non-colours
When `color` is null the fallback takes whatever follows `" - "`, which for wellness / candle /
rewards lines is a quantity: `60 Pack`, `8 oz`, `50ML`, `450 points`, `All Colors`.
**`product_dimension` currently has 27 such rows, and they are inside `product_key`.**
A vocabulary whitelist is the wrong fix — ~18 genuine colours (`Grey Tiedye`, `Java Brown`,
`Bordeaux`, `Light Grey Iridescent`, …) appear *only* in titles. Filter by shape instead:
`^\s*(?:\d+\s*(?:pack|oz|ml|g|points?)|all colors)\s*$`.

### 8.2 `product_name` splits on the *first* `" - "`
A title with two separators fragments. `"Ambience Short - Graphic - Black/Black"` yields both
`Ambience Short - Graphic`/`Black/Black` and `Ambience Short`/`Black` — two `product_key`s.
Currently **1 title of 7,117**. Fix would be splitting on the last separator.

### 8.3 Mixed taxonomy is labelled, not resolved
380 products span multiple business lines ($341.8M) and are shown as `Mixed / multiple` rather
than arbitrarily picking one SKU. Also 98 category / 102 subcategory / 79 item class.

### 8.4 `subcategory` is not a clean parent of `item_class`
`Leggings`, `Sweatpants`, `Pants`, `Jackets`, `Bras` appear in **both** with identical totals.
The only real rollup is `Coverups` ($640.4M), absorbing Pullovers + Hoodies. Do not treat the
three taxonomy columns as a strict hierarchy.

### 8.5 Unclassified taxonomy is one population
The **same $67,936,207.63** is unclassified at item class, subcategory *and* category — one set of
rows missing the whole block, not independent gaps. It is the 5th-largest "category".

### 8.6 Calendar quirks
- `primary_hex` populated for only 21/103 drops (a contiguous WT25D1 → SU26D7 block).
- 12 rows from 2021 have `color_story = "No Color"`; FA21D1 has lowercase `"no Color"` — naive
  grouping splits them.
- 7 rows have no `early_access_date`, so the Early-access anchor toggle does nothing for them.
- SP22 has no `d7`, and `drop_number` is **not** chronological there (SP22D4 precedes SP22D5).

### 8.7 Censoring in date columns
`first_sale_date = 2025-01-01` means "already selling when the extract starts" (left-censored),
and `last_sale_date = 2026-09-15` means "still selling" (right-censored). Neither is a launch or
discontinuation. Only interior dates are real events. Also note `2026-09-15` is flagged
`is_incomplete_date` — prefer `2026-09-14` as the last complete day.

### 8.8 Build artefacts carry absolute paths
`data_quality.json` records the absolute paths of its three inputs, so rebuilding on a different
machine produces a real diff on that file even when nothing else changed.

### 8.9 Sampling destroys date-based metrics
In a 1% row sample, `active_days` captures a **median 2.5%** of true active days, and **33% of
product-colour pairs disappear** (worst for the long tail). Revenue *shares* survive sampling;
counts, dates and coverage do not. Use full-extract queries for those.

### 8.10 Apparent duplicates are retained
2,578 groups sharing date/SKU/revenue/units ($3,192,610.49) are flagged in `data_quality.json`
but **kept** in the fact, by design. Decide per analysis whether to net them out.

---

## 9. Recipes

```sql
-- Revenue by contribution bucket, complete days only, excluding promos
SELECT f.contribution_family, sum(f.revenue) AS revenue, sum(f.units) AS units
FROM read_parquet('to_share/data/processed/product_daily.parquet') f
JOIN read_parquet('to_share/data/processed/daily_context.parquet') c
  ON c.order_date = f.order_date
WHERE f.order_date <= DATE '2026-09-14'
  AND NOT c.is_configured_sale
GROUP BY 1 ORDER BY revenue DESC;
```

```sql
-- The three latest validated drops as of a reference date
SELECT family_tag, drop_label, color_story, anchor_date
FROM read_parquet('to_share/data/processed/drop_calendar.parquet')
WHERE anchor_date <= DATE '2026-09-15'
ORDER BY anchor_date DESC, family_tag DESC
LIMIT 3;
```

```sql
-- Product detail with taxonomy (fact is additive, so this is safe)
SELECT d.product_name, d.color, d.category,
       sum(f.revenue) AS revenue, sum(f.units) AS units,
       min(f.order_date) AS first_sale, max(f.order_date) AS last_sale
FROM read_parquet('to_share/data/processed/product_daily.parquet') f
JOIN read_parquet('to_share/data/processed/product_dimension.parquet') d
  USING (product_key)
GROUP BY 1,2,3 ORDER BY revenue DESC LIMIT 25;
```

```sql
-- Cohort size per drop. NON-ADDITIVE across family_tag: a product may appear in several.
SELECT m.family_tag, r.color_story, count(DISTINCT m.product_key) AS products
FROM read_parquet('to_share/data/processed/product_drop_membership.parquet') m
JOIN read_parquet('to_share/data/processed/drop_calendar.parquet') r USING (family_tag)
GROUP BY 1,2 ORDER BY products DESC;
```

```python
# Scan the raw extract without loading it into pandas
import duckdb
con = duckdb.connect(); con.execute("PRAGMA threads=4")
df = con.execute("""
    SELECT strftime(order_date, '%Y-%m') AS ym, sum(revenue) AS sales
    FROM read_csv_auto('to_share/inputs.csv', sample_size=200000)
    GROUP BY 1 ORDER BY 1
""").df()
```

---

## 10. Invariants to preserve

1. `product_daily` reconciles to the raw extract on revenue and units.
2. `core` + every `family_tag` + `rest` sums exactly to the total — buckets never overlap.
3. `product_drop_membership` is non-additive across `family_tag`.
4. The raw CSV is never loaded into pandas, and never modified.
5. `tests/test_data_contract.py` (8 tests) must pass after any build change.
6. Changing `product_key` derivation invalidates every stored key — treat as a breaking change
   and bump `schema_version`.
