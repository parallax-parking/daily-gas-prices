# CONTEXT.md

_Regenerated 2026-11-09T22:59:53+00:00 by `forecast/score.py`. Do not hand-edit._

This file is the working state of a daily gas-price forecast calibration loop. It is written for two readers: a human skimming, and a fresh Claude session with no memory of this project. If you are the latter, read DESIGN.md next — it holds the reasoning, the rejected alternatives, and the invariants.

## What this system does

Every day a GitHub Actions job scrapes the AAA national average, scores yesterday's forecast against what actually happened, then makes a new forecast for tomorrow. The forecast is not the product — **the calibration record is**. The question being answered is 'when this system says 70%, does it happen about 70% of the time?'

The target is always the **change** in price, never the level, and thresholds are relative to the level at forecast time.

## Data on hand

- Observations: **109**
- Range: `2026-07-24` to `2026-11-09`
- Gaps: **0**
- Forecasts written: **103**
- Forecasts scored: **102**
- Awaiting outcome: **1**

Most recent scored call — `2026-11-09` (`model` mode): predicted **-1.17c**, actual **-1.10c**, error **+0.07c**.

## What the model is keying on

Standardised ridge coefficients, refit on all **101** training rows available today. Units are cents of predicted next-day change per one standard deviation of the feature, so the magnitudes are directly comparable to each other.

| feature | weight | what it is |
|---|---|---|
| `d1` | +1.180 | yesterday's change |
| `d2` | -0.521 | the change 2 days ago |
| `ma7` | +0.256 | mean of the last 7 daily changes |
| `wk` | +0.256 | 7-day change |
| `ma3` | +0.219 | mean of the last 3 daily changes |
| `dow` | -0.119 | day of week (of the target) |
| `d3` | -0.105 | the change 3 days ago |
| `vol7` | -0.092 | volatility of the last 7 daily changes |

Largest: `d1` at +1.180, 2.3× the next-largest (`d2`).

DESIGN.md §10 found on weekly data that last period's change dominates everything else by roughly 3×, with the mechanism being staggered repricing — stations don't all move at once, so a shock keeps propagating for days. **If `d1` is not on top here, that is a genuine finding about daily data**, not a bug: it would mean the daily dynamics differ from the weekly ones this design was built on. Worth investigating before trusting the forecasts.

## Calibration

`prior` and `model` rows are reported separately and never pooled. Prior-mode rows are bootstrap output and say nothing about model skill.

### mode = `model` (n = 71)

- Effective n, by error correlation: **62.5** (lag-1 r = +0.06)
- Effective n, by price-change correlation: **11.9** (lag-1 r = +0.71)
- **Gating on the lower: n_eff = 11.9** (the outcome figure).

- **Nothing is concludable at n_eff = 11.9.** The numbers below are recorded so the series exists, not because they support a claim. Do not quote them as skill.

| threshold | Brier | vs 0.25 | base rate | n |
|---|---|---|---|---|
| > -2c | 0.0996 | +0.1504 | 0.85 | 71 |
| > -1c | 0.1302 | +0.1198 | 0.68 | 71 |
| > +0c **(headline)** | 0.1538 | +0.0962 | 0.41 | 71 |
| > +1c | 0.1204 | +0.1296 | 0.18 | 71 |
| > +2c | 0.0778 | +0.1722 | 0.11 | 71 |

Judge this system on the `> +0c` row, secondarily `±1c`. The ±2c thresholds routinely resolve before they are asked — a Brier near zero against a base rate of 0 or 1 measures nothing. **Do not average across the grid and quote the result as 'the Brier score'.**

**Predictive distribution**

- PIT mean: **0.466** (target 0.500)
- 80% interval coverage: **91.5%** (target 80.0%)
- Residual sd 2.01c vs claimed sigma 1.66c (ratio 1.21)
- Spread check: **held** at n_eff = 11.9 (needs 20). Errors currently look close to the claimed sigma, but that comparison is not yet evidence.

**Reliability** (pooled across thresholds; bins with n<3 suppressed)

| bin | n | predicted | observed | gap |
|---|---|---|---|---|
| 0.0–0.1 | 60 | 0.043 | 0.017 | -2.6pp |
| 0.1–0.3 | 66 | 0.194 | 0.106 | -8.8pp |
| 0.3–0.5 | 54 | 0.387 | 0.204 | -18.4pp |
| 0.5–0.7 | 62 | 0.599 | 0.581 | -1.8pp |
| 0.7–0.9 | 62 | 0.802 | 0.839 | +3.6pp |
| 0.9–1.0 | 51 | 0.955 | 1.000 | +4.5pp |

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

## Flagged regime windows

Stretches the weekly review flagged as a regime the model does not cover — single-day moves past ±5c, where news rather than diffusion is driving price. Recorded in `data/regime_windows.csv` (append-only). **Annotation only:** rows inside a window are scored exactly like every other row and are never excluded or down-weighted. The point is that a reviewer reading the calibration numbers above at higher n_eff can attribute error in these stretches to a known shock instead of reading it as drift or noise.

### `2026-09-08` to `2026-09-20` — issue #9

Upward run with three single-day moves past +5c (09-09, 09-10, 09-17) after roughly nine near-flat days. Momentum picked the run up late and light rather than missing it outright, so this is the milder form of the deaf-to-news failure. Flagged by the weekly review; no model, feature, or constant was changed.

- Observed days in window: **13**
- Largest single-day move: **+7.31c** on `2026-09-09`
- Cumulative change, last close before the window to its last day: **+32.56c**
- `model` mode: 13 scored forecast(s) inside, mean absolute error 1.69c (mean error +0.64c, i.e. the model undershot on average) vs 0.77c across the 58 model-mode row(s) outside every flagged window.

## Known limitations

- **The model is deaf to news.** Its worst historical call was a +48.5c week predicted at +6.5c, driven by a geopolitical supply shock. Momentum is a lagging echo when news drives price, not a leading signal. Expect the calibration to degrade in exactly those weeks — the flagged regime windows above are where that has happened in the daily record so far.
- **The prior constants are measured on one regime.** M5 (2026-10-31) replaced the guessed `PRIOR_SIGMA_C`/`PRIOR_SHRINK` with values measured on 98 daily changes (sigma 1.60c, shrink 0.69, daily lag-1 rho +0.666) — a record that includes one news-driven window. They only matter if the bootstrap ever runs again; re-measure with `forecast/measure_prior.py` before trusting them on a new grade or series.

