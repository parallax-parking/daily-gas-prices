# CONTEXT.md

_Regenerated 2026-08-17T13:54:54+00:00 by `forecast/score.py`. Do not hand-edit._

This file is the working state of a daily gas-price forecast calibration loop. It is written for two readers: a human skimming, and a fresh Claude session with no memory of this project. If you are the latter, read DESIGN.md next — it holds the reasoning, the rejected alternatives, and the invariants.

## What this system does

Every day a GitHub Actions job scrapes the AAA national average, scores yesterday's forecast against what actually happened, then makes a new forecast for tomorrow. The forecast is not the product — **the calibration record is**. The question being answered is 'when this system says 70%, does it happen about 70% of the time?'

The target is always the **change** in price, never the level, and thresholds are relative to the level at forecast time.

## Data on hand

- Observations: **25**
- Range: `2026-07-24` to `2026-08-17`
- Gaps: **0**
- Forecasts written: **19**
- Forecasts scored: **18**
- Awaiting outcome: **1**

Most recent scored call — `2026-08-17` (`prior` mode): predicted **+0.27c**, actual **-0.20c**, error **-0.47c**.

## What the model is keying on

**Not fitted yet.** The ridge model needs 30 complete training rows and has **17**. Until then every forecast comes from the bootstrap prior, which is a rule of thumb with no coefficients to show.

## Calibration

`prior` and `model` rows are reported separately and never pooled. Prior-mode rows are bootstrap output and say nothing about model skill.

### mode = `prior` (n = 18)

- Effective n, by error correlation: **3.7** (lag-1 r = +0.66)
- Effective n, by price-change correlation: **3.6** (lag-1 r = +0.67)
- **Gating on the lower: n_eff = 3.6** (the outcome figure).
- The two figures are close, which means the model is not yet removing much of the day-to-day overlap between consecutive forecasts.

- **Nothing is concludable at n_eff = 3.6.** The numbers below are recorded so the series exists, not because they support a claim. Do not quote them as skill.

| threshold | Brier | vs 0.25 | base rate | n |
|---|---|---|---|---|
| > -2c | 0.0530 | +0.1970 | 0.94 | 18 |
| > -1c | 0.1596 | +0.0904 | 0.78 | 18 |
| > +0c **(headline)** | 0.2701 | -0.0201 | 0.28 | 18 |
| > +1c | 0.1135 | +0.1365 | 0.11 | 18 |
| > +2c | 0.1093 | +0.1407 | 0.11 | 18 |

Judge this system on the `> +0c` row, secondarily `±1c`. The ±2c thresholds routinely resolve before they are asked — a Brier near zero against a base rate of 0 or 1 measures nothing. **Do not average across the grid and quote the result as 'the Brier score'.**

**Predictive distribution**

- PIT mean: **0.411** (target 0.500)
- 80% interval coverage: **72.2%** (target 80.0%)
- Residual sd 1.41c vs claimed sigma 1.00c (ratio 1.41)
- Spread check: **held** at n_eff = 3.6 (needs 20). Errors currently look wider than the claimed sigma, but that comparison is not yet evidence.

**Reliability** (pooled across thresholds; bins with n<3 suppressed)

| bin | n | predicted | observed | gap |
|---|---|---|---|---|
| 0.0–0.1 | 23 | 0.035 | 0.130 | +9.6pp |
| 0.1–0.3 | 13 | 0.170 | 0.077 | -9.3pp |
| 0.3–0.5 | 11 | 0.409 | 0.273 | -13.6pp |
| 0.5–0.7 | 7 | 0.560 | 0.286 | -27.4pp |
| 0.7–0.9 | 18 | 0.814 | 0.778 | -3.6pp |
| 0.9–1.0 | 18 | 0.969 | 0.944 | -2.5pp |

## Known limitations

- **The model is deaf to news.** Its worst historical call was a +48.5c week predicted at +6.5c, driven by a geopolitical supply shock. Momentum is a lagging echo when news drives price, not a leading signal. Expect the calibration to degrade in exactly those weeks.
- **`PRIOR_SIGMA_C = 1.0` cents is a guess**, derived loosely from weekly EIA variance. Daily autocorrelation has never been measured. Replacing it with a measured value at n >= 60 is milestone M5.
- **`PRIOR_SHRINK = 0.35` has no empirical basis.** Placeholder, also due to die at M5.

