# Style-Level Revenue Forecast — EDA & Feasibility Design

**Version:** 1.0 · **Date:** 2026-09-18
**Owner:** Deepan Thulasi
**Repo:** https://github.com/AloDeepan/Product_level_forecast.git
**Data reference:** `DATA_MODEL.md`, `to_share/README.md` (sections cited inline as §)

---

## 0. Purpose of this document

This is the plan for the exploratory work that comes **before** any model is built. Its job is to
answer one question with evidence rather than opinion:

> Can a style-level revenue forecast, four weeks ahead, at weekly grain, reduce the current
> 8% forecast error to under 5%, using a method a merchant can understand?

Every step below is written as a question, the way to answer it, the decision it unlocks, and the
point at which we stop digging. EDA without stop rules runs forever, and this project has an
audience waiting on an answer.

**No web search or outside research was used.** All factual statements about the data come from
`DATA_MODEL.md` and `to_share/README.md` in the repo above. There are no external sources to cite.

---

## 1. What is already decided

| Item | Decision |
|---|---|
| Forecast horizon | 4 weeks ahead |
| Time grain | Weekly to start. Daily is the later ambition |
| Measure | Revenue |
| Forecast unit | **Style** = `product_name` (title with the colour stripped). Colour is pooled |
| Accuracy bar | Beat the existing 8% error. Target under 5% |
| Method constraint | Explainable. No black box. A merchant must be able to see why the number moved |
| Colour | Deliberately parked. Revisited only after the style question is settled |
| Existing benchmark | An org-level forecast exists. No product-level forecast exists today |

---

## 2. Assumptions (stated explicitly, each one falsifiable)

1. **The 8% figure is an org-level, not product-level, error.** The purpose of going to style level
   is to improve that same org-level number by building it up from parts. So the headline scorecard
   stays at the org level, and style-level accuracy is the means, not the goal.
2. **The 8% is an average absolute percentage miss.** The exact definition (which horizon, which
   weeks, absolute or signed) is not in the repo. Step 0 below exists to pin it down. Until it is
   pinned down, "under 5%" cannot be measured, only claimed.
3. **`revenue` is gross demand revenue, not net of returns or cancellations.** The data dictionary
   (§3.1) calls it "Revenue for the row" with no returns column anywhere in the extract. If the
   business plans on net, every number in this project is measuring the wrong thing. This is
   assumption number one to confirm with the business.
4. **The extract covers all sales channels.** There is no channel column in `inputs.csv` (§3.1),
   so this cannot be checked from the data.
5. **History is 2025-01-01 to 2026-09-14.** 2026-09-15 exists but is flagged incomplete (§4.6, §8.7).
   That is 623 days, roughly **89 usable weeks**.
6. **Sales history does not get restated between extracts.** If yesterday's numbers change when a
   new extract lands, every backtest below is invalid. Unverified. See Risk R1.
7. **A style is stable over time.** A product name does not get re-merchandised into a different
   name mid-life.
8. **`config/sale_periods.csv` is incomplete.** It holds two windows, described in the README as
   coming from a legacy notebook. Two promotional windows across 89 weeks is almost certainly not
   the real promo calendar.

---

## 3. The three hard constraints this project runs into

These are not problems to solve. They are the shape of the board. Every design choice below follows
from them.

**Constraint A — under two years of history.** 89 weeks means each calendar week of the year is
observed roughly **1.7 times**. Annual seasonality cannot be estimated for an individual style. It
can only be estimated at a level with enough volume to be stable (business line, category, or
total), and even there it rests on one and a bit observations per week. Any method that claims to
learn per-style seasonality from this data is fitting noise.

**Constraint B — drops every two weeks inside a four-week window.** With a two-week drop cadence,
**every four-week forecast window contains roughly two drops**. Some share of the revenue being
forecast belongs to items that have zero history at the moment the forecast is made. That share is
the part of the error that ordinary time-series methods cannot touch. Measuring that share is the
single most important number EDA produces (Step 5 and Step 10).

**Constraint C — pooling colour hides the mechanism.** A style's weekly revenue can rise because
demand for that style rose, or because a fresh colour of it just dropped. Those are different
business events with different forward implications. A style series that adds them together will
answer "is demand going down" incorrectly. Step 6 exists solely to separate them.

---

## 4. Step 0 — Define the target and the benchmark (do this first, it takes a day)

