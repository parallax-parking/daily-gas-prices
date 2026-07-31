# Design: daily gas price forecast calibration loop

**Status:** implemented through M4; M5 blocked on data volume
**Repo:** `parallax-parking/nantucket-late-august`
**Audience:** a Claude Code session implementing or extending this. You will not
have the conversation this came from. Everything you need is here, including the
reasons behind choices that look arbitrary — several of them are load-bearing
and were arrived at by measurement. Section 10 lists things already tried and
rejected, with evidence. Do not relitigate those without new data.

---

## 0. Implementation status

_Added during implementation. Everything below section 0 is the design as
written, with one correction noted in §2._

| milestone | state |
|---|---|
| M0 — schema | done. 4dp storage, lag columns, backward-compatible migration, revision check, `--backfill`. |
| M1 — forecast in prior mode | done. `forecast/forecast.py`, wired into the daily job. |
| M2 — scoring | done. `forecast/score.py` → `CONTEXT.md`. |
| M3 — fitted model | done and tested against synthetic data. **Dormant until 30 training rows exist** (~2026-08-30 at one row/day). |
| M4 — review routine | **prompt written, Routine not created.** Creating it needs a tool approval this session did not have. Prompt and cron are in `forecast/REVIEW_ROUTINE.md`, ready to create. Deliberately *not* implemented with a session-scoped cron: those expire after 7 days, which §8 rules out. |
| M5 — replace the prior with measurement | **blocked.** Needs n ≥ 60, i.e. no earlier than ~2026-09-28. |

Decisions taken against §11's open questions:

- **Grade: `regular` only.** `forecasts.csv` carries a `grade` column, so adding
  others later is additive — no migration.
- **`CONTEXT.md` is committed** on every run, as §11 proposed. Noisy history,
  clean audit trail.
- **Exogenous inputs deferred** to M6, per §11.

---

## 1. Goal

Produce a **calibrated** daily probabilistic forecast of the AAA national
average gas price, and accumulate an auditable record of how good it is.

The forecast is not the product. **The calibration record is the product.** A
forecast that is right is worth less than a forecast whose reliability we can
quantify.

Concretely, after ~3 months we want to be able to say: "when this system says
70%, it happens about 70% of the time," with an honest error bar on that claim.

### Non-goals

- Trading. Nothing here should assume a position is being taken.
- Predicting price *levels*. The target is always **change**, never level —
  see §6.1.
- Beating the market. If a liquid market disagrees with us, the market is
  probably right and our job is to notice by how much and why.

---

## 2. What already exists

**`scraper/aaa_gas_prices.py`** — working. Runs daily via GitHub Actions,
scrapes "Today's AAA National Average" from `gasprices.aaa.com`, appends one row
per US-Eastern date to `data/aaa_national_average.csv`, commits back to the
repo. Idempotent per date unless `--force`. Parses on table *shape* (a fuel-grade
header plus a row labelled `Current Avg.`) rather than CSS classes, so it
survives re-themes.

Schema as of M0:

```
date,regular,mid_grade,premium,diesel,e85,
regular_yesterday,regular_week_ago,regular_month_ago,regular_year_ago,
retrieved_at_utc,source_url
```

**As of 2026-07-30 there is exactly one day of data.** Everything below has to
work from a cold start.

> **Correction, made during implementation.** The original draft of this section
> stated that `forecast/forecast.py`, `forecast/score.py` and
> `forecast/README.md` had been drafted and smoke-tested against a synthetic
> 90-day series. They had not — no files by those names existed in any branch,
> commit, or stash of this repository. They were written from scratch against
> §5–§7, which specify the behaviour completely enough that this cost little.
> The synthetic-series smoke test described in §9 was likewise written fresh; it
> now lives in `forecast/tests/test_forecast.py` and passes. If the original
> drafts exist somewhere outside this repo, reconcile rather than duplicate.

---

## 3. Invariants

These are not preferences. Violating any of them silently destroys the value of
the record, usually without an error.

1. **A forecast row is written before its outcome exists, and is never edited.**
   Git commit timestamps are the proof. If you need to change the model, bump
   `MODEL_VERSION` and leave old rows standing.

2. **`forecast.py` must never see the value it is predicting.** Its only inputs
   are `data/aaa_national_average.csv` as of the current commit, plus any
   exogenous series with a stated as-of date strictly before the target date.

3. **No LLM in the forecast path.** The forecast is produced by deterministic
   code with a pinned model version. An agent that reasons freshly each morning
   is a moving target, and Brier scores against a moving target measure nothing.
   Agents belong in the review layer (§8, M4).

