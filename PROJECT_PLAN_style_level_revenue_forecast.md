# Project Plan — Style-Level Weekly Revenue Forecast

**Document type:** execution handoff. Written to be read by a coding agent (Claude Code) and by the
humans reviewing its output.
**Version:** 2.0 · **Date:** 2026-09-18
**Repository:** https://github.com/AloDeepan/Product_level_forecast.git
**Data reference:** `DATA_MODEL.md` and `to_share/README.md` in that repository. Section numbers
below are cited as §N and refer to `DATA_MODEL.md` unless the text says README.

**Sources used to write this plan.** Only the two repository documents named above, plus direct
inspection of the cloned repository. No web search was performed and no outside material was
consulted, so there are no external links to cite.

---

## Part 1 — What this project is

### 1.1 The question

Can weekly revenue be forecast four weeks ahead at the level of an individual style, accurately
enough for merchandising to plan on, using a method whose logic a stakeholder can follow and challenge?

A **style** is a product name with the colour removed. `Grounded No-Slip Mat Towel - Gravel` and
`Grounded No-Slip Mat Towel - Jungle` are two colours of one style.

### 1.2 What is fixed, and why

| Item | Setting | Reason |
|---|---|---|
| Forecast unit | Style (`product_name`, colours pooled) | This is the level at which the business wants to see demand. Colour is a second-stage question |
| Horizon | 4 weeks ahead | Set by the business |
| Grain | Weekly | Daily revenue in this data is volatile and drop-driven. Weekly is the stable starting grain. Daily is a later phase |
| Measure | Revenue | Set by the business |
| Accuracy bar | Under 5% error on total revenue, four weeks ahead | Set by the business. Section 4.3 defines exactly how this is computed |
| Method constraint | Explainable. Every forecast must decompose into terms a stakeholder can name | A number nobody can interrogate will not be used, regardless of its accuracy |
| Starting position | Nothing exists at this grain and nothing will be supplied | The only comparison points are the naive baselines built in Phase 9 |

### 1.3 What this project is not

It does not forecast colour, size, or SKU. Size is not present in the fact table at all (§4.2), so
size-level work would require a different data build. It does not cover buy quantity, depletion, or
inventory, which the README places out of scope. It does not modify the source extract or the
existing dashboard pipeline.

### 1.4 What "done" means for this phase of work

A written readout that answers, with evidence: how much revenue is forecastable at style level, for
which kinds of style, at what error, and whether the 5% bar is reachable. Plus the reusable code and
data that produced those answers. Model building starts only after this readout is accepted.

---

## Part 2 — Environment and ground rules for the agent

### 2.1 Repository layout

```
Product_level_forecast/
├── DATA_MODEL.md                      # the data dictionary. Authoritative
├── 01_EDA_product_distro_pt1.ipynb    # prior exploration, reference only
├── 02_EDA_product_distro_pt2.ipynb    # prior exploration, reference only
├── explore_vscode.ipynb               # shows the Redshift pull. Reference only
└── to_share/
    ├── README.md                      # pipeline and methodology notes. Authoritative
    ├── app.py                         # Streamlit dashboard. Do not modify
    ├── build_dashboard_data.py        # the builder. Do not modify
    ├── requirements.txt
    ├── tests/test_data_contract.py    # 8 tests. Must still pass at the end
    ├── old_codes/ana.ipynb            # legacy notebook. Reference only
    └── data/processed/                # ← all inputs for this project live here
        ├── product_daily.parquet
        ├── product_dimension.parquet
        ├── product_drop_membership.parquet
        ├── drop_calendar.parquet
        ├── daily_context.parquet
        ├── excluded_family_tags.parquet
        └── data_quality.json
```

### 2.2 What is present and what is absent

The seven files in `to_share/data/processed/` are committed to the repository and are sufficient for
every phase in this plan.

The three raw inputs are **not** in the repository, because `.gitignore` excludes `*.csv`, `*.xlsx`
and `*.xls`. Those are `to_share/inputs.csv` (919 MB), `to_share/Product Release Dates.xlsx`, and
`to_share/config/sale_periods.csv`. Consequently `build_dashboard_data.py` cannot be re-run without
obtaining them separately. **No phase in this plan requires them.** If a phase appears to need the
raw extract, that is a signal the phase has been misread, and it should be raised rather than worked
around.

The eleven analyst CSV reports listed in §7 are also absent for the same reason. They are
regenerable and are not inputs here.

### 2.3 Rules the agent must follow

1. **Never modify anything under `to_share/`.** All new work goes in a new top-level directory,
   `analysis/`. The existing dashboard and its builder must keep working untouched.
2. **Never load the raw CSV into pandas**, in the unlikely event it becomes available. The project
   convention is DuckDB scanning to Parquet (§1, Invariant 4).
3. **Never sample.** §8.9 records that in a 1% row sample, active-day counts capture a median 2.5%
   of true active days and 33% of product-colour pairs vanish. Revenue shares survive sampling;
   counts, dates and coverage do not. Every number in this project is a count, a date, or a coverage
   measure at some point, so all queries run on the full processed tables.