Nothing downstream is measurable until this is fixed.

**Questions to answer**

1. The existing 8%: measured over what horizon, at what grain, at what level, on gross or net
   revenue, over what date range? Signed or absolute?
2. Can we obtain the **history of that forecast** (what it predicted, week by week, versus what
   happened)?
3. Is the sub-5% bar meant as an average across weeks, or a worst-week ceiling? These are very
   different engineering problems.

**Why question 2 matters more than it looks.** If we can get the org forecast's error history, we
can decompose where the 8% actually comes from before touching a model: is it a handful of bad
weeks (promo timing, drop timing), a persistent bias (always low), or evenly smeared across all
weeks? If the error is concentrated in a few event weeks, more product granularity will not fix it,
and this project should be redirected at event modelling instead. That finding alone would be worth
the whole exercise.

**Decision unlocked:** the scorecard. Two numbers, both reported from here on:
- **Primary:** error of the summed style forecast against actual total revenue, 4 weeks ahead.
- **Secondary:** error per style, weighted by that style's revenue share.

**Stop rule:** if the 8% cannot be defined precisely, escalate. Do not proceed on a guess.

---

## 5. Step 1 — Build the analysis base: the style-week grid

One clean table that every later step reads. Built once, tested once.

**Target shape:** one row per `style_key` × `week_start`, with revenue, units, and the context
columns below. It must be rebuildable and it must reconcile.

**Rules to apply, and the reason for each**

| Rule | Detail | Source |
|---|---|---|
| Style key | Normalise `product_name` (lowercase, collapse punctuation and spaces) and hash. Do **not** reuse `product_key`, which includes colour | §5.1, §5.2 |
| Known naming defect | One title of 7,117 splits on the first `" - "` and fragments into two keys. Check whether it survives pooling to style level | §8.2 |
| Non-colour values | 27 dimension rows carry a quantity where a colour should be (`8 oz`, `60 Pack`). At style level these should collapse harmlessly. Verify, do not assume | §8.1 |
| Week definition | Pick one and write it down: ISO Monday weeks, or a retail 4-5-4 week. The fiscal calendar file is out of scope per the README, so ISO is the default unless the business supplies a calendar | README |
| Incomplete weeks | Drop any week not fully covered by the extract. Last complete day is 2026-09-14 | §4.6, §8.7 |
| Dense grid | A style with no sales in a week must appear as a **real zero row**, not be missing. Absence in the fact table means no sale, and models must see the zero | §7.1 convention |
| Join cast | `daily_context.order_date` is TIMESTAMP, the fact is DATE. Cast on join | §4.6 |
| Status at style-week | `planning_status` is part of the fact grain, so one style-week can hold several. Carry both: the full mix, and a dominant status by revenue | §4.2, §5.3 |
| Family at style-week | `assigned_family` is likewise part of the grain. Carry the mix and the dominant | §4.2, §5.5 |
| Reconciliation gate | Total revenue across the whole grid must equal **$2,831,081,580.32** and units **31,761,946** before any filtering | §2, §10 |

**Context columns to attach**

- From `daily_context` (§4.6), rolled up to the week: `is_configured_sale` days in week,
  `is_volume_spike` days in week, `revenue_index`.
- From `drop_calendar` (§4.5) and `product_drop_membership` (§4.4): the style's drop families, each
  family's `anchor_date`, and therefore **weeks since that style's most recent drop anchor**.
- Derived age: weeks since the style's first genuine appearance.

**Age must not come from `first_seen_date`.** A value of 2025-01-01 means "already selling when the
extract began", not "launched then" (§8.7). Styles alive at the start are left-censored and must be
flagged as "age unknown, at least 89 weeks" rather than given a false age. Where a style has drop
membership, `first_tag_observed_date` and `anchor_date` give a real release date.

**Deliverable:** `style_week.parquet` plus a short build audit mirroring the existing
`data_quality.json` pattern.

---

## 6. Step 2 — Integrity gates before any analysis

Short, mechanical, and non-negotiable. Each one either passes or produces a documented decision.