4. **Score before forecast, within a run.** Scoring consumes the reading that
   just landed; forecasting takes it as an input. Reversed, you score a forecast
   against its own input.

5. **Threshold probabilities are relative to the level at forecast time**, not
   absolute prices. See §6.4 — this is the difference between a calibration
   curve that converges and one that never does.

6. **Store four decimals.** AAA publishes `$4.0980`; the pre-M0 CSV stored
   `4.098`. Every interesting question here turns on tenths of a cent.

---

## 4. Architecture

```
scraper/
  aaa_gas_prices.py          # scrape, store, backfill, revision check
forecast/
  features.py                # feature construction, pure functions
  model.py                   # fit / predict, prior fallback
  thresholds.py              # the threshold grid, shared
  forecast.py                # CLI: append one immutable forecast row
  score.py                   # CLI: join, score, regenerate CONTEXT.md
  tests/
data/
  aaa_national_average.csv   # observations   (scraper owns)
  forecasts.csv              # predictions    (append-only)
CONTEXT.md                   # regenerated each run; human- and LLM-readable
DESIGN.md                    # this file
```

Daily Actions job, in order:

```yaml
- run: python scraper/aaa_gas_prices.py --out data/aaa_national_average.csv
- run: python forecast/score.py --out CONTEXT.md
- run: python forecast/forecast.py --out data/forecasts.csv
- run: |
    git add data/ CONTEXT.md
    git diff --staged --quiet || git commit -m "data: $(date -u +%F)"
    git push
```

Keep it in one job so the three steps share a working tree and land in one
commit. If you split them, the forecast and its outcome can end up in commits
whose order doesn't reflect reality.

---

## 5. Data schemas

### 5.1 `data/aaa_national_average.csv`

The context columns AAA already renders on the same page — `Yesterday`,
`Week Ago`, `Month Ago`, `Year Ago` — are captured for the `regular` grade.

Three reasons this is worth the extra parsing:

- **Gap repair.** GitHub delays or drops scheduled runs under load. A missed day
  is recoverable from the next day's `regular_yesterday`.
- **Revision detection.** Today's `regular_yesterday` should equal yesterday's
  `regular`. When it doesn't, AAA revised, and you want to know rather than
  silently carry a changed number into the feature set.
- **Free anchors** at week/month/year lags for validating longer-horizon work.

Migration is backward compatible: old rows keep empty values in the new columns.

Rows written by `--backfill` carry `regular` only, and are marked in
`source_url` with `backfill:next-day-yesterday` so they are never mistaken for
direct observations.

### 5.2 `data/forecasts.csv` (append-only)

```
target_date        # date being forecast (made_on_date + 1 day)
made_at_utc        # ISO timestamp
made_on_date       # last observation date used
grade              # 'regular'
level_at_forecast  # price at made_on_date, 4dp
mu_cents           # point forecast of CHANGE, cents
sigma_cents        # predictive sd, cents
n_train            # rows the model was fit on
mode               # 'model' | 'prior'
model_version      # pinned string
git_sha            # short sha of the producing commit
features           # JSON of the feature vector used
p_gt_m2c ... p_gt_p2c   # P(change > -2,-1,0,+1,+2 cents)
```

`mu_cents` and `sigma_cents` make **any** absolute threshold recoverable after
the fact: `P(price > X) = norm_sf((X - level_at_forecast - mu) / sigma)`. Stored
always, even in `prior` mode.

`features` is not optional. Without it you cannot diagnose a bad forecast weeks
later, and diagnosing bad forecasts is most of the value.

---

## 6. The model

### 6.1 Target

`y[t] = price[t+1] - price[t]`. **Never the level.**

Predicting the level scores an R² near 0.999 from pure persistence and tells you
nothing. Every metric in this system is relative to the naive "no change"
baseline.

Implementation note: the code works in **cents** throughout, since that is the
unit the calibration record is quoted in. Conversion happens at the CSV
boundary.

### 6.2 Features (daily)

All computed causally from data up to and including `made_on_date`:

- `d1, d2, d3` — recent daily changes
- `ma3, ma7` — rolling means of changes
- `vol7` — rolling sd of changes
- `wk` — 7-day change (weekly-scale momentum)
- `dow` — day of week (of the *target*, not of `made_on` — weekend pricing
  behaviour is a property of the day being predicted)

Lags are looked up **by calendar date, not row position**. A missing day yields
NaN rather than a lag that silently spans a gap. A wrong feature is far more
expensive here than an absent one.

### 6.3 Estimator

Ridge (`alpha≈5`) on standardised features. Deliberately boring:

