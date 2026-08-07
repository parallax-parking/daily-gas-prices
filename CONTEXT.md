# CONTEXT.md

_Regenerated 2026-08-07T14:27:15+00:00 by `forecast/score.py`. Do not hand-edit._

This file is the working state of a daily gas-price forecast calibration loop. It is written for two readers: a human skimming, and a fresh Claude session with no memory of this project. If you are the latter, read DESIGN.md next — it holds the reasoning, the rejected alternatives, and the invariants.

## What this system does

Every day a GitHub Actions job scrapes the AAA national average, scores yesterday's forecast against what actually happened, then makes a new forecast for tomorrow. The forecast is not the product — **the calibration record is**. The question being answered is 'when this system says 70%, does it happen about 70% of the time?'

The target is always the **change** in price, never the level, and thresholds are relative to the level at forecast time.

## Data on hand

- Observations: **9**
- Range: `2026-07-30` to `2026-08-07`
- Gaps: **0**
- Forecasts written: **8**
- Forecasts scored: **8**
- Awaiting outcome: **0**

Most recent scored call — `2026-08-07` (`prior` mode): predicted **-0.17c**, actual **-2.11c**, error **-1.94c**.

## What the model is keying on

**Not fitted yet.** The ridge model needs 30 complete training rows and has **1**. Until then every forecast comes from the bootstrap prior, which is a rule of thumb with no coefficients to show.

## Calibration

`prior` and `model` rows are reported separately and never pooled. Prior-mode rows are bootstrap output and say nothing about model skill.

### mode = `prior` (n = 8)

- Effective n, by error correlation: **4.9** (lag-1 r = +0.24)
- Effective n, by price-change correlation: **3.7** (lag-1 r = +0.36)
- **Gating on the lower: n_eff = 3.7** (the outcome figure).

- **Nothing is concludable at n_eff = 3.7.** The numbers below are recorded so the series exists, not because they support a claim. Do not quote them as skill.

| threshold | Brier | vs 0.25 | base rate | n |
|---|---|---|---|---|
| > -2c | 0.1171 | +0.1329 | 0.88 | 8 |
| > -1c | 0.1798 | +0.0702 | 0.75 | 8 |
| > +0c **(headline)** | 0.2495 | +0.0005 | 0.12 | 8 |
| > +1c | 0.0263 | +0.2237 | 0.00 ⚠︎ degenerate | 8 |
| > +2c | 0.0006 | +0.2494 | 0.00 ⚠︎ degenerate | 8 |

Judge this system on the `> +0c` row, secondarily `±1c`. The ±2c thresholds routinely resolve before they are asked — a Brier near zero against a base rate of 0 or 1 measures nothing. **Do not average across the grid and quote the result as 'the Brier score'.**

**Predictive distribution**

- PIT mean: **0.292** (target 0.500)
- 80% interval coverage: **75.0%** (target 80.0%)
- Residual sd 0.90c vs claimed sigma 1.00c (ratio 0.90)
- Spread check: **held** at n_eff = 3.7 (needs 20). Errors currently look close to the claimed sigma, but that comparison is not yet evidence.

**Reliability** (pooled across thresholds; bins with n<3 suppressed)

| bin | n | predicted | observed | gap |
|---|---|---|---|---|
| 0.0–0.1 | 8 | 0.023 | 0.000 | -2.3pp |
| 0.1–0.3 | 8 | 0.159 | 0.000 | -15.9pp |
| 0.3–0.5 | 5 | 0.469 | 0.000 | -46.9pp |
| 0.5–0.7 | 3 | 0.544 | 0.333 | -21.0pp |
| 0.7–0.9 | 8 | 0.838 | 0.750 | -8.8pp |
| 0.9–1.0 | 8 | 0.976 | 0.875 | -10.1pp |

## Known limitations

- **The model is deaf to news.** Its worst historical call was a +48.5c week predicted at +6.5c, driven by a geopolitical supply shock. Momentum is a lagging echo when news drives price, not a leading signal. Expect the calibration to degrade in exactly those weeks.
- **`PRIOR_SIGMA_C = 1.0` cents is a guess**, derived loosely from weekly EIA variance. Daily autocorrelation has never been measured. Replacing it with a measured value at n >= 60 is milestone M5.
- **`PRIOR_SHRINK = 0.35` has no empirical basis.** Placeholder, also due to die at M5.