| Check | What to look for | Decision it forces |
|---|---|---|
| Reconciliation | Grid totals match source exactly | Pass/fail gate |
| Style count | How many distinct styles exist, and how many have any revenue in the last 13 weeks | Confirms or corrects the "~1,900" working figure. The dimension holds 7,117 name+colour keys (§4.3) |
| Apparent duplicates | 2,578 groups, $3,192,610.49, retained by design (§8.10). Compute their share of revenue **per week**, not just overall | Net them out or keep them. At 0.11% of total they are immaterial on average, but a single concentrated week could matter against a 5% bar |
| Mixed / multiple taxonomy | 380 products span business lines ($341.8M), plus 98 category, 102 subcategory, 79 item class (§8.3). Does pooling colour into style reduce this, or make it worse? | Whether taxonomy can be used as a segmentation input at all |
| Unclassified block | The same $67,936,207.63 is missing category, subcategory and item class together (§8.5). It is one population of rows, not three gaps | Whether these styles get their own segment |
| Spikes and sale days | 32 spike days, 68 configured-sale days (§4.6) | Held for Step 8 |
| Zero and near-zero styles | Share of style-weeks that are zero | Whether the tail is forecastable at all, or must be aggregated |

**Stop rule:** do not "clean" anything discovered here without recording what changed and how much
revenue moved. The reconciliation guarantee is the project's credibility.

---

## 7. Step 3 — Concentration: how much of this problem is actually large

**Question:** how many styles carry the revenue, and how stable is that set week to week?

**How**
- Rank styles by revenue over the last 13 and last 52 weeks. Cumulative share curve.
- Count of styles needed to reach 50%, 80%, 95% of revenue.
- Stability: of the top styles in one quarter, how many are still top the next quarter?
- The same curves within each business line. Women is $2,039.7M of $2.8B and Men $545.7M, while
  Beauty, Wellness, Books and Internal together are under $7M (§6.1).

**Decisions unlocked**
- Which styles get an individual forecast, and which are forecast as a group.
- Whether small business lines are in scope at all. Below a revenue threshold they cannot move an
  org-level number and only add maintenance cost.

**Stop rule:** stop once the head/tail split is a defensible number with a chart behind it.

---

## 8. Step 4 — Segmentation on traits known in advance

**Question:** what groups of styles behave alike, in a way a merchant would recognise?

**The trap to avoid.** Grouping styles by the shape of their past growth curve is tempting and
wrong for this purpose. It clusters on the very history we then try to predict, the clusters move
when you re-run them, and a merchant cannot use the label to classify a new style. Segments must be
built from traits **known before the forecast window opens**.

**Candidate traits, all available in the data**

| Trait | Source |
|---|---|
| Revenue size band | Step 3 |
| Week-to-week volatility | Step 1 grid |
| Weeks of usable history | Step 1, censoring-aware |
| Lifecycle status mix: Core / Seasonal / Carryover / FPPhaseOut / Markdown | §5.3 |
| Drop-linked or not, and weeks since last drop anchor | §4.4, §4.5 |
| Category and business line, where not `Mixed / multiple` | §4.2, §8.3 |
| Share of weeks with zero sales | Step 1 |

**The lifecycle split is the one that carries the most weight**, because it maps onto three
genuinely different forecasting problems:

| Situation | Volume | Why it differs |
|---|---|---|
| Always-on Core | $863.1M | Long history, stable demand, ordinary methods work |
| Seasonal and drop-linked | $803.7M Seasonal | Short life. At forecast time there may be no history at all |
| Declining: FPPhaseOut, Markdown | $444.1M + $11.2M | The trend is a decline to zero. Modelling growth here is meaningless |

Note that `planning_status` is recorded **per row per date** (§4.2), so a style's status changes
over time. That transition (Core to Carryover to FPPhaseOut) is itself a leading signal, and it is
exactly the kind of explanation a merchant accepts.

**Decision unlocked:** the segment scheme, and one modelling approach per segment.

---

## 9. Step 5 — Drop mechanics: what is actually new every two weeks

This is the highest-value step in the whole plan, because it determines whether style-level
forecasting is a tractable problem or a mostly-cold-start problem.

**The question that matters most**

> When a drop lands, is it **new styles**, or **new colours of styles that already exist**?

If drops are mostly new colours of existing styles, then at style level most of the revenue has
history, and a four-week forecast is largely a continuation problem with a known refresh event.
If drops are mostly genuinely new styles, then a meaningful slice of every forecast window is
cold-start, and no amount of time-series sophistication will reach 5% without a release-aligned
curve library.

**How to answer it**
1. Join `product_drop_membership` to `drop_calendar` (§4.4, §4.5) and, for each of the 103 validated
   drops, split its products into styles already selling before the anchor date versus styles never
   seen before.
