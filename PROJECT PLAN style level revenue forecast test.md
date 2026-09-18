# Project Plan — Style-Level Weekly Revenue Forecast

**Version:** 3.0 · **Date:** 2026-09-18
**Owner:** Deepan Thulasi
**Repository:** https://github.com/AloDeepan/Product_level_forecast.git
**Data references:** `DATA_MODEL.md` (cited below as §N) and `to_share/README.md`

---

## 1. Summary

We want to know whether weekly revenue can be forecast four weeks ahead for each style, accurately
enough for stakeholders to plan on, using a method whose logic they can follow and question.

A **style** is a product name with the colour removed. `Grounded No-Slip Mat Towel - Gravel` and
`Grounded No-Slip Mat Towel - Jungle` are two colours of one style.

This plan covers the analysis phase. It builds the data, measures what the data can support, and
ends with a go/no-go on whether to build a model. Every phase produces a number and a decision.

Three initial checks on the committed data (Section 3.3) shape the order of work:

- Revenue is concentrated in a small number of event weeks. 14 of the 88 complete weeks carry 46%
  of revenue. Event handling is therefore the first analysis, not the last.
- Drops are new colours of existing styles, not new styles. Cold-start at style level is small.
  The drop question becomes "how much does a new colour add, and when", not "what do we do with
  styles that have no history".
- Two thirds of recent revenue comes from styles that were already selling when the data starts.
  Their age is unknown, so no method in this plan depends on age.

---

## 2. Objective and scope

### 2.1 Objective

Measure, with evidence, how much revenue can be forecast at style level, for which kinds of style,
at what error, and whether the 5% bar on total revenue is reachable four weeks ahead.

### 2.2 Fixed decisions

| Item | Decision | Reason |
|---|---|---|
| Forecast unit | Style (`product_name`, colours pooled) | The level stakeholders plan at. Colour is a later question |
| Horizon | 4 weeks ahead | Set by the business |
| Grain | Weekly | Daily revenue is drop-driven and volatile. Weekly is the stable starting point. Daily is a later phase |
| Measure | Revenue | Set by the business |
| Accuracy bar | Under 5% error on total revenue, 4 weeks ahead, averaged across forecast origins | Set by the business. Section 4.3 defines the calculation |
| Method | Explainable. Every forecast splits into named parts that add up | A number nobody can question will not be used |
| Reference point | The naive baselines built in Phase 9 | No forecast exists at this grain today |

### 2.3 Out of scope

- Colour, size and SKU forecasts. Size is not in the fact table (§4.2).
- Buy quantity, depletion and inventory. The README places these outside the pipeline.
- Changes to the source extract, the dashboard, or the builder under `to_share/`.
- Daily-grain forecasting. It follows this phase if the weekly result supports it.

### 2.4 Definition of done

A written readout (Phase 11) that states: revenue forecastable at style level, by segment, with its
measured error; the best-case error against the 5% bar; and a recommendation to proceed, proceed at
segment level, or stop. Plus the code and tables that produced it. Model building starts after the
readout is accepted, not before.

---

## 3. Data

### 3.1 Files used

All inputs are the seven processed files in `to_share/data/processed/`. They are committed to the
repository and are sufficient for every phase.

| File | Role |
|---|---|
| `product_daily.parquet` | Fact table. Date × product-colour × status × family × taxonomy. Additive (§4.2) |
| `product_dimension.parquet` | One row per product-colour, with `product_name` (§4.3) |
| `product_drop_membership.parquet` | Product-colour to drop bridge. Non-additive across drops (§4.4) |
| `drop_calendar.parquet` | 103 validated drops with anchor dates (§4.5) |
| `daily_context.parquet` | Daily totals, spike flag, sale flag, incomplete-day flag (§4.6) |
| `excluded_family_tags.parquet` | Audit of family tags that were not validated (§4.7) |
| `data_quality.json` | Build audit and reconciliation totals (§4.8) |

The raw files (`inputs.csv`, `Product Release Dates.xlsx`, `config/sale_periods.csv`) are not in
the repository. No phase needs them. If a step appears to need them, the step has been misread and
should be raised.

### 3.2 Reference figures

Verified against the committed data on 2026-09-18. Phase 2 re-derives every one of them.