4. **Reconcile before analysing.** Any aggregate built from `product_daily` must, before filtering,
   total `$2,831,081,580.32` revenue and `31,761,946` units (§2, §4.8). A build that does not
   reconcile is a bug, not a finding.
5. **No leakage in any backtest.** A forecast standing at week *t* may read only data with
   `week_start <= t`. This includes derived features: segment membership, volatility, product age,
   and any rolling statistic. Compute them as-of the origin, not once over the whole history.
6. **Determinism.** Fix any random seed. Pin library versions to `to_share/requirements.txt`. Write
   an audit JSON for every generated artefact recording row counts, totals, the git commit, and the
   parameters used.
7. **Write down every judgement call** in `analysis/DECISIONS.md` with the date, the choice, the
   alternative rejected, and the revenue affected. This document is what makes the work defensible
   in review.
8. **Re-run `to_share/tests/test_data_contract.py` at the end.** All 8 tests must still pass.
   Command: `cd to_share && PYTHONPATH=. python -m unittest tests.test_data_contract`

### 2.4 Output locations

```
analysis/
├── DECISIONS.md                 # running log of every judgement call
├── MEASUREMENT_SPEC.md          # Phase 0 output. Written before any number exists
├── build/                       # scripts that produce data
├── data/                        # generated tables (parquet) + audit json
├── reports/                     # one markdown findings file per phase
└── figures/                     # charts
```

Phase reports are named `reports/P<n>_<topic>.md`. Each one opens with the question it answers, and
closes with the decision it unlocks and what it changes about the plan.

---

## Part 3 — Facts about the data, taken from the data model

These are the starting conditions. The agent should verify each one in Phase 2 rather than trusting
this list, because a mismatch means the data has changed since this plan was written.

### 3.1 Volumes and coverage

| Fact | Value | Source |
|---|---|---|
| Fact table rows | 1,379,103 | §4.2 |
| Distinct product-colour keys | 7,117 | §4.3 |
| Product-to-drop bridge rows | 4,114, covering 3,933 products across 100 drops | §4.4 |
| Validated drops | 103, from FA21D1 (2021-07-06) to FA26D3 (2026-09-06) | §4.5 |
| Distinct sale dates | 623 | §4.6 |
| Date range | 2025-01-01 to 2026-09-15 | §3.1 |
| Last complete day | 2026-09-14. 2026-09-15 is flagged `is_incomplete_date` | §4.6, §8.7 |
| Total revenue | $2,831,081,580.32 | §2 |
| Total units | 31,761,946 | §2 |
| Build stamp of the committed data | 2026-09-17T17:16:38Z, schema version 2 | §4.8 |

The number of distinct **styles** is not stated anywhere in the data model. §5.2 reports that in a
1% sample, 5,093 titles collapsed to 1,418 products, but that is a sampled figure and §8.9 warns
that counts do not survive sampling. Establishing the true style count is a Phase 2 task.

### 3.2 Lifecycle status, which drives segmentation

`planning_status` is recorded per row per date (§4.2), so a style's status changes over its life.

| Status | Fact rows | Revenue | Forecasting character |
|---|---|---|---|
| Core | 134,424 | $863.1M | Long history, stable demand |
| Seasonal | 231,788 | $803.7M | Drop-driven, short life |
| Carryover | 280,432 | $692.8M | Continuing from a prior season |
| FPPhaseOut | 652,729 | $444.1M | Declining toward zero |
| Markdown | 44,818 | $11.2M | Price-driven clearance |
| NOT-MAPPED | 14,736 | $9.8M | Unclassified |
| BeautyWellness | 20,176 | $6.4M | Separate assortment |

Source: §5.3.

### 3.3 Business line concentration

Women $2,039.7M · Men $545.7M · Accessories $238.5M · Beauty $5.8M · Wellness $0.71M ·
Unknown $0.59M · Books $5,950.66 · Internal $72.00. Source: §6.1.

The last five lines together are under $7M against a $2.83B total. Phase 3 decides whether they stay
in scope.

### 3.4 Attribution buckets

`contribution_family` assigns every fact row to exactly one bucket, and the buckets sum to the total
(§5.6). Core is tested first, so a Core product inside a drop counts as Core and the drop bucket
shows only its non-Core portion.

| Bucket | Revenue | Units |
|---|---|---|
| Core | $863,098,913.11 | 10,338,376 |
| Eligible conventional drop | $1,337,126,953.72 | 14,648,154 |
| Rest, no eligible drop | $630,855,713.49 | 6,775,416 |

### 3.5 Calendar context available per day

`daily_context` (§4.6) supplies, per date: total revenue and units, a trailing 28-day median, a
revenue index, `is_volume_spike` (32 days, defined as revenue at least 3× the trailing 28-day median
**and** at or above the global 90th percentile), `is_configured_sale` (68 days, from two windows in
`config/sale_periods.csv`), and `is_incomplete_date`.

