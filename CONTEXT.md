# CONTEXT.md

_Regenerated 2026-09-01T17:20:25+00:00 by `forecast/score.py`. Do not hand-edit._

This file is the working state of a daily gas-price forecast calibration loop. It is written for two readers: a human skimming, and a fresh Claude session with no memory of this project. If you are the latter, read DESIGN.md next — it holds the reasoning, the rejected alternatives, and the invariants.

## What this system does

Every day a GitHub Actions job scrapes the AAA national average, scores yesterday's forecast against what actually happened, then makes a new forecast for tomorrow. The forecast is not the product — **the calibration record is**. The question being answered is 'when this system says 70%, does it happen about 70% of the time?'

The target is always the **change** in price, never the level, and thresholds are relative to the level at forecast time.

## Data on hand

- Observations: **40**
- Range: `2026-07-24` to `2026-09-01`
- Gaps: **0**
- Forecasts written: **34**
- Forecasts scored: **33**
- Awaiting outcome: **1**

Most recent scored call — `2026-09-01` (`model` mode): predicted **+0.03c**, actual **+1.47c**, error **+1.44c**.

## What the model is keying on

Standardised ridge coefficients, refit on all **32** training rows available today. Units are cents of predicted next-day change per one standard deviation of the feature, so the magnitudes are directly comparable to each other.

| feature | weight | what it is |
|---|---|---|
| `d1` | +0.684 | yesterday's change |
| `d2` | -0.290 | the change 2 days ago |
| `vol7` | +0.226 | volatility of the last 7 daily changes |
| `dow` | -0.207 | day of week (of the target) |
| `ma3` | +0.128 | mean of the last 3 daily changes |
| `d3` | -0.080 | the change 3 days ago |
| `wk` | -0.066 | 7-day change |
| `ma7` | -0.066 | mean of the last 7 daily changes |

Largest: `d1` at +0.684, 2.4× the next-largest (`d2`).

DESIGN.md §10 found on weekly data that last period's change dominates everything else by roughly 3×, with the mechanism being staggered repricing — stations don't all move at once, so a shock keeps propagating for days. **If `d1` is not on top here, that is a genuine finding about daily data**, not a bug: it would mean the daily dynamics differ from the weekly ones this design was built on. Worth investigating before trusting the forecasts.

## Calibration

`prior` and `model` rows are reported separately and never pooled. Prior-mode rows are bootstrap output and say nothing about model skill.

### mode = `model` (n = 2)

- Effective n, by error correlation: **2.0** (lag-1 r = +0.00)
- Effective n, by price-change correlation: **2.0** (lag-1 r = +0.00)
- **Gating on the lower: n_eff = 2.0** (the residual figure).

- **Nothing is concludable at n_eff = 2.0.** The numbers below are recorded so the series exists, not because they support a claim. Do not quote them as skill.

| threshold | Brier | vs 0.25 | base rate | n |
|---|---|---|---|---|
| > -2c | 0.0005 | +0.2495 | 1.00 ⚠︎ degenerate | 2 |
| > -1c | 0.0253 | +0.2247 | 1.00 ⚠︎ degenerate | 2 |
| > +0c **(headline)** | 0.2520 | -0.0020 | 1.00 ⚠︎ degenerate | 2 |
| > +1c | 0.3611 | -0.1111 | 0.50 | 2 |
| > +2c | 0.0005 | +0.2495 | 0.00 ⚠︎ degenerate | 2 |

Judge this system on the `> +0c` row, secondarily `±1c`. The ±2c thresholds routinely resolve before they are asked — a Brier near zero against a base rate of 0 or 1 measures nothing. **Do not average across the grid and quote the result as 'the Brier score'.**

**Predictive distribution**

- PIT mean: **0.761** (target 0.500)
- 80% interval coverage: **50.0%** (target 80.0%)
- Residual sd 0.90c vs claimed sigma 0.99c (ratio 0.90)
- Spread check: **held** at n_eff = 2.0 (needs 20). Errors currently look close to the claimed sigma, but that comparison is not yet evidence.

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

