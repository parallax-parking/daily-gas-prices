# CONTEXT.md

_Regenerated 2026-09-20T16:50:13+00:00 by `forecast/score.py`. Do not hand-edit._

This file is the working state of a daily gas-price forecast calibration loop. It is written for two readers: a human skimming, and a fresh Claude session with no memory of this project. If you are the latter, read DESIGN.md next — it holds the reasoning, the rejected alternatives, and the invariants.

## What this system does

Every day a GitHub Actions job scrapes the AAA national average, scores yesterday's forecast against what actually happened, then makes a new forecast for tomorrow. The forecast is not the product — **the calibration record is**. The question being answered is 'when this system says 70%, does it happen about 70% of the time?'

The target is always the **change** in price, never the level, and thresholds are relative to the level at forecast time.

## Data on hand

- Observations: **59**
- Range: `2026-07-24` to `2026-09-20`
- Gaps: **0**
- Forecasts written: **53**
- Forecasts scored: **52**
- Awaiting outcome: **1**

Most recent scored call — `2026-09-20` (`model` mode): predicted **+0.19c**, actual **+0.02c**, error **-0.17c**.

## What the model is keying on

Standardised ridge coefficients, refit on all **51** training rows available today. Units are cents of predicted next-day change per one standard deviation of the feature, so the magnitudes are directly comparable to each other.

| feature | weight | what it is |
|---|---|---|
| `d1` | +1.064 | yesterday's change |
| `d2` | -0.496 | the change 2 days ago |
| `d3` | -0.273 | the change 3 days ago |
| `ma7` | +0.255 | mean of the last 7 daily changes |
| `wk` | +0.255 | 7-day change |
| `dow` | -0.208 | day of week (of the target) |
| `ma3` | +0.123 | mean of the last 3 daily changes |
| `vol7` | +0.084 | volatility of the last 7 daily changes |

Largest: `d1` at +1.064, 2.1× the next-largest (`d2`).

DESIGN.md §10 found on weekly data that last period's change dominates everything else by roughly 3×, with the mechanism being staggered repricing — stations don't all move at once, so a shock keeps propagating for days. **If `d1` is not on top here, that is a genuine finding about daily data**, not a bug: it would mean the daily dynamics differ from the weekly ones this design was built on. Worth investigating before trusting the forecasts.

## Calibration

`prior` and `model` rows are reported separately and never pooled. Prior-mode rows are bootstrap output and say nothing about model skill.

### mode = `model` (n = 21)

- Effective n, by error correlation: **21.0** (lag-1 r = -0.11)
- Effective n, by price-change correlation: **9.2** (lag-1 r = +0.39)
- **Gating on the lower: n_eff = 9.2** (the outcome figure).

- **Nothing is concludable at n_eff = 9.2.** The numbers below are recorded so the series exists, not because they support a claim. Do not quote them as skill.

| threshold | Brier | vs 0.25 | base rate | n |
|---|---|---|---|---|
| > -2c | 0.0036 | +0.2464 | 1.00 ⚠︎ degenerate | 21 |
| > -1c | 0.0276 | +0.2224 | 1.00 ⚠︎ degenerate | 21 |
| > +0c **(headline)** | 0.1187 | +0.1313 | 0.95 | 21 |
| > +1c | 0.1956 | +0.0544 | 0.52 | 21 |
| > +2c | 0.1809 | +0.0691 | 0.33 | 21 |

Judge this system on the `> +0c` row, secondarily `±1c`. The ±2c thresholds routinely resolve before they are asked — a Brier near zero against a base rate of 0 or 1 measures nothing. **Do not average across the grid and quote the result as 'the Brier score'.**

**Predictive distribution**

- PIT mean: **0.584** (target 0.500)
- 80% interval coverage: **81.0%** (target 80.0%)
- Residual sd 2.26c vs claimed sigma 1.60c (ratio 1.42)
- Spread check: **held** at n_eff = 9.2 (needs 20). Errors currently look wider than the claimed sigma, but that comparison is not yet evidence.

**Reliability** (pooled across thresholds; bins with n<3 suppressed)

| bin | n | predicted | observed | gap |
|---|---|---|---|---|
| 0.0–0.1 | 9 | 0.034 | 0.111 | +7.7pp |
| 0.1–0.3 | 10 | 0.202 | 0.400 | +19.8pp |
| 0.3–0.5 | 11 | 0.374 | 0.455 | +8.1pp |
| 0.5–0.7 | 17 | 0.592 | 0.765 | +17.3pp |
| 0.7–0.9 | 21 | 0.808 | 0.952 | +14.4pp |
| 0.9–1.0 | 37 | 0.965 | 1.000 | +3.5pp |

### mode = `prior` (n = 31)

- Effective n, by error correlation: **7.0** (lag-1 r = +0.63)
- Effective n, by price-change correlation: **6.5** (lag-1 r = +0.65)
- **Gating on the lower: n_eff = 6.5** (the outcome figure).
- The two figures are close, which means the model is not yet removing much of the day-to-day overlap between consecutive forecasts.

- **Nothing is concludable at n_eff = 6.5.** The numbers below are recorded so the series exists, not because they support a claim. Do not quote them as skill.

| threshold | Brier | vs 0.25 | base rate | n |
|---|---|---|---|---|
| > -2c | 0.0309 | +0.2191 | 0.97 | 31 |
| > -1c | 0.1003 | +0.1497 | 0.87 | 31 |
| > +0c **(headline)** | 0.2518 | -0.0018 | 0.35 | 31 |
| > +1c | 0.1168 | +0.1332 | 0.13 | 31 |
| > +2c | 0.0935 | +0.1565 | 0.10 | 31 |

Judge this system on the `> +0c` row, secondarily `±1c`. The ±2c thresholds routinely resolve before they are asked — a Brier near zero against a base rate of 0 or 1 measures nothing. **Do not average across the grid and quote the result as 'the Brier score'.**

**Predictive distribution**

- PIT mean: **0.437** (target 0.500)
- 80% interval coverage: **77.4%** (target 80.0%)
- Residual sd 1.22c vs claimed sigma 1.00c (ratio 1.22)
- Spread check: **held** at n_eff = 6.5 (needs 20). Errors currently look close to the claimed sigma, but that comparison is not yet evidence.

**Reliability** (pooled across thresholds; bins with n<3 suppressed)

| bin | n | predicted | observed | gap |
|---|---|---|---|---|
| 0.0–0.1 | 36 | 0.033 | 0.111 | +7.8pp |
| 0.1–0.3 | 26 | 0.181 | 0.115 | -6.6pp |
| 0.3–0.5 | 14 | 0.422 | 0.214 | -20.8pp |
| 0.5–0.7 | 17 | 0.568 | 0.471 | -9.7pp |
| 0.7–0.9 | 31 | 0.837 | 0.871 | +3.4pp |
| 0.9–1.0 | 31 | 0.975 | 0.968 | -0.7pp |

## Known limitations

- **The model is deaf to news.** Its worst historical call was a +48.5c week predicted at +6.5c, driven by a geopolitical supply shock. Momentum is a lagging echo when news drives price, not a leading signal. Expect the calibration to degrade in exactly those weeks.
- **`PRIOR_SIGMA_C = 1.0` cents is a guess**, derived loosely from weekly EIA variance. Daily autocorrelation has never been measured. Replacing it with a measured value at n >= 60 is milestone M5.
- **`PRIOR_SHRINK = 0.35` has no empirical basis.** Placeholder, also due to die at M5.