The README states explicitly that a volume spike is a statistical flag and is not assumed to be a
promotion.

### 3.6 Drop calendar contents

`drop_calendar` (§4.5) gives, per validated drop: `family_tag`, `drop_label`, `season_code`,
`season_year`, `drop_number`, `early_access_date`, `launch_date`, `anchor_date` (early access where
it exists, otherwise launch), `color_story`, and hex colours.

`product_drop_membership` (§4.4) links product-colour to drop with `first_tag_observed_date` and
`last_tag_observed_date`.

Eligibility, per §5.5: a sale belongs to at most one family, being the most recently anchored
validated family attached to that product that is already eligible on that date, where eligibility
begins at `greatest(anchor_date, first_tag_observed_date - 1 day)`.

---

## Part 4 — Definitions that must be fixed before any code runs

Ambiguity here propagates into every number downstream, so each definition is written out in full.

### 4.1 Style key

```
style_name_normalised = regexp_replace(lower(product_name), '[^a-z0-9]+', ' ', 'g')  -- then trim
style_key             = 'style:' || md5(style_name_normalised)
```

`product_name` comes from `product_dimension` (§4.3), which already holds the title with the
trailing colour stripped. The fact table carries `product_key`, not `product_name`, so the fact must
be joined to the dimension on `product_key` to reach style.

Do not reuse `product_key` for this purpose: it is an md5 of name **and** colour (§5.1), so it is a
style-colour identifier, not a style identifier.

### 4.2 Week

Default: ISO weeks, Monday start, labelled by `week_start` date.

This must be a parameter in the code, not a hard-coded value, because the business may use a retail
4-5-4 calendar instead. The README records that the fiscal calendar file from the legacy notebook is
not available, which is why ISO is the default rather than the confirmed answer. See Blocker B4.

A week enters the analysis only if all seven of its days fall within 2025-01-01 to 2026-09-14
inclusive. 2026-09-15 is excluded because it is flagged incomplete (§4.6). With ISO weeks this is
expected to yield roughly 88 complete weeks, the first starting 2025-01-06 and the last starting
2026-09-07. The agent computes the exact figure and reports it; the number here is a check, not an
input.

### 4.3 Error, written out

Let an **origin** be a week *t* from which the forecast is made. The forecast covers weeks
*t+1* through *t+4*.

**Primary measure — total revenue error.**

```
For each origin t:
    F_t = sum of forecast revenue across all styles, weeks t+1..t+4
    A_t = sum of actual   revenue across all styles, weeks t+1..t+4
    APE_t = |F_t - A_t| / A_t

Headline = mean of APE_t across all origins, expressed as a percentage
```

This is the number compared to the 5% bar.

**Secondary measure — style-level error, revenue weighted.**

```
For each origin t:
    WAPE_t = ( sum over styles and weeks of |forecast - actual| )
             / ( sum over styles and weeks of actual )
```

Weighted absolute percentage error is used rather than an average of per-style percentage errors,
for two reasons. A style with zero actual revenue in a week makes a percentage error undefined, and
this data will contain many such weeks. And an unweighted average lets a hundred tiny styles
outvote the styles that carry the revenue, which is the opposite of what the business needs.

**Third measure — skill against baseline.**

```
Skill = 1 - (error of method / error of best naive baseline)
```

Positive skill means the method earned its complexity. Zero or negative means the simple rule was
as good, which is a legitimate and publishable result.

**Fourth measure — bias.**

```
Bias_t = (F_t - A_t) / A_t          -- signed, not absolute
```

Reported alongside the headline. A forecast that is 4% off but always low is a different operational
problem from one that is 4% off in both directions, and planners need to know which they have.

### 4.4 Backtest protocol

Rolling origin, expanding training window. Stand at week *t*, using only data up to and including
*t*. Forecast *t+1* to *t+4*. Step forward one week. Repeat.

Minimum training window: 26 weeks. With roughly 88 complete weeks, and four weeks needed after each
origin, this yields on the order of 59 origins. The agent computes and reports the exact count.

The final 8 weeks are held back entirely and are not touched until a method is selected. This
protects against the slow overfitting that comes from repeatedly looking at the same test period.

### 4.5 Segment

A grouping of styles built only from information available **before** the forecast window opens.
Growth-shape clustering is explicitly excluded, because it groups styles on the very history being
predicted, it is unstable across re-runs, and a stakeholder cannot apply the label to a style that has
no history yet. Permitted inputs are listed in Phase 4.

---

## Part 5 — Phases

Each phase states its question, its inputs, the work, the deliverable, and the condition for moving
on. Phases run in order. Phase F is the decision point for the whole project.

---

### Phase 0 — Measurement specification

**Question.** How will success be judged, and is that agreed before anyone has a stake in the answer?

**Work.** Write `analysis/MEASUREMENT_SPEC.md` containing: the four formulas from section 4.3 with a
worked arithmetic example on invented numbers; the backtest protocol from 4.4 including the exact
origin count once computed; the week definition from 4.2; and the treatment of promotional weeks,
spike weeks and cold-start revenue, stating whether they sit inside the headline number or are
reported separately.