| Fact | Value | Source |
|---|---|---|
| Fact rows | 1,379,103 | §4.2 |
| Total revenue | $2,831,081,580.32 | §2 |
| Total units | 31,761,946 | §2 |
| Date range | 2025-01-01 to 2026-09-15, 623 days | §3.1 |
| Last complete day | 2026-09-14. 2026-09-15 is flagged incomplete | §4.6 |
| Complete ISO weeks | 88, from 2025-01-06 to 2026-09-13 | computed |
| Product-colour keys | 7,117 | §4.3 |
| Styles (distinct `product_name`) | 1,776; 1,761 after normalisation | computed |
| Styles with revenue in the last 13 weeks | 1,279 | computed |
| Validated drops | 103, FA21D1 to FA26D3; 46 anchored inside the sales window | §4.5, computed |
| Drop bridge | 4,114 rows, 3,933 products, 100 drops | §4.4 |
| Days between drops since 2025 | median 14, range 6 to 28 | computed |
| Spike days | 32 | §4.6 |
| Configured sale days | 68, from two windows | §4.6 |
| Spike or sale days | 76 (24 spike days fall inside sale windows) | computed |
| Median daily revenue | $3.05M | computed |
| Largest day | 2026-05-02, $90.5M | computed |

Lifecycle status (§5.3), revenue: Core $863.1M · Seasonal $803.7M · Carryover $692.8M ·
FPPhaseOut $444.1M · Markdown $11.2M · NOT-MAPPED $9.8M · BeautyWellness $6.4M.

Business line (§6.1), revenue: Women $2,039.7M · Men $545.7M · Accessories $238.5M · Beauty $5.8M ·
Wellness $0.71M · Unknown $0.59M · Books $5,950.66 · Internal $72.00.

Attribution buckets (§5.6): Core $863.1M · Eligible drop $1,337.1M · Rest $630.9M. They sum to the
total. Core is tested first, so a Core product inside a drop counts as Core.

### 3.3 Initial checks and what they change

Run on 2026-09-18 against the committed data. Each is repeated properly in its phase. They are
here because they change the order and weight of the work.

**Event weeks carry the revenue.** Tag a complete ISO week as an event week if any day in it is a
spike day or a configured sale day. 14 of 88 weeks qualify and carry 46.4% of revenue. The 32 spike
days alone (5% of days) carry 36.2%. A four-week forecast window that contains one of these weeks
will have its error set by the event, not by style mix. Phase 3 handles events before anything
else is segmented.

**The April/May window repeated.** 2025-04-26 to 05-02 is a configured sale with spike days.
2026-05-01 to 05-08 is a spike run with no configured sale. Same slot, one week later. The October
to December 2025 windows have no 2026 counterpart in the data yet. This is the only forward-looking
event signal available, and Phase 3 tests it.

**Drops bring new colours, not new styles.** For the 45 validated drops anchored after the first
complete week, revenue in the eight weeks after the anchor came to $619.2M from styles already
selling before the anchor and $0.7M from styles first seen at or after it. For drops in the last
26 weeks, the four-week split is $116.6M against under $0.1M. Style-level cold-start is small.
Phase 6 confirms this and then measures the thing that matters: how much a new colour adds.

**Most revenue has no known start date.** 922 of 1,776 styles were selling in the first complete
week or earlier. Their true start is before the data. They carry 67.6% of revenue in the last 26
weeks. Age is recorded as unknown for them and no method depends on it.

**The tail is small.** Of 1,334 styles active in the last 26 weeks, 330 had fewer than 13 active
weeks. Together they carry 1.5% of that period's revenue. Grouping them costs almost nothing.

### 3.4 Data issues to handle

From §8 of the data model. Each has a task in Phase 2.

| Issue | Detail | Source |
|---|---|---|
| Title fragmentation | One title of 7,117 splits on the first `" - "` into two keys | §8.2 |
| Non-colour values | 27 dimension rows hold a quantity where the colour should be (`8 oz`, `60 Pack`) | §8.1 |
| Apparent duplicates | 2,578 groups, $3,192,610.49, kept in the fact by design | §8.10 |
| Mixed taxonomy | 380 products span business lines ($341.8M); 98 category, 102 subcategory, 79 item class | §8.3 |
| Unclassified block | The same $67,936,207.63 has no category, subcategory or item class | §8.5 |
| Censored dates | `first_seen_date = 2025-01-01` means already selling; `last_seen_date = 2026-09-15` means still selling | §8.7 |
| Calendar ordering | `drop_number` is not chronological everywhere. Always order by `anchor_date` | §8.6 |
| Missing early access | 13 drops have no `early_access_date`, all anchored before 2025. The data model says 7; record the count | §4.5, computed |
| Price column | Not usable. Compute realised price as revenue ÷ units | §3.1, README |
| Negative revenue | 4 fact rows, netting to $0 | computed |

