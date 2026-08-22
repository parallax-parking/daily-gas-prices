# CONTEXT.md

_Regenerated 2026-08-22T13:46:01+00:00 by `forecast/score.py`. Do not hand-edit._

This file is the working state of a daily gas-price forecast calibration loop. It is written for two readers: a human skimming, and a fresh Claude session with no memory of this project. If you are the latter, read DESIGN.md next — it holds the reasoning, the rejected alternatives, and the invariants.

## What this system does

Every day a GitHub Actions job scrapes the AAA national average, scores yesterday's forecast against what actually happened, then makes a new forecast for tomorrow. The forecast is not the product — **the calibration record is**. The question being answered is 'when this system says 70%, does it happen about 70% of the time?'

The target is always the **change** in price, never the level, and thresholds are relative to the level at forecast time.

## Data on hand

- Observations: **30**
- Range: `2026-07-24` to `2026-08-22`
- Gaps: **0**
- Forecasts written: **24**
- Forecasts scored: **23**
- Awaiting outcome: **1**

Most recent scored call — `2026-08-22` (`prior` mode): predicted **+0.16c**, actual **-0.68c**, error **-0.84c**.

## What the model is keying on

**Not fitted yet.** The ridge model needs 30 complete training rows and has **22**. Until then every forecast comes from the bootstrap prior, which is a rule of thumb with no coefficients to show.

## Calibration

`prior` and `model` rows are reported separately and never pooled. Prior-mode rows are bootstrap output and say nothing about model skill.

### mode = `prior` (n = 23)

- Effective n, by error correlation: **5.2** (lag-1 r = +0.63)
- Effective n, by price-change correlation: **4.8** (lag-1 r = +0.66)
- **Gating on the lower: n_eff = 4.8** (the outcome figure).
- The two figures are close, which means the model is not yet removing much of the day-to-day overlap between consecutive forecasts.

- **Nothing is concludable at n_eff = 4.8.** The numbers below are recorded so the series exists, not because they support a claim. Do not quote them as skill.

| threshold | Brier | vs 0.25 | base rate | n |
|---|---|---|---|---|
| > -2c | 0.0415 | +0.2085 | 0.96 | 23 |
| > -1c | 0.1276 | +0.1224 | 0.83 | 23 |
| > +0c **(headline)** | 0.2538 | -0.0038 | 0.39 | 23 |
| > +1c | 0.1464 | +0.1036 | 0.17 | 23 |
| > +2c | 0.1257 | +0.1243 | 0.13 | 23 |

Judge this system on the `> +0c` row, secondarily `±1c`. The ±2c thresholds routinely resolve before they are asked — a Brier near zero against a base rate of 0 or 1 measures nothing. **Do not average across the grid and quote the result as 'the Brier score'.**

**Predictive distribution**

- PIT mean: **0.461** (target 0.500)
- 80% interval coverage: **69.6%** (target 80.0%)
- Residual sd 1.39c vs claimed sigma 1.00c (ratio 1.39)
- Spread check: **held** at n_eff = 4.8 (needs 20). Errors currently look wider than the claimed sigma, but that comparison is not yet evidence.

**Reliability** (pooled across thresholds; bins with n<3 suppressed)

| bin | n | predicted | observed | gap |
|---|---|---|---|---|
| 0.0–0.1 | 28 | 0.035 | 0.143 | +10.8pp |
| 0.1–0.3 | 18 | 0.184 | 0.167 | -1.7pp |
| 0.3–0.5 | 11 | 0.409 | 0.273 | -13.6pp |
| 0.5–0.7 | 12 | 0.572 | 0.500 | -7.2pp |
| 0.7–0.9 | 23 | 0.830 | 0.826 | -0.4pp |
| 0.9–1.0 | 23 | 0.973 | 0.957 | -1.6pp |

## Known limitations

- **The model is deaf to news.** Its worst historical call was a +48.5c week predicted at +6.5c, driven by a geopolitical supply shock. Momentum is a lagging echo when news drives price, not a leading signal. Expect the calibration to degrade in exactly those weeks.
- **`PRIOR_SIGMA_C = 1.0` cents is a guess**, derived loosely from weekly EIA variance. Daily autocorrelation has never been measured. Replacing it with a measured value at n >= 60 is milestone M5.
- **`PRIOR_SHRINK = 0.35` has no empirical basis.** Placeholder, also due to die at M5.