2. Express that split in **revenue**, not counts.
3. Repeat for the last 26 weeks specifically, since the recent pattern is what the forecast faces.

**Supporting questions in the same step**
- How many of the 103 drops fall inside the sales window at all? The calendar runs FA21D1 (2021)
  to FA26D3 (2026) but sales start 2025-01-01, so the early drops have a release date and no sales.
- What does a typical release-aligned curve look like: week 1, week 2, week 4, week 8 as a share of
  the first eight weeks? Is the decay shape consistent enough across drops to borrow?
- Does week-one revenue predict weeks two to five? If yes, cold-start becomes a much smaller problem
  after seven days.
- Seven drops have no `early_access_date`, so their anchor falls back to launch (§4.5, §8.6). Does
  that shift their curves?
- `drop_number` is not chronological in SP22 and SP22 has no D7 (§8.6). Order by `anchor_date`, never
  by drop number.
- Drop families excluded from the validated set are large: season rollups, men-specific tags,
  spotlight/capsule extensions, and `NO_FAM` at $346.3M associated revenue (§4.7). That associated
  revenue is **not additive** because a row can carry several tags, so it cannot be summed. The
  question is whether real drop activity is being missed by the validation rule.

**Decisions unlocked**
- Whether cold-start handling is a core workstream or a footnote.
- Whether a release-aligned curve library is needed, and at what level it should be built.

---

## 10. Step 6 — Is style-level demand going down?

The broad business question, answered carefully rather than quickly.

**Why the obvious answer is wrong.** Summing colours into a style and drawing a trend line conflates
two things: the underlying demand for the style, and the refresh cadence of colours attached to it.
A style whose demand is flat but whose colour refreshes have stopped will look like it is dying.
A style in genuine decline that just got a fresh colour will look healthy.

**The decomposition to run, per style, per week**

1. **Continuation revenue** — revenue from colours that were already selling before the week began.
2. **Injection revenue** — revenue from colours introduced by a drop in that week or the recent past.

Then measure trend on continuation revenue, and treat injection as an event driven by the drop
calendar. This is one of the few places where colour must be touched, and it is worth the cost
because the answer changes the conclusion.

**Additional cuts**
- Trend by segment from Step 4, not just overall. "Demand is going down" is usually a mix shift.
- Distinguish fewer styles selling from each style selling less. Count of active styles per week
  versus average revenue per active style.
- Total revenue trend from `daily_context` as the reference line, so style-level conclusions can be
  checked against the whole.

**Decisions unlocked**
- Whether the forecast needs an explicit decline term.
- Whether "product demand is falling" is a real finding or a colour-cadence artefact. This is a
  finding senior stakeholders will act on, so it has to be right.

---

## 11. Step 7 — Split revenue into units and price

Revenue is the target, but revenue is two things multiplied: units sold, and average revenue per
unit. They move for different reasons, and forecasting them separately is both more accurate and
far more explainable.

**How**
- Compute average realised price as **revenue ÷ units**. The source `price` column must not be used:
  the README states it contains mixed scaling regimes, and the data dictionary marks it unused
  (§3.1, §4.3 note on `source_price`, §8.7 context).
- Plot realised price per style over time. Look for step changes, which indicate markdown.
- Check whether the `Markdown` and `FPPhaseOut` statuses line up with realised-price drops. If they
  do, status becomes a usable markdown signal.

**Decision unlocked:** whether the forecast is one revenue model, or a units model times a price
model. Given the explainability requirement, the split is likely to win, because "we expect 10%
fewer units at 5% lower price" is a sentence a merchant can argue with.

---

## 12. Step 8 — Promotions, spikes, and calendar effects

**Question:** how much of weekly revenue variation is driven by events we could know about in
advance?

**What the data gives**
- 68 days inside configured sale windows and 32 statistical volume-spike days (§4.6).
- A volume spike is defined as revenue at least 3× the trailing 28-day median and above the global
  90th percentile. The README is explicit that this is a statistical flag, not a confirmed promotion.

**What to do**
- Quantify the revenue in spike and sale weeks. If those weeks hold a large share, promo handling
  is the main lever on the error, not product granularity.
- Investigate the May 2026 surge specifically. The README names it. Somebody in the business knows
  what it was, and that single answer decides whether it is signal to model or noise to flag.