---

## 4. Definitions

Fix these before any code runs. Every number downstream depends on them.

### 4.1 Style key

```
style_name_normalised = trim(regexp_replace(lower(product_name), '[^a-z0-9]+', ' ', 'g'))
style_key             = 'style:' || md5(style_name_normalised)
```

`product_name` comes from `product_dimension`. Join the fact to the dimension on `product_key` to
reach it. Do not use `product_key` as a style key: it hashes name and colour together (§5.1).

### 4.2 Week

ISO weeks, Monday start, labelled by `week_start`. Implement as a parameter so a retail 4-5-4
calendar can be swapped in if one is supplied. A week is complete only if all seven days fall
inside 2025-01-01 to 2026-09-14. This gives 88 complete weeks, numbered 1 to 88.

### 4.3 Error measures

An **origin** is a week *t* from which the forecast is made. The forecast covers weeks *t+1* to
*t+4*.

**Headline — total revenue error.**

```
F_t   = sum of forecast revenue, all styles, weeks t+1..t+4
A_t   = sum of actual revenue,   all styles, weeks t+1..t+4
APE_t = |F_t - A_t| / A_t
Headline = mean of APE_t across origins, as a percentage
```

This is the number compared to 5%. Report the worst origin alongside it.

**Style-level error, revenue weighted.**

```
WAPE_t = sum over styles and weeks of |forecast - actual|
       / sum over styles and weeks of actual
```

Weighted, because many style-weeks are zero (a percentage error is undefined there) and because
an unweighted average lets a hundred small styles outvote the ones that carry the revenue.

**Skill against baseline.**

```
Skill = 1 - (error of method / error of best naive baseline)
```

Positive skill means the method earned its complexity. Zero or negative means the simple rule was
as good. That is a valid result.

**Bias.**

```
Bias_t = (F_t - A_t) / A_t      -- signed
```

A forecast that is 4% off and always low is a different planning problem from one that is 4% off
in both directions.

### 4.4 Backtest protocol

Rolling origin, expanding window. Stand at week *t*. Use only data up to and including *t*.
Forecast *t+1* to *t+4*. Step forward one week. Repeat.

- Minimum training window: 26 weeks.
- Holdout: weeks 81 to 88. Not read by any method until one is selected.
- Rolling origins: *t* = 26 to 76, giving **51 origins**. Every origin's four-week window ends at
  or before week 80.
- Same-week-last-year is available for origins 52 to 76 only: **25 origins**, one observation
  per calendar week.

Every feature is computed as of the origin: segment, volatility, age, taxonomy, rolling statistics.
Computing a feature once over the full history leaks the future into the past.

### 4.5 Segment

A group of styles built only from traits known before the forecast window opens. Growth-shape
clustering is not allowed: it groups on the history being predicted, it moves between runs, and a
stakeholder cannot apply the label to a new style. Permitted traits are listed in Phase 5.

### 4.6 Event week

A complete week containing at least one day flagged `is_volume_spike` or `is_configured_sale` in
`daily_context`. Event revenue stays in the target. It is real revenue and the business plans on
the total.

### 4.7 Explainability

Every forecast row carries four columns that add up to the forecast:

| Column | Meaning |
|---|---|
| `base` | Level the style is expected to hold with no other effects |
| `trend` | Change from the recent slope |
| `event_uplift` | Change from an event week |
| `drop_injection` | Change from a new colour arriving |

A script asserts `base + trend + event_uplift + drop_injection = forecast` for every style-week.
For naive baselines the last two columns are zero. A method whose output cannot be split this way
is not adopted.

---

## 5. Working rules

1. **Do not modify anything under `to_share/`.** New work lives in `analysis/` at the repository
   root. The dashboard and its builder keep working untouched.
2. **Do not load the raw CSV into pandas** if it ever becomes available. The project convention is
   DuckDB to Parquet (§1, Invariant 4).
3. **Do not sample.** In a 1% sample, active-day counts capture a median 2.5% of true active days
   and 33% of product-colour pairs disappear (§8.9). Every number here is a count, a date or a
   coverage measure at some point. Run on the full tables.