**Deliverable.** `analysis/MEASUREMENT_SPEC.md`, circulated for sign-off.

**Exit condition.** Spec circulated. Phase 1 may begin in parallel with sign-off, but no accuracy
number is produced or shown until the spec is agreed.

---

### Phase 1 — Build the style-week analysis base

**Question.** What is the one table every later phase reads?

**Inputs.** `product_daily.parquet`, `product_dimension.parquet`, `daily_context.parquet`,
`product_drop_membership.parquet`, `drop_calendar.parquet`.

**Target table.** `analysis/data/style_week.parquet`, one row per `style_key` × `week_start`.

| Column | Type | Definition |
|---|---|---|
| `style_key` | VARCHAR | Section 4.1 |
| `style_name` | VARCHAR | Normalised display name |
| `week_start` | DATE | Section 4.2 |
| `revenue` | DOUBLE | Sum of fact revenue |
| `units` | BIGINT | Sum of fact units |
| `realised_price` | DOUBLE | `revenue / units`, null when units is zero |
| `active_colours` | BIGINT | Distinct `product_key` with revenue that week |
| `continuation_revenue` | DOUBLE | Phase 6 definition |
| `injection_revenue` | DOUBLE | Phase 6 definition |
| `dominant_status` | VARCHAR | `planning_status` with the most revenue that week |
| `status_mix` | VARCHAR | All statuses present, with revenue shares |
| `dominant_family` | VARCHAR | `assigned_family` with the most revenue that week, else null |
| `weeks_since_anchor` | BIGINT | Weeks from the style's most recent drop `anchor_date`, null if none |
| `business_line`, `category`, `subcategory`, `item_class` | VARCHAR | Dominant by revenue across the style's history, else `Mixed / multiple` |
| `first_active_week` | DATE | First week with revenue |
| `age_weeks` | BIGINT | Weeks since `first_active_week`, null where left-censored |
| `age_is_censored` | BOOLEAN | True where the style was already selling in the first week of the extract |
| `sale_days_in_week` | BIGINT | Days flagged `is_configured_sale` |
| `spike_days_in_week` | BIGINT | Days flagged `is_volume_spike` |
| `source_rows` | BIGINT | Fact rows collapsed into this row, for audit |

**Rules and the reason for each.**

1. **Dense grid.** Every style must have a row for every week between its first and last active
   week, with revenue zero where there were no sales. The fact table omits rows for no-sale days, so
   the zeros must be created. A model that never sees zeros will not predict them, and §7.1 records
   that a month with no activity is a real zero in this business, not missing data.
2. **Cast on join.** `daily_context.order_date` is TIMESTAMP while the fact is DATE (§4.6).
3. **Status and family are part of the fact grain** (§4.2), so a style-week legitimately holds
   several of each. Keep the dominant for modelling and the mix for audit. Do not silently pick one.
4. **Age must not come from `first_seen_date` or `last_seen_date`.** §8.7 states that
   `first_sale_date = 2025-01-01` means "already selling when the extract starts" and
   `last_sale_date = 2026-09-15` means "still selling". Neither is a launch or a discontinuation.
   Styles active in the first week get `age_is_censored = true` and a null age. Where a style has
   drop membership, `anchor_date` and `first_tag_observed_date` give a real release date and should
   be preferred.
5. **Reconcile before any week filtering.** Total revenue across all style-weeks, including partial
   weeks, must equal $2,831,081,580.32 and units 31,761,946. Then apply the complete-week filter and
   record exactly how much revenue that filter removed.

**Deliverable.** `style_week.parquet`, a build audit JSON, and `reports/P1_base_table.md`.

**Exit condition.** Reconciliation passes exactly. Revenue dropped by the complete-week filter is
quantified and recorded.

---

### Phase 2 — Integrity checks

**Question.** What in this data will distort a forecast if left unhandled?

Each check produces a number and a recorded decision, not a silent fix.