- Test whether the two configured windows are the whole promo calendar. They almost certainly are
  not (Assumption 8).

**Do not remove promotions from the target.** Promotional revenue is real revenue and the business
is forecast on the total. Promotions belong in the model as a known input, not in the bin.

**Dependency to raise now:** a forward-looking promo calendar. A four-week forecast that does not
know about a sale starting in week three cannot be accurate, no matter how good the method is.

---

## 13. Step 9 — Measure predictability with naive baselines

Your original plan asks which products have the highest predictability. That is not visible by
inspection. It is measured, and it is measured during EDA, not after modelling.

**Backtest design**
- Rolling origin. Stand at week *t*, forecast weeks *t+1* to *t+4*, step forward one week, repeat.
- With ~89 weeks and a minimum training window of ~26 weeks, this yields roughly **55 test origins**.
- Every method sees only data available at its origin. No exceptions.

**Baselines to run (all trivially explainable)**

| Baseline | Rule |
|---|---|
| Last week repeated | Next four weeks equal the most recent week |
| Trailing 4-week average | Flat continuation of the recent average |
| Trailing average with trend | Recent average plus recent slope |
| Same week last year | Only testable for the second year of data, and only once per week. Constraint A applies |
| Segment share allocation | Forecast the total, then split it by each style's recent revenue share |

**Scoring**
- Report both scorecard numbers from Step 0: the summed-up total error, and the revenue-weighted
  per-style error.
- Report **skill**, meaning how much a method beats the best naive baseline, per segment. A style
  that a trailing average already predicts within 3% does not need a model, and saying so is a
  legitimate result.
- Rank segments and styles by skill. This is your step 4, now with a number attached.

**Decision unlocked:** which segments need real models, which are already solved by simple rules,
and which are hopeless individually and must be aggregated.

---

## 14. Step 10 — The feasibility test: can 5% actually be reached?

Run this before proposing any model. It is the step that protects the project from promising
something the data cannot deliver.

**The calculation**

Split the last 26 weeks of revenue into three buckets, as they would have looked from a forecast
origin four weeks earlier:

| Bucket | Definition | Forecastability |
|---|---|---|
| Established | Styles with 13+ weeks of history at the origin | Genuinely forecastable |
| Cold-start | Styles with no history at the origin, arriving via a drop inside the window | Only via borrowed release-aligned curves |
| Event-driven | Revenue inside spike or sale weeks | Only with a promo calendar |

Then estimate the best case: assume established revenue is forecast at the best baseline error from
Step 9, assume cold-start is forecast at the borrowed-curve error, assume event weeks are handled
either well or not at all. The resulting blended error is the **floor**.

**Decision unlocked, and it is the big one:**
- If the floor is comfortably under 5%, proceed to modelling with confidence.
- If the floor sits between 5% and 8%, the project can still improve on today but will not hit the
  target without the promo calendar and the drop calendar populated forward. Say so early.
- If the floor is above 8%, style-level granularity is not the lever, and the recommendation changes
  to segment-level forecasting with allocation, plus event modelling.

Delivering this honestly and early is worth more to the audience than an optimistic plan.

---

## 15. Step 11 — Visualise and pick examples

Last, not first. Built for a merchandising audience, not an analytics one.

- Cumulative revenue concentration curve, with the head/tail cut marked.
- One panel per segment: a representative style, its actual weekly revenue, the naive baseline, and
  the error.
- Release-aligned curves for the recent drops, overlaid, showing how consistent the decay shape is.
- The continuation-versus-injection decomposition for a handful of named styles, since that is the
  chart that answers "is demand going down".
- A skill ranking table: segment, revenue share, best baseline, error, verdict.
- Worked examples. `Accolade 1/4 Zip Pullover` appears in three of the latest ten drops per the
  README, which makes it a natural case study for a style that gets repeatedly refreshed.

---

## 16. Decision register — what EDA must settle

Every question here blocks a modelling choice. None of them should be answered by opinion.