4. **Reconcile before analysing.** Any aggregate built from `product_daily` must total
   $2,831,081,580.32 and 31,761,946 units before any filter is applied.
5. **No leakage.** A forecast at week *t* reads only data with `week_start <= t`, including every
   derived feature.
6. **Determinism.** Fix seeds. Pin versions to `to_share/requirements.txt`. Write an audit JSON for
   every generated table: row count, totals, git commit, parameters.
7. **Log every judgement call** in `analysis/DECISIONS.md`: date, choice, alternative rejected,
   revenue affected.
8. **Run the existing tests at the end.** `cd to_share && PYTHONPATH=. python -m unittest
   tests.test_data_contract`. All 8 must pass.

Output layout:

```
analysis/
├── DECISIONS.md            # running log of judgement calls
├── MEASUREMENT_SPEC.md     # Phase 0 output
├── build/                  # scripts that produce data
├── data/                   # generated parquet + audit json
├── reports/                # P<n>_<topic>.md, one per phase
└── figures/
```

Each phase report opens with the question it answers and closes with the decision it unlocks and
any change it makes to this plan.

---

## 6. Phases

Phases run in order. Phase 10 is the go/no-go.

### Phase 0 — Measurement specification

**Goal.** Agree how success is judged before any number exists.

**Tasks.**
1. Write `analysis/MEASUREMENT_SPEC.md` with the four formulas from 4.3 and a worked example on
   invented numbers.
2. Write the backtest protocol from 4.4 with the origin count and the holdout weeks.
3. Write the week definition from 4.2.
4. State how event weeks are treated: inside the headline, and reported separately as well.
5. State the explainability rule from 4.7.
6. Share with stakeholders.

**Output.** `MEASUREMENT_SPEC.md`.

**Done when.** The spec has been shared. Phase 1 can start in parallel. No accuracy figure is
shown to anyone until the spec is agreed.

### Phase 1 — Build the style-week base table

**Goal.** One table every later phase reads.

**Inputs.** All five parquet tables except `excluded_family_tags`.

**Target.** `analysis/data/style_week.parquet`, one row per `style_key` × `week_start`.

| Column | Definition |
|---|---|
| `style_key`, `style_name` | Section 4.1 |
| `week_start` | Section 4.2 |
| `revenue`, `units` | Sum of fact revenue and units |
| `realised_price` | `revenue / units`; null when units is zero |
| `active_colours` | Distinct `product_key` with revenue that week |
| `dominant_status` | `planning_status` with the most revenue that week |
| `status_mix` | Every status present, with revenue share |
| `dominant_family` | `assigned_family` with the most revenue that week, else null |
| `weeks_since_anchor` | Weeks since the most recent drop `anchor_date` on or before the week's last day, across all the style's colours in `product_drop_membership`. Null if none |
| `business_line`, `category`, `subcategory`, `item_class` | Revenue-dominant value over all weeks up to and including this one. Cumulative, so it is as-of by construction. `Mixed / multiple` where no value holds a majority |
| `first_active_week` | First week with revenue |
| `age_weeks` | Weeks since `first_active_week`; null where censored |
| `age_is_censored` | True if the style has revenue in week 1 |
| `sale_days_in_week`, `spike_days_in_week` | Counts from `daily_context` |
| `is_event_week` | Section 4.6 |
| `source_rows` | Fact rows collapsed into this row |

**Tasks.**
1. Join the fact to the dimension on `product_key`. Build the style key.
2. Aggregate to style × ISO week. Cast `daily_context.order_date` from TIMESTAMP to DATE on
   join (§4.6).
3. **Dense grid.** Give every style a row for every week from its first active week to week 88,
   with zero revenue where there were no sales. Extend to the end, not to the style's last sale.
   A style that stops selling must exist as zeros so that any method still forecasting it is
   scored against zero.
4. Keep the full status and family mix in audit columns. Pick the dominant for modelling.
5. Set `age_is_censored` and null age for styles selling in week 1. Do not derive age from
   `first_seen_date` (§8.7).
6. Reconcile the full table, including partial weeks, to $2,831,081,580.32 and 31,761,946 units.
   Then drop incomplete weeks and record how much revenue that removed.

**Output.** `style_week.parquet`, its audit JSON, `reports/P1_base_table.md`.

**Done when.** Reconciliation matches exactly. Revenue removed by the complete-week filter is
recorded. Style count and complete-week count are reported.

### Phase 2 — Integrity checks