| # | Check | What to compute | Decision it forces |
|---|---|---|---|
| 2.1 | Ground truth | Every figure in Part 3, re-derived | Whether this plan's stated facts still hold |
| 2.2 | Style count | Distinct styles overall, and with revenue in the last 13 weeks | Scope and compute budget. The "~1,900" working figure is unverified |
| 2.3 | Title fragmentation | §8.2 records one title of 7,117 splitting on the first `" - "` into two keys. Does it survive into style level? | Whether a fix is needed. One title is likely immaterial, but this must be shown, not assumed |
| 2.4 | Non-colour values | §8.1 records 27 dimension rows where the colour slot holds a quantity such as `8 oz` or `60 Pack` | Whether pooling colour into style neutralises them |
| 2.5 | Apparent duplicates | §8.10 records 2,578 groups sharing date, SKU, revenue and units, worth $3,192,610.49, retained by design. Compute their share **per week**, not only overall | Keep or net out. The overall share is 0.11%, but a single concentrated week matters against a 5% bar |
| 2.6 | Mixed taxonomy | §8.3 records 380 products spanning multiple business lines ($341.8M), plus 98 category, 102 subcategory, 79 item class conflicts. Does pooling colour into style reduce or increase this? | Whether taxonomy is usable as a segmentation input |
| 2.7 | Unclassified block | §8.5 records the same $67,936,207.63 missing item class, subcategory and category together. It is one population, not three independent gaps | Whether these styles form their own segment |
| 2.8 | Sparsity | Share of style-weeks with zero revenue, by revenue size band | Whether the tail can be forecast individually at all |
| 2.9 | Series length | Distribution of usable weeks per style, censoring-aware | How many styles can support any time-series method |
| 2.10 | Excluded tags | §4.7 records 460 excluded family tags. `NO_FAM` alone carries $346.3M associated revenue, season rollups $1,461.4M. Associated revenue is **not additive**, because a row can carry several tags, so these figures cannot be summed | Whether real drop activity is being missed by the validation rule in §5.4 |

**Deliverable.** `reports/P2_integrity.md`, with every figure and every decision recorded in
`DECISIONS.md`.

**Exit condition.** No unexplained mismatch against Part 3. Any mismatch is escalated before Phase 3.

---

### Phase 3 — Revenue concentration

**Question.** How much of this problem is large, and how stable is the large part?

**Work.**
- Rank styles by revenue over the last 13 weeks and the last 52 weeks.
- Cumulative revenue share curve. Count of styles reaching 50%, 80%, 95%.
- Stability: of the styles in the top 80% in one quarter, how many remain there the next quarter.
- Repeat within each business line, using the §6.1 figures as the reference.

**Decisions unlocked.** Which styles receive an individual forecast and which are forecast as a
group. Whether the five small business lines, together under $7M of $2.83B, stay in scope.

**Deliverable.** `reports/P3_concentration.md`, concentration curve figure.

**Exit condition.** A defensible head/tail cut, expressed as a style count and a revenue share.

---

### Phase 4 — Segmentation on traits known in advance

**Question.** What groups of styles behave alike, in terms a stakeholder would recognise?

**Permitted inputs.** All computable as-of a forecast origin without seeing the future.

| Trait | Source |
|---|---|
| Revenue size band | Phase 3 |
| Week-to-week volatility over the trailing 13 weeks | Phase 1 |
| Usable weeks of history, censoring-aware | Phase 1 |
| Lifecycle status mix and recent status transitions | §5.3, Phase 1 |
| Drop-linked or not, and weeks since last anchor | §4.4, §4.5 |
| Business line and category, where not `Mixed / multiple` | §4.2, Phase 2.6 |
| Share of weeks with zero revenue | Phase 2.8 |

**The lifecycle split carries the most weight**, because it separates three genuinely different
problems: always-on Core with long history; Seasonal and drop-linked styles that may have no history
at forecast time; and FPPhaseOut and Markdown styles whose trend is a decline toward zero.

Status transitions deserve particular attention. Because `planning_status` is recorded per row per
date, a style moving Core → Carryover → FPPhaseOut is visible in the data before the revenue decline
completes. That is both a predictive signal and an explanation a stakeholder will accept.

**Deliverable.** `reports/P4_segments.md` with segment definitions, style counts, revenue shares, and
a plain-language description of each segment.

**Exit condition.** Segment definitions frozen and reviewed by merchandising before Phase 9. Frozen
definitions matter because a segment that changes between runs destroys trust in the results.

---

### Phase 5 — Drop mechanics

**Question, and it is the most consequential in the plan.** When a drop lands, is it new styles, or
existing styles appearing in a new colour?

This determines whether style-level forecasting is mostly a continuation problem or mostly a
cold-start problem. If drops are predominantly new colours of existing styles, most revenue in any
forecast window has history and the task is tractable. If drops bring genuinely new styles, a real
share of every window has no history at all and no time-series method can reach it.

**Do not assume the answer.** This plan does not state one, because the data model does not contain
one. It is a query.

**Work.**

1. For each of the 103 validated drops, join `product_drop_membership` to `drop_calendar` and split
   its member products into styles already selling before the drop's `anchor_date` versus styles
   never seen before that date. Express the split in **revenue**, not counts.
2. Repeat the split restricted to the last 26 weeks, since recent behaviour is what a live forecast
   faces.
3. Count how many of the 103 drops fall inside the sales window at all. The calendar starts at
   FA21D1 in 2021 while sales start 2025-01-01, so early drops have a release date and no sales.
4. Build release-aligned curves: for each drop, revenue by week since anchor, as a share of the
   first eight weeks. Measure how consistent that shape is across drops.
5. Test whether week-one revenue predicts weeks two to five. If it does, cold-start shrinks to a
   seven-day problem rather than a four-week one.
6. Check the seven drops with no `early_access_date` (§4.5, §8.6), whose anchor falls back to launch,
   for a different curve shape.