- On weekly data, gradient boosting beat ridge by 0.003 skill — noise. The
  relationship is close to linear.
- Coefficients are inspectable, which matters when explaining a bad call.
- It fits in milliseconds on any amount of data this system will ever have.

`sigma` comes from an expanding-window backtest — refit at each step on strictly
prior data, collect the honest one-step errors, take their spread. In-sample
residuals would understate sigma and manufacture overconfidence, which §7's own
overconfidence check would then flag on our own model. This is the Gaussian
analogue of the conformal approach §10 settled on.

### 6.4 Threshold grid — why relative

Store `P(change > c)` for `c ∈ {-2,-1,0,+1,+2}` cents.

If thresholds were absolute (`P(price > $4.09)`), then as the level drifts,
every day is a structurally different bet — some trivially resolved before
they're made. Pooling those into a reliability curve is meaningless. Relative
thresholds keep each day comparable.

**The `> 0c` threshold is the only genuinely hard one.** In smoke testing, `±2c`
scored a Brier of 0.0002 against a 100% base rate — resolved before it was
asked. Report all five, but judge the system on `> 0c`, secondarily `±1c`. Do
not average across the grid and quote the result as "the Brier score."

### 6.5 Bootstrap prior

Below `MIN_TRAIN = 30` observations, forecast from an explicit prior:
`mu = 0.35 × mean(last 7 daily changes)`, `sigma = PRIOR_SIGMA_C = 1.0` cents.
Tag the row `mode='prior'`.

`PRIOR_SIGMA_C` is a real guess and is labelled as one in the code. It comes
from weekly EIA variance, which pins daily sigma only loosely — roughly 0.9–1.5
cents depending on assumed daily autocorrelation. **The daily autocorrelation ρ
has never been measured.** Measuring it is the main scientific output of the
first two months (§9, M5).

Scoring reports `prior` and `model` rows separately. Prior-mode rows are not
evidence about model skill.

---

## 7. Scoring

`score.py` joins forecasts to outcomes and writes `CONTEXT.md`. Reports:

- **Brier per threshold**, against the 0.25 no-skill reference, with base rates
  alongside so degenerate thresholds are visible.
- **Reliability**, pooled across thresholds to reach usable bin counts early.
  Bins: `[0,.1,.3,.5,.7,.9,1]`. Bins with n<3 suppressed.
- **PIT** — `Φ((actual - mu)/sigma)` should be uniform; reports the mean (target
  0.500) and 80% interval coverage (target 80%).
- **Overconfidence check** — residual sd vs claimed sigma. Flagged if residual
  sd exceeds 1.25× sigma.
- **Effective n**, not nominal n. Consecutive daily forecasts are nearly the
  same bet. Uses the lag-1 autocorrelation adjustment `n_eff = n(1-r)/(1+r)`,
  computed **two ways**, and gates on the lower:
  - on the **residual** (z) series — how correlated the system's errors are. If
    the model genuinely captures momentum its errors decorrelate and n_eff
    approaches n. Risks overstating the evidence when errors only look
    independent.
  - on the **outcome** (actual change) series — how correlated price changes
    themselves are. Gas prices are persistently autocorrelated regardless of
    model quality, so this pins the discount near a constant fraction of n.
    Risks sitting on a sound result for months.

  Both are reported. The gap between them is informative in its own right: if
  they stay close, the model is not removing the day-to-day overlap, which
  neither number alone would reveal. `n_eff` is capped at nominal `n` —
  anti-correlated errors do carry more information per observation, but
  claiming more independent evidence than there are observations is not a claim
  this report should make.

  Gates on the lower figure:
  - `n_eff < 20` — reports numbers, states plainly that nothing is concludable
  - `n_eff < 50` — directional read only; gaps under 10pp are noise
  - otherwise — first honest calibration read

`CONTEXT.md` has two readers: a human skimming, and a fresh Claude session with
no memory of any of this. It is written so the second reader can pick up cold.
It is the only state that survives between sessions.

---

## 8. Milestones

**M0 — schema.** Four-decimal storage. `Yesterday`/`Week Ago`/`Month Ago`/
`Year Ago` columns. Backward-compatible migration. Revision check that warns
when today's `yesterday` ≠ yesterday's `regular`.

**M1 — forecast in prior mode.** `forecast.py` writing `forecasts.csv`, wired
into the Actions job. Refuses to overwrite an existing `target_date`+`grade`.
Works from a single observation without crashing.

**M2 — scoring.** `score.py` + `CONTEXT.md`. Handles zero scored forecasts
gracefully — this is the state for the first two days.