**Goal.** Find what will distort a forecast if left alone. Each check produces a number and a
recorded decision, not a silent fix.

| # | Check | Compute | Decide |
|---|---|---|---|
| 2.1 | Reference figures | Re-derive every figure in 3.2 | Whether the data has changed since this plan |
| 2.2 | Style count | Distinct styles; styles with revenue in the last 13 weeks | Scope. Reference: 1,776 and 1,279 |
| 2.3 | Title fragmentation | Whether the one split title (§8.2) survives pooling to style | Fix or record as immaterial |
| 2.4 | Non-colour values | Whether the 27 rows (§8.1) collapse into their style | Fix or record |
| 2.5 | Duplicates | Duplicate revenue as a share of each week | Net out any week above 1% and log it |
| 2.6 | Mixed taxonomy | Whether pooling colour reduces or increases conflicts (§8.3) | Whether taxonomy can be a segment trait |
| 2.7 | Unclassified block | Styles carrying the $67.9M with no taxonomy (§8.5) | Whether they form their own segment |
| 2.8 | Sparsity | Share of zero weeks per style, by revenue band | Which styles are grouped (Risk check 8) |
| 2.9 | Series length | Usable weeks per style, censoring-aware | How many styles can support a time-series method |
| 2.10 | Censored revenue | Revenue share of censored styles in the last 26 weeks. Reference: 67.6% | Confirms age is not usable as a feature |
| 2.11 | Excluded tags | Revenue associated with `NO_FAM` ($346.3M) and season rollups ($1,461.4M). Not additive (§4.7) | Whether drop activity is being missed by the validation rule (§5.4) |
| 2.12 | Upcoming tags | The 4 canonical-looking tags absent from the calendar (§4.7), including `fa26d4` and `fa26d5` first seen 2026-08-24 | Note as early sales of upcoming drops. Product-level membership is not available for them |
| 2.13 | Early access | Count of drops with no `early_access_date`. Reference: 13, all before 2025 | Record the count |

**Output.** `reports/P2_integrity.md`. Every decision in `DECISIONS.md`.

**Done when.** No unexplained mismatch against 3.2. Any mismatch is raised before Phase 3.

### Phase 3 — Events

**Goal.** Measure how much of the forecast error is set by event weeks, and what can be known
about events in advance from the data.

**Tasks.**
1. Tag event weeks (4.6). Report their count and revenue share. Reference: 14 of 88, 46.4%.
2. List every event window with dates, days, revenue, and peak `revenue_index`.
3. Year-over-year repeat. For each 2025 event window, check whether a window landed in the same
   ISO week in 2026, allowing one week either side. Reference: April/May repeated one week later;
   October to December have no 2026 data yet.
4. Undocumented events. Compute weekly realised price at total level (revenue ÷ units). List
   weeks where it sits more than 10% below the trailing 8-week median and the week is not tagged.
   Report them as candidate events. Do not change the tagging rule.
5. Set the forward event assumption: the forecast treats a week as an event week if the same ISO
   week (±1) was an event week one year earlier. Record this in `DECISIONS.md`.
6. Prepare the split for Phase 9: origins whose window contains an event week versus origins whose
   window does not.

**Output.** `reports/P3_events.md`, event calendar table.

**Done when.** Event revenue share, the repeat test and the forward assumption are written down.

### Phase 4 — Revenue concentration

**Goal.** Find how much of the problem is large, and how stable the large part is.

**Tasks.**
1. Rank styles by revenue over the last 13 weeks and the last 52 weeks.
2. Cumulative share curve. Count styles needed for 50%, 80% and 95% of revenue.
3. Stability: of styles in the top 80% in one quarter, share still there the next quarter.
4. Repeat within Women, Men and Accessories.
5. Decide whether Beauty, Wellness, Unknown, Books and Internal (under $7M combined) stay in scope.

**Output.** `reports/P4_concentration.md`, concentration curve.

**Done when.** A head/tail cut is stated as a style count and a revenue share.

### Phase 5 — Segmentation

**Goal.** Group styles that behave alike, in terms stakeholders would recognise.

**Permitted traits.** All computable as of an origin.

| Trait | Source |
|---|---|
| Revenue size band | Phase 4 |
| Week-to-week volatility, trailing 13 weeks | Phase 1 |
| Usable weeks of history, censoring-aware | Phase 1 |
| Lifecycle status mix and recent status changes | §5.3, Phase 1 |
| Drop-linked or not; weeks since last anchor | §4.4, §4.5 |
| Business line and category where not `Mixed / multiple` | Phase 2.6 |
| Share of zero weeks | Phase 2.8 |