7. Quantify the drop cadence actually present in the data: distribution of days between consecutive
   `anchor_date` values.

**Two calendar defects to respect.** §8.6 records that `drop_number` is not chronological in SP22 and
that SP22 has no D7, so ordering must always use `anchor_date`. It also records that twelve 2021 rows
have `color_story = "No Color"` while FA21D1 has lowercase `"no Color"`, so naive grouping on that
field splits them.

**Deliverable.** `reports/P5_drop_mechanics.md`, release-aligned curve figure.

**Exit condition.** The new-style versus new-colour split is quantified in revenue terms, for the
full history and for the last 26 weeks.

---

### Phase 6 — Is style-level demand declining?

**Question.** Net of colour refresh, is demand for a style going down?

**Why the direct approach fails.** Summing colours into a style and fitting a trend conflates two
different things. A style with flat demand whose colour refreshes have stopped will appear to be
dying. A style in genuine decline that has just received a fresh colour will appear healthy. The
trend must be measured on a series that excludes the refresh effect.

**The decomposition.** For each style-week, split revenue in two:

- **Injection revenue** — revenue from colours (`product_key` values) whose first sale falls within
  the trailing N weeks, N being a parameter with a default of 8, or whose drop `anchor_date` falls
  within that window.
- **Continuation revenue** — all remaining revenue, from colours already selling before that window.

Colours already selling in the first week of the extract are left-censored and count as
continuation, with a flag, because their true start date is unknown (§8.7).

This is the one place where colour must be examined despite being parked, and the cost is justified
because the answer changes the business conclusion.

**Additional cuts.**
- Trend on continuation revenue, by segment from Phase 4, not only in total. A falling total is
  usually a mix shift rather than uniform decline.
- Separate "fewer styles selling" from "each style selling less": count of active styles per week
  against average revenue per active style.
- Compare against the total revenue trend from `daily_context`, as a reference line that the
  style-level conclusions must be consistent with.

**Deliverable.** `reports/P6_demand_trend.md` with the headline answer stated in one sentence, plus
supporting figures.

**Exit condition.** The decline question is answered separately for continuation and injection, by
segment.

---

### Phase 7 — Splitting revenue into units and price

**Question.** Is revenue better forecast directly, or as units multiplied by realised price?

**Work.**
- Compute realised price as revenue divided by units. The source `price` column must not be used:
  §3.1 marks it "Not used by the build" and the README states it contains mixed scaling regimes.
  §4.3 flags `source_price` as unvalidated, with an example value of `5970.0`.
- Chart realised price per style over time and identify step changes, which indicate markdown.
- Test whether the `Markdown` and `FPPhaseOut` statuses coincide with realised-price drops. If they
  do, status becomes a usable forward markdown signal.
- Compare volatility of units against volatility of price, by segment, to see which side carries the
  forecast difficulty.

**Why this matters for the explainability constraint.** "We expect nine percent fewer units at four
percent lower realised price" is a sentence a stakeholder can dispute on its merits. A single revenue
number is not.

**Deliverable.** `reports/P7_units_price.md`.

**Exit condition.** A recommendation, with evidence, on whether to model revenue directly or as two
components.

---

### Phase 8 — Events: promotions, spikes, and the calendar

**Question.** How much of weekly revenue movement is driven by events that could be known in advance?

**Work.**
- Quantify revenue in weeks containing configured-sale days (68 days) and volume-spike days
  (32 days), as a share of total. If that share is large, event handling is the main lever on
  accuracy, not product granularity.
- Investigate the May 2026 surge named in the README. It is currently flagged as a statistical volume
  spike and explicitly not assumed to be a promotion. Someone in the business knows what it was, and
  that single answer decides whether it is signal to model or noise to flag.
- Test whether the two windows in `config/sale_periods.csv` plausibly represent the whole promotional
  calendar across roughly 88 weeks, by looking for realised-price dips and volume jumps outside them.
- Quantify how much accuracy is lost when event weeks are forecast without knowing the event.

**Do not remove promotional revenue from the target.** It is real revenue and the business plans on
the total. Events belong in the model as known inputs, not in the discard pile.

**Deliverable.** `reports/P8_events.md`, and a written dependency statement on the forward promotional
calendar (Blocker B3).

**Exit condition.** Event revenue share quantified and the calendar dependency escalated in writing.

---

### Phase 9 — Naive baselines and the backtest harness

**Question.** Which styles and segments are predictable, and by how much does anything beat a simple
rule?

**These baselines are the only reference point in the project**, since nothing exists at this grain
to compare against. They are a deliverable in their own right, not a warm-up, and they are scored
exactly as any later method will be scored.

**Baselines, all trivially explainable.**

| Name | Rule |
|---|---|
| Last week repeated | Each of the next four weeks equals the most recent observed week |
| Trailing 4-week mean | Flat continuation of the recent average |
| Trailing mean with trend | Recent average extended by the recent slope, with the slope capped to avoid runaway extrapolation on short series |
| Seasonal naive | Same week one year earlier. Testable only for the second year of data, and with a single observation per calendar week |
| Segment share allocation | Forecast the segment or total, then split it across styles by recent revenue share |
| Zero | Predict zero. The correct baseline for styles in phase-out, and a genuine contender there |