**M3 — fitted model.** Switches at `n_train ≥ 30`. The `prior`→`model`
transition appears in `CONTEXT.md` and the two populations are scored
separately.

**M4 — review routine.** A weekly Claude Code **Cloud Routine** (not `/loop` —
that's session-scoped and expires in 7 days) reading `CONTEXT.md` and recent
commits, opening a GitHub issue when it finds: calibration drift, a parser
degrading, or a regime the model's assumptions don't cover. Routines run
autonomously and cannot ask clarifying questions, so the prompt states exactly
what to do with what it finds.

Note: scheduled runs fire up to 30 minutes after their nominal time (the offset
is deterministic, derived from the task ID). Pick a minute that isn't `:00` or
`:30`. For the daily pipeline this doesn't matter much, but if the read time
ever drifts across AAA's own refresh you'd capture pre- and post-update values
on different days — a silent corruption of exactly the digit we care about.
The daily job runs at `:17` and the weekly review at `:23` for this reason.

**M5 — replace the prior with measurement.** Once `n ≥ 60`, estimate daily ρ and
σ directly, replace `PRIOR_SIGMA_C`, and record the measured values in this doc.

---

## 9. Acceptance tests

All implemented in `forecast/tests/` and `scraper/tests/`.

- `forecast.py` refuses to write a second row for an existing
  `target_date`+`grade`, and exits 0 (not an error — reruns are expected).
- `forecast.py` runs without crashing on a 1-row observations file.
- Round-trip: recomputing `p_gt_*` from stored `mu`/`sigma` reproduces the
  stored values to 4dp.
- `score.py` produces valid `CONTEXT.md` with zero scored forecasts.
- On a synthetic 90-day random-walk series, calibration output is sane: PIT mean
  within [0.40, 0.60], pooled reliability gaps mostly under 15pp.
- Gap repair: deleting a middle row from the observations CSV and re-running the
  backfill reconstructs it from the following day's `regular_yesterday`.
- A `mode='prior'` row and a `mode='model'` row are never pooled in any headline
  skill number.

---

## 10. Rejected alternatives

Measured on weekly EIA data, 1993–2026, walk-forward with quarterly refits, 160
weeks of true holdout. Do not re-add these without new evidence.

| Idea | Result |
|---|---|
| Regional cross-section (28 EIA region/state/city series: Gulf Coast lead-lag, dispersion, region-vs-national gaps) | **No gain.** Baseline skill +0.360 → +0.355 with regions. Paired t on squared-error reduction = −0.27. The national average *is* a weighted mean of those regions, so their moves are already inside the national momentum term. Redundancy, not information. |
| Asymmetric crude terms ("rockets and feathers": separate coefficients for positive/negative wholesale moves) | **No gain.** +0.369 → +0.367. The asymmetry is already absorbed by momentum features. |
| Error-correction term (retail/crude spread vs its rolling mean) | **No gain.** +0.367 → +0.368. |
| Gradient boosting instead of ridge | +0.003 skill. Noise. Not worth the opacity. |
| Quantile GBM for predictive intervals | **Badly miscalibrated.** 80% nominal interval realised 66.8%. Conformal intervals from rolling empirical out-of-sample errors got 77.3%. Use conformal. |
| Crude/wholesale features *alone*, without retail momentum | +0.217 vs +0.291 for momentum alone. Crude helps only as a supplement. |

**What actually carries the signal:** last period's change. Standardised
coefficient +2.07 cents per SD, roughly three times the next-largest feature.
Everything else is a rounding error on top of momentum. The mechanism is
staggered repricing — stations don't all move at once, so a wholesale shock
keeps propagating for days-to-weeks after it lands. This is a diffusion effect,
not a market inefficiency.

**Known failure mode:** the model is deaf to news. Its worst call in 160 holdout
weeks was 2026-03-09 — actual +48.5c, predicted +6.5c — the second-largest
weekly move in the 33-year record, driven by a geopolitical supply shock. When
news is driving prices rather than diffusion, momentum is a lagging echo, not a
leading signal. M4's review routine exists partly to flag this state.

---

## 11. Open questions

- **Grade.** Resolved: `regular` only, see §0. Revisit once there is a
  calibration record worth widening.
- **Exogenous inputs.** Weekly EIA retail and daily WTI improved the weekly
  model materially (skill +0.291 → +0.369). Adding them here means a second
  fetcher and as-of-date discipline. M6, not now.
- **`PRIOR_SHRINK = 0.35`** is unjustified. It's a placeholder that should die
  at M5.
- `CONTEXT.md` is committed on every run. Noisy history, clean audit trail.