**Tasks.**
1. Build the lifecycle split first. It separates three different problems: always-on Core with
   long history; Seasonal and drop-linked styles refreshed by colour; FPPhaseOut and Markdown
   styles declining toward zero.
2. Track status changes. `planning_status` is recorded per row per date, so a style moving
   Core → Carryover → FPPhaseOut is visible before its revenue finishes falling. That is a
   forward signal and an explanation stakeholders accept.
3. Add the other traits one at a time. Keep a trait only if it separates baseline error in
   Phase 9.
4. Stability test (Risk check 7): build segments at two origins 13 weeks apart. If more than 10%
   of revenue changes segment, remove the trait causing it and rebuild.
5. Freeze the definitions and write a plain-language description of each segment.

**Output.** `reports/P5_segments.md`: definitions, style counts, revenue shares, descriptions.

**Done when.** Definitions are frozen and shared with stakeholders before Phase 9.

### Phase 6 — Drop mechanics

**Goal.** Measure what a drop does to a style's revenue: how much a new colour adds, for how long,
and how predictable that is.

**Tasks.**
1. Confirm composition. For every validated drop anchored inside the sales window (46), join
   `product_drop_membership` to `drop_calendar` and split post-anchor revenue into styles already
   selling before the anchor and styles first seen at or after it. Report in revenue. Reference:
   $619.2M against $0.7M over eight weeks.
2. Release-aligned curves. For each drop, revenue by week since anchor as a share of the first
   eight weeks. Report the min, median and max share for weeks 1 to 8 across drops.
3. Week-one signal. For each drop, the ratio of weeks 2 to 5 revenue to week 1 revenue. Report
   the spread. A tight spread means the first week tells us most of what follows.
4. Injection size. For each style that receives a new colour, revenue in the four weeks after the
   anchor against the four weeks before. Report the distribution by segment.
5. Cadence. Gaps between consecutive `anchor_date` values since 2025. Reference: median 14 days,
   range 6 to 28. Set 14 days as the assumed gap to the next drop when forecasting forward.
6. Order every drop analysis by `anchor_date`, never by `drop_number` (§8.6). Drops with no
   `early_access_date` use `launch_date`; all 13 are before the sales window.

**Output.** `reports/P6_drop_mechanics.md`, release-aligned curve figure.

**Done when.** The composition split, the curve shape spread, the week-one ratio and the injection
distribution are all reported in revenue terms.

### Phase 7 — Demand trend

**Goal.** Answer, net of colour refresh, whether demand for a style is falling.

**Why not a simple trend line.** Summing colours into a style mixes two things: demand for the
style, and the arrival of new colours. A style with flat demand and no new colours looks like it
is dying. A style in decline with a fresh colour looks healthy.

**Tasks.**
1. Build `analysis/data/style_week_injection.parquet`, keyed on `style_key` × `week_start`, with:
   - `injection_revenue`: revenue from colours whose first sale, or whose drop anchor, falls in
     the trailing N weeks. N is a parameter, default 8.
   - `continuation_revenue`: everything else.
   Colours selling in week 1 are censored and count as continuation, with a flag.
2. Measure trend on continuation revenue, by segment.
3. Separate fewer styles selling from each style selling less: active styles per week against
   average revenue per active style.
4. Check the style-level story against the total revenue line from `daily_context`.
5. State the answer in one sentence, by segment.

**Output.** `reports/P7_demand_trend.md`.

**Done when.** The decline question is answered separately for continuation and injection, by
segment.

### Phase 8 — Units and price

**Goal.** Decide whether to forecast revenue directly or as units × realised price.

**Tasks.**
1. Compute realised price as revenue ÷ units. Do not use the source `price` column (§3.1, README).
2. Chart realised price per style over time. Mark step changes.
3. Test whether `Markdown` and `FPPhaseOut` status changes line up with price steps. If they do,
   status is a forward markdown signal.
4. Compare volatility of units against volatility of price, by segment.
5. Recommend one structure. "Nine percent fewer units at four percent lower price" is a sentence a
   stakeholder can argue with. A single revenue number is not.

**Output.** `reports/P8_units_price.md`.

**Done when.** A recommendation with evidence, by segment.

### Phase 9 — Naive baselines and backtest harness

