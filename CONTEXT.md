# CONTEXT.md

_Regenerated 2026-08-13T14:34:10+00:00 by `forecast/score.py`. Do not hand-edit._

This file is the working state of a daily gas-price forecast calibration loop. It is written for two readers: a human skimming, and a fresh Claude session with no memory of this project. If you are the latter, read DESIGN.md next — it holds the reasoning, the rejected alternatives, and the invariants.

## What this system does

Every day a GitHub Actions job scrapes the AAA national average, scores yesterday's forecast against what actually happened, then makes a new forecast for tomorrow. The forecast is not the product — **the calibration record is**. The question being answered is 'when this system says 70%, does it happen about 70% of the time?'

The target is always the **change** in price, never the level, and thresholds are relative to the level at forecast time.

## Data on hand

- Observations: **21**
- Range: `2026-07-24` to `2026-08-13`
- Gaps: **0**
- Forecasts written: **15**
- Forecasts scored: **14**
- Awaiting outcome: **1**

Most recent scored call — `2026-08-13` (`prior` mode): predicted **-0.22c**, actual **+3.55c**, error **+3.77c**.

## What the model is keying on

**Not fitted yet.** The ridge model needs 30 complete training rows and has **13**. Until then every forecast comes from the bootstrap prior, which is a rule of thumb with no coefficients to show.

## Calibration

`prior` and `model` rows are reported separately and never pooled. Prior-mode rows are bootstrap output and say nothing about model skill.

### mode = `prior` (n = 14)

- Effective n, by error correlation: **3.3** (lag-1 r = +0.62)
- Effective n, by price-change correlation: **3.4** (lag-1 r = +0.61)
- **Gating on the lower: n_eff = 3.3** (the residual figure).
- The two figures are close, which means the model is not yet removing much of the day-to-day overlap between consecutive forecasts.

- **Nothing is concludable at n_eff = 3.3.** The numbers below are recorded so the series exists, not because they support a claim. Do not quote them as skill.

| threshold | Brier | vs 0.25 | base rate | n |
|---|---|---|---|---|
| > -2c | 0.0681 | +0.1819 | 0.93 | 14 |
| > -1c | 0.2010 | +0.0490 | 0.71 | 14 |
| > +0c **(headline)** | 0.2559 | -0.0059 | 0.29 | 14 |
| > +1c | 0.1335 | +0.1165 | 0.14 | 14 |
| > +2c | 0.1401 | +0.1099 | 0.14 | 14 |

Judge this system on the `> +0c` row, secondarily `±1c`. The ±2c thresholds routinely resolve before they are asked — a Brier near zero against a base rate of 0 or 1 measures nothing. **Do not average across the grid and quote the result as 'the Brier score'.**

**Predictive distribution**

- PIT mean: **0.425** (target 0.500)
- 80% interval coverage: **64.3%** (target 80.0%)
- Residual sd 1.59c vs claimed sigma 1.00c (ratio 1.59)
- Spread check: **held** at n_eff = 3.3 (needs 20). Errors currently look wider than the claimed sigma, but that comparison is not yet evidence.

**Reliability** (pooled across thresholds; bins with n<3 suppressed)

| bin | n | predicted | observed | gap |
|---|---|---|---|---|
| 0.0–0.1 | 19 | 0.034 | 0.158 | +12.3pp |
| 0.1–0.3 | 9 | 0.154 | 0.111 | -4.2pp |
| 0.3–0.5 | 11 | 0.409 | 0.273 | -13.6pp |
| 0.5–0.7 | 3 | 0.544 | 0.333 | -21.0pp |
| 0.7–0.9 | 14 | 0.795 | 0.714 | -8.1pp |
| 0.9–1.0 | 14 | 0.964 | 0.929 | -3.6pp |

## Known limitations

- **The model is deaf to news.** Its worst historical call was a +48.5c week predicted at +6.5c, driven by a geopolitical supply shock. Momentum is a lagging echo when news drives price, not a leading signal. Expect the calibration to degrade in exactly those weeks.
- **`PRIOR_SIGMA_C = 1.0` cents is a guess**, derived loosely from weekly EIA variance. Daily autocorrelation has never been measured. Replacing it with a measured value at n >= 60 is milestone M5.
- **`PRIOR_SHRINK = 0.35` has no empirical basis.** Placeholder, also due to die at M5.