**Harness requirements.** Rolling origin per section 4.4. All four measures from section 4.3 reported
per origin and averaged. Results broken down by segment, by revenue size band, and by weeks of
history. The final 8 weeks untouched.

**Feature timing.** Every feature must be computed as-of the origin. Segment membership, volatility,
age and rolling statistics all change over time, and computing them over the full history would leak
future information into past forecasts and produce results that cannot be reproduced live.

**Output.** A skill ranking: for each segment, its revenue share, its best baseline, that baseline's
error, and the verdict. A segment already predicted within tolerance by a trailing average needs no
model, and saying so is a real finding that saves effort.

**Deliverable.** `analysis/build/backtest.py`, results table, `reports/P9_baselines.md`.

**Exit condition.** Every segment has a measured baseline error and a measured skill ceiling.

---

### Phase 10 — Error floor and feasibility

**Question.** Given what the data contains, can the 5% bar actually be reached?

This is the only early warning the project has. If it is skipped, the first honest read on
feasibility arrives at the end, when the effort has already been spent.

**Work.** Take the last 26 complete weeks. For each, reconstruct the view from a forecast origin four
weeks earlier and split actual revenue three ways:

| Bucket | Definition | What can forecast it |
|---|---|---|
| Established | Styles with at least 13 weeks of history at the origin | Ordinary methods. Use the Phase 9 baseline error |
| Cold-start | Styles with no history at the origin, arriving via a drop inside the window | Only borrowed release-aligned curves from Phase 5 |
| Event-driven | Revenue in weeks containing configured-sale or spike days | Only with a forward promotional calendar |

Then compute a best-case blended error: established revenue at its best measured baseline error,
cold-start at the borrowed-curve error from Phase 5, event weeks handled both with and without
advance knowledge. The blend is the **floor**, the best the data can support.

**The decision this produces.**

- Floor comfortably under 5%: proceed to modelling.
- Floor a little above 5%: the target is reachable only with the promotional calendar and the drop
  calendar populated four weeks forward. Name those as dependencies now rather than discovering them
  at the end.
- Floor far above 5%: style-level granularity is not the lever. Move to the fallback in Part 7.

**Deliverable.** `reports/P10_feasibility.md` with the floor, its three components, and a clear
recommendation.

**Exit condition.** This is the project's go/no-go. Do not begin model building until it is accepted.

---

### Phase 11 — Readout

**Question.** What does a merchandising audience need to see to act on this?

**Contents.**
- Concentration curve with the head/tail cut marked.
- One panel per segment: a representative style, actual weekly revenue, best baseline, and error.
- Release-aligned curves across recent drops, overlaid, showing how consistent the decay shape is.
- Continuation versus injection for several named styles. This is the chart that answers the demand
  question.
- Skill ranking table: segment, revenue share, best baseline, error, verdict.
- The error floor and its three components.
- Worked example. The README records that `Accolade 1/4 Zip Pullover` appears in three of the latest
  ten drops (SU26D5, FA26D2, FA26D3), which makes it a natural case study for a style that is
  repeatedly refreshed.

**Deliverable.** `reports/P11_readout.md` and the figures behind it.

---

## Part 6 — Blockers requiring a human answer

Each blocker names what is unknown, why it matters, what the code does in the meantime, and what
must be revisited if the answer differs from the default.

| ID | Question | Why it matters | Default until answered | Blocks |
|---|---|---|---|---|
| B1 | Is `revenue` gross, or net of returns and cancellations? | §3.1 describes it only as "Revenue for the row" and there is no returns column anywhere in the extract. If planning uses net and this forecasts gross, every number is measuring the wrong quantity | Proceed as gross, and label every output "gross demand revenue" | Interpretation of all phases. Nothing technical |
| B2 | Is the 5% bar an average across origins, or a ceiling on the worst window? | An average and a worst-case bar are different engineering problems | Report both. Headline is the average | Phase 0 sign-off |
| B3 | Does a promotional calendar exist, and is it populated four weeks forward? | A four-week forecast blind to a sale starting in week three cannot be accurate regardless of method. `config/sale_periods.csv` holds two windows described in the README as coming from a legacy notebook, across roughly 88 weeks | Use the two configured windows and the 32 spike days, and report the accuracy cost of not knowing more | Phase 8, Phase 10 |
| B4 | ISO weeks or a retail 4-5-4 calendar? | Changes every aggregate, and changes which weeks align year over year. The README records the fiscal calendar file as unavailable | ISO Monday weeks, implemented as a parameter | Phase 1 |
| B5 | What was the May 2026 surge? | It is flagged as a statistical spike and explicitly not assumed to be a promotion (README). The answer decides whether it is modelled or excluded | Treat as an unexplained spike and flag it | Phase 8 |
| B6 | Does history get restated when a new extract lands? | If past weeks change between extracts, every backtest result is invalid, because the model would be trained on numbers that did not exist at the time | Testable in code if a second extract is available: compare overlapping dates. Otherwise flag as unverified | Validity of Phase 9 and Phase 10 |
| B7 | How far forward is `Product Release Dates.xlsx` populated, and who owns it? | Forecasting future drops requires future release dates. The README notes that FA26D4 and FA26D5 tags already appeared in sales data before being valid, so tags precede calendar entries | Use the 103 validated drops as they stand | Live operation, not the EDA |
| B8 | Does the extract cover all sales channels? | There is no channel column in `inputs.csv` (§3.1), so this cannot be checked from the data | Treat as total demand across channels, and label it so | Interpretation |