**Goal.** Measure which segments are predictable with simple rules, and set the bar any later
method has to beat.

**Baselines.**

| Name | Rule |
|---|---|
| Last week | Next four weeks equal the most recent week |
| Trailing 4-week mean | Flat continuation of the recent average |
| Trailing mean with trend | Recent average plus recent slope, slope capped |
| Seasonal naive | Same week one year earlier. Origins 52 to 76 only. Labelled "25 origins, one year". Not used in the skill ranking |
| Segment share | Forecast the segment or total, split by each style's recent revenue share |
| Zero | Predict zero. The right baseline for phase-out styles |

**Tasks.**
1. Build `analysis/build/backtest.py` implementing 4.4. Every feature as of the origin.
2. Run every baseline on the 51 rolling origins. Report all four measures from 4.3 per origin and
   averaged.
3. Break results down by segment, by revenue band, by weeks of history, and by event versus
   non-event windows (Phase 3 task 6).
4. Produce the skill table: segment, revenue share, best baseline, its error, verdict.
5. Emit the four explainability columns for every baseline forecast and run the sum check.

**Output.** `backtest.py`, results table, `reports/P9_baselines.md`.

**Done when.** Every segment has a measured baseline error. Event and non-event windows are
reported separately.

### Phase 10 — Feasibility

**Goal.** Decide whether 5% is reachable before any modelling effort is spent.

**Tasks.**
1. Take weeks 55 to 80, the 26 complete weeks before the holdout.
2. For each four-week window in that range, split actual revenue three ways:

| Bucket | Definition | Error to apply |
|---|---|---|
| Established, non-event | Styles with 13+ weeks of history, in weeks that are not event weeks | Best baseline error from Phase 9 |
| Young | Styles with fewer than 13 weeks of history at the origin | Error of the segment-share baseline, or the injection estimate from Phase 6 |
| Event | Revenue in event weeks | Best baseline error on event windows, with and without the forward event assumption from Phase 3 |

3. Compute the best-case blended error: each bucket's revenue share × its error. Report it with
   and without the event assumption.
4. Decide:
   - Under 5%: proceed to modelling on the segments where skill is positive.
   - Over 5%: name the bucket that drives the gap. Move to the fallback in Section 9.

**Output.** `reports/P10_feasibility.md` with the three buckets, the blended error, and the
recommendation.

**Done when.** The recommendation is accepted. No model building before this.

### Phase 11 — Readout

**Goal.** Give stakeholders what they need to act.

**Contents.**
- Concentration curve with the head/tail cut.
- Event calendar and its revenue share.
- One panel per segment: a representative style, actual weekly revenue, best baseline, error.
- Release-aligned curves across recent drops, overlaid.
- Continuation versus injection for several named styles.
- Skill table.
- The feasibility buckets and blended error.
- Worked example: `Accolade 1/4 Zip Pullover`, which appears in three of the latest ten drops
  (SU26D5, FA26D2, FA26D3 per the README), as the case of a style refreshed repeatedly.

**Output.** `reports/P11_readout.md` and figures.

---

## 7. Assumptions and defaults

Each is implemented as stated, recorded in `DECISIONS.md`, and labelled on the affected outputs.
Any of them can be changed later without redoing the analysis, except A4.

| ID | Assumption | Basis | Where it shows |
|---|---|---|---|
| A1 | Revenue is gross demand revenue | §3.1 describes it as "Revenue for the row". There is no returns column | Every output labelled "gross demand revenue" |
| A2 | The 5% bar is the average across origins | Standard reading. The worst origin is reported next to it | Headline table |
| A3 | Event weeks come from the two configured windows and the 32 spike days. Forward event weeks are assumed to repeat last year's, ±1 week | §4.6, Phase 3 task 3 | Phase 3, Phase 9, Phase 10 |
| A4 | ISO Monday weeks | No fiscal calendar in the repo. Implemented as a parameter | Every aggregate |
| A5 | The May 2026 surge is an event week | It lines up with the 2025 late-April sale window, one week later | Phase 3 |
| A6 | History is not restated between extracts | One extract only. If a second arrives, compare overlapping dates before use | Backtest validity |
| A7 | Drops continue at a 14-day cadence | Median gap since 2025 is 14 days. The calendar runs to FA26D3 | Phase 6, Phase 10 |
| A8 | The extract is total demand across channels | No channel column (§3.1) | Output labels |

---