| # | Question | Step | Decision it unlocks |
|---|---|---|---|
| 1 | What exactly is the 8%? | 0 | Whether success is measurable |
| 2 | Can we get the org forecast's error history? | 0 | Whether granularity is even the right lever |
| 3 | Gross or net revenue? | 0 / business | Whether we are forecasting the right quantity |
| 4 | How many styles are there really? | 2 | Scope and compute |
| 5 | ISO weeks or retail weeks? | 1 | Every aggregation downstream |
| 6 | Keep or net out the 2,578 duplicate groups? | 2 | Data base |
| 7 | Are `Mixed / multiple` styles usable? | 2 | Whether taxonomy can segment |
| 8 | How concentrated is revenue? | 3 | Individual vs grouped forecasting |
| 9 | Which segments, on which traits? | 4 | One method per segment |
| 10 | Are drops new styles or new colours? | 5 | Whether cold-start is core or a footnote |
| 11 | Is the release-aligned decay shape consistent? | 5 | Whether curves can be borrowed |
| 12 | Does week-one predict weeks two to five? | 5 | Size of the cold-start problem |
| 13 | Is style demand declining, net of colour refresh? | 6 | Whether a decline term is needed |
| 14 | Units and price separately, or revenue directly? | 7 | Model structure and explainability |
| 15 | What share of revenue sits in event weeks? | 8 | Whether promo is the main lever |
| 16 | Is the promo calendar complete, and available forward? | 8 / business | Achievable accuracy ceiling |
| 17 | Which segments beat naive baselines, and by how much? | 9 | Where to spend modelling effort |
| 18 | What is the error floor? | 10 | Go / no-go against the 5% target |

---

## 17. Risks

| ID | Risk | Impact | Response |
|---|---|---|---|
| R1 | History gets restated between extracts | Every backtest result is invalid | Compare two extracts on overlapping dates before trusting any backtest. Check first |
| R2 | `revenue` is gross, business plans on net | Forecasting the wrong quantity | Confirm with finance before Step 3 |
| R3 | Promo calendar is incomplete and has no forward view | 5% target unreachable regardless of method | Raise as a business dependency now, not at the end |
| R4 | Under two years of history | Annual seasonality cannot be learned per style | Estimate seasonality only at aggregate level. State the limitation in the readout |
| R5 | Drop calendar not populated four weeks forward | Model works in backtest, fails in production | Check the workbook's forward coverage and its ownership |
| R6 | Overfitting to 89 weeks | Backtest looks good, live performance does not | Rolling origin with many folds. Prefer simple methods. Reserve a final untouched holdout |
| R7 | Segment definitions drift | Merchants lose trust | Segment only on traits known in advance. Freeze definitions before modelling |
| R8 | Explainability traded away for accuracy under pressure | Output gets rejected by users | Treat explainability as a hard requirement, and record it as such in the scorecard |
| R9 | Scope creep into colour and size | Timeline slips | Colour is parked by decision. Size is not in the fact table at all |

---

## 18. Sequencing and checkpoints

| Phase | Steps | Output | Checkpoint |
|---|---|---|---|
| A | 0 | Scorecard definition, benchmark decomposition | Go / no-go on measurability |
| B | 1, 2 | `style_week.parquet` + integrity report | Reconciliation passes |
| C | 3, 4 | Concentration curves, segment scheme | Segments reviewed by merchandising |
| D | 5, 6 | Drop mechanics, demand-trend answer | Business readout on "is demand going down" |
| E | 7, 8 | Units/price split, event quantification | Promo dependency escalated |
| F | 9, 10 | Baseline backtest, skill ranking, error floor | **Go / no-go on the 5% target** |
| G | 11 | Visuals and examples | Final EDA readout |

Phase F is the decision point. Everything before it is evidence gathering, and everything after it
is modelling that should not start until F says it can succeed.

---

## 19. If the answer turns out to be no

A credible plan names its fallback. If Step 10 shows the floor above 5%, the recommendation becomes:

1. Forecast at **segment level**, where the noise of individual styles cancels out and accuracy is
   structurally higher.
2. Allocate the segment total down to styles using recent revenue shares, so planners still get a
   style-level number, with honest uncertainty attached.
3. Model drops as **events** against the release calendar rather than as products with history.
4. Put the remaining effort into the promo calendar, which is likely the larger untapped lever.

That outcome is still a win over today, and it is a defensible answer to bring to the room.

---

## 20. What I need from you to start

Three answers unblock everything else:

1. **The precise definition of the 8%**, and whether its forecast-versus-actual history can be pulled.
2. **Gross or net revenue.**
3. **Whether the promo calendar exists anywhere, and whether it is populated forward four weeks.**

Everything else in this document can be answered from the data already sitting in the repo.