**How the agent handles a blocker.** Implement the default, record it in `DECISIONS.md` with the
blocker ID, and flag it prominently at the top of the affected phase report. Do not stop work, and
do not quietly pick an answer without recording it.

---

## Part 7 — Fallback if the answer is no

If Phase 10 shows the floor well above 5%, the recommendation changes rather than the project failing:

1. Forecast at **segment level**, where individual style noise cancels out and accuracy is
   structurally higher.
2. Allocate the segment total down to styles using recent revenue shares, so planners still receive a
   style-level number, with its uncertainty stated honestly.
3. Model drops as **events** against the release calendar rather than as products with history.
4. Direct remaining effort at the promotional calendar, which Phase 8 will likely show to be the
   larger untapped lever.

This still delivers a usable style-level number and a clear account of what limits it.

---

## Part 8 — Risk register

| ID | Risk | Impact if it materialises | Response |
|---|---|---|---|
| R1 | History is restated between extracts | Every backtest result is invalid | Test it if a second extract exists. Otherwise carry as unverified and state it in the readout. See B6 |
| R2 | Revenue is gross while planning uses net | The forecast measures the wrong quantity | Resolve B1 before Phase 3 |
| R3 | Promotional calendar is incomplete and has no forward view | The 5% bar is unreachable regardless of method | Quantify the cost in Phase 8 and escalate as a dependency, not as a surprise |
| R4 | Under two years of history | Each calendar week is observed roughly 1.7 times, so per-style annual seasonality cannot be estimated. Anything claiming to learn it is fitting noise | Estimate seasonality only at aggregate level. State the limitation in the readout |
| R5 | Drop calendar not populated four weeks forward | Method works in backtest and fails in live use | Resolve B7 before any production commitment |
| R6 | Overfitting to roughly 88 weeks | Backtest looks strong, live performance does not | Many rolling origins, preference for simple methods, and the final 8 weeks held back untouched |
| R7 | Segment definitions drift between runs | stakeholders lose confidence in the output | Segments use only traits known in advance, and definitions are frozen after Phase 4 |
| R8 | Explainability traded away under accuracy pressure | The output is rejected by its users | Explainability is a hard requirement and is recorded in the measurement spec |
| R9 | Scope creep into colour and size | Timeline slips | Colour is limited to the Phase 6 decomposition. Size is absent from the fact table entirely |
| R10 | Nothing exists to compare against, so the error figure is argued over rather than accepted | The result stalls in review | Sign off the measurement spec before any number exists. Lead with skill against the project's own baselines |
| R11 | The real driver of error turns out not to be product mix | Effort spent on the wrong lever | Decompose the project's own error by week and by segment from the first backtest, so the driver surfaces as early as the data allows |

---

## Part 9 — Sequencing and checkpoints

| Phase | Output | Checkpoint |
|---|---|---|
| 0 | Measurement spec | Signed off before any number is produced |
| 1, 2 | `style_week.parquet`, integrity report | Reconciliation exact. Ground-truth figures confirmed |
| 3, 4 | Concentration curves, frozen segments | Segments reviewed by merchandising |
| 5, 6 | Drop mechanics, demand-trend answer | Business readout on "is demand declining" |
| 7, 8 | Units and price split, event quantification | Promotional calendar dependency escalated |
| 9, 10 | Baselines, skill ranking, error floor | **Go / no-go on the 5% target** |
| 11 | Readout | EDA accepted, modelling scope agreed |

Everything before Phase 10 gathers evidence. Everything after it is modelling that should not begin
until Phase 10 says it can succeed.

---

## Part 10 — First actions for the agent

1. Confirm the repository is present and `to_share/data/processed/` contains all seven files.
2. Create `analysis/` with the structure in section 2.4, plus an empty `DECISIONS.md`.
3. Verify the environment against `to_share/requirements.txt`. DuckDB and pyarrow are the only hard
   requirements for Phase 1.
4. Re-derive the Part 3 figures and report any mismatch before doing anything else.
5. Write `MEASUREMENT_SPEC.md` (Phase 0).
6. Build `style_week.parquet` (Phase 1) and prove the reconciliation.

Report after step 6 with the reconciliation result, the true style count, and the number of complete
weeks, before continuing to Phase 2.