## 8. Risk checks

Run these as tasks in the phase named. Each has a measurement and a rule for what happens when the
measurement fails.

**RC1 — Event weeks (Phase 3, Phase 9).** Tag event weeks. Split origins by whether their window
contains one. Report headline error for each group. If non-event windows are under 5% and event
windows are over 5%, state in the readout that 5% depends on the forward event assumption in A3,
and report the error with and without it.

**RC2 — Event repeat (Phase 3).** For each 2025 event window, check for a 2026 window in the same
ISO week ±1. Record matches and misses. Only the April/May window can be tested now. October to
December get their first test when 2026 data arrives.

**RC3 — Drop timing (Phase 6, Phase 9).** Assume a 14-day gap. Flag backtest windows where the
real next drop landed more than 7 days from the assumed date. Report error for flagged and
unflagged windows separately.

**RC4 — Unknown start dates (Phase 1, Phase 2).** Set `age_is_censored` for styles selling in
week 1. Report their revenue share. Reference: 922 styles, 67.6% of recent revenue. Score any
method that uses age on the uncensored styles only.

**RC5 — Seasonal baseline (Phase 9).** Run same-week-last-year for origins 52 to 76 only. Label it
"25 origins, one year". Exclude it from the skill ranking.

**RC6 — Holdout (Phase 9, Phase 10).** Hold back weeks 81 to 88. After a method is chosen, score it
once on the holdout. If holdout error is more than 1.5 percentage points worse than the rolling
error, reject the method and return to the best baseline.

**RC7 — Segment stability (Phase 5).** Build segments at two origins 13 weeks apart. If more than
10% of revenue changes segment, remove the trait causing the movement and rebuild. Repeat until
under 10%. Then freeze.

**RC8 — Tail styles (Phase 2, Phase 9).** At each origin, count zero weeks in each style's trailing
26. If more than 13, forecast the style inside its segment group, not on its own. Report the
revenue moved. Reference: 330 styles, 1.5% of recent revenue.

**RC9 — Duplicates (Phase 2).** Compute the $3.19M duplicate revenue as a share of each week. Net
it out of any week above 1% and log the amount.

**RC10 — Skill gate (Phase 9, Phase 10).** For every method, compute skill against the best naive
baseline on the rolling origins and on the holdout. Adopt only if both are above zero. Otherwise
the baseline is the deliverable.

**RC11 — Explainability gate (Phase 9 onward).** Every forecast carries `base`, `trend`,
`event_uplift`, `drop_injection`. A script asserts they sum to the forecast for every style-week.
The build fails if they do not.

---

## 9. Fallback plan

If Phase 10 puts the blended error above 5%:

1. Forecast at segment level, where individual style noise cancels.
2. Allocate each segment total to styles by recent revenue share, so stakeholders still receive a
   style-level number, with its error stated.
3. Model drops as events on the release calendar, using the Phase 6 curves, rather than as
   products with history.
4. Report the event-week error separately, with the A3 assumption and without it, so the cost of
   not knowing events in advance is visible.

This still delivers a style-level number and a clear statement of what limits it.

---

## 10. Checkpoints

| Phase | Output | Checkpoint |
|---|---|---|
| 0 | Measurement spec | Shared with stakeholders before any number is shown |
| 1, 2 | `style_week.parquet`, integrity report | Reconciliation exact. Reference figures confirmed |
| 3 | Event calendar, forward event assumption | Event share and repeat test recorded |
| 4, 5 | Concentration curve, frozen segments | Segments shared with stakeholders |
| 6, 7 | Drop mechanics, demand-trend answer | Readout on "is demand falling" |
| 8 | Units and price recommendation | Model structure chosen |
| 9, 10 | Baselines, skill table, feasibility | **Go / no-go on 5%** |
| 11 | Readout | Analysis accepted. Modelling scope agreed |

---

## 11. First tasks

1. Confirm `to_share/data/processed/` holds all seven files.
2. Create `analysis/` with the layout in Section 5 and an empty `DECISIONS.md`.
3. Install from `to_share/requirements.txt`. DuckDB and pyarrow are the only hard requirements
   for Phase 1.
4. Re-derive every figure in 3.2 and report any mismatch before going further.
5. Write `MEASUREMENT_SPEC.md`.
6. Build `style_week.parquet` and prove the reconciliation.

Report after step 6 with the reconciliation result, the style count, and the complete-week count,
then continue to Phase 2.
