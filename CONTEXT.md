# CONTEXT.md

_Regenerated 2026-08-11T10:51:08+00:00 by `forecast/score.py`. Do not hand-edit._

This file is the working state of a daily gas-price forecast calibration loop. It is written for two readers: a human skimming, and a fresh Claude session with no memory of this project. If you are the latter, read DESIGN.md next — it holds the reasoning, the rejected alternatives, and the invariants.

## What this system does

Every day a GitHub Actions job scrapes the AAA national average, scores yesterday's forecast against what actually happened, then makes a new forecast for tomorrow. The forecast is not the product — **the calibration record is**. The question being answered is 'when this system says 70%, does it happen about 70% of the time?'

The target is always the **change** in price, never the level, and thresholds are relative to the level at forecast time.

## Data on hand

- Observations: **19**
- Range: `2026-07-24` to `2026-08-11`
- Gaps: **0**
- Forecasts written: **13**
- Forecasts scored: **12**
- Awaiting outcome: **1**

Most recent scored call — `2026-08-11` (`prior` mode): predicted **-0.43c**, actual **+0.25c**, error **+0.68c**.

## What the model is keying on

**Not fitted yet.** The ridge model needs 30 complete training rows and has **11**. Until then every forecast comes from the bootstrap prior, which is a rule of thumb with no coefficients to show.

## Calibration

`prior` and `model` rows are reported separately and never pooled. Prior-mode rows are bootstrap output and say nothing about model skill.

### mode = `prior` (n = 12)

- Effective n, by error correlation: **4.6** (lag-1 r = +0.44)
- Effective n, by price-change correlation: **3.7** (lag-1 r = +0.53)
- **Gating on the lower: n_eff = 3.7** (the outcome figure).

- **Nothing is concludable at n_eff = 3.7.** The numbers below are recorded so the series exists, not because they support a claim. Do not quote them as skill.

| threshold | Brier | vs 0.25 | base rate | n |
|---|---|---|---|---|
| > -2c | 0.0791 | +0.1709 | 0.92 | 12 |
| > -1c | 0.2245 | +0.0255 | 0.67 | 12 |
| > +0c **(headline)** | 0.2345 | +0.0155 | 0.17 | 12 |
| > +1c | 0.0198 | +0.2302 | 0.00 ⚠︎ degenerate | 12 |
| > +2c | 0.0004 | +0.2496 | 0.00 ⚠︎ degenerate | 12 |

Judge this system on the `> +0c` row, secondarily `±1c`. The ±2c thresholds routinely resolve before they are asked — a Brier near zero against a base rate of 0 or 1 measures nothing. **Do not average across the grid and quote the result as 'the Brier score'.**

**Predictive distribution**

- PIT mean: **0.329** (target 0.500)
- 80% interval coverage: **75.0%** (target 80.0%)
- Residual sd 0.88c vs claimed sigma 1.00c (ratio 0.88)
- Spread check: **held** at n_eff = 3.7 (needs 20). Errors currently look close to the claimed sigma, but that comparison is not yet evidence.

**Reliability** (pooled across thresholds; bins with n<3 suppressed)

| bin | n | predicted | observed | gap |
|---|---|---|---|---|
| 0.0–0.1 | 16 | 0.034 | 0.000 | -3.4pp |
| 0.1–0.3 | 8 | 0.159 | 0.000 | -15.9pp |
| 0.3–0.5 | 9 | 0.415 | 0.111 | -30.4pp |
| 0.5–0.7 | 3 | 0.544 | 0.333 | -21.0pp |
| 0.7–0.9 | 12 | 0.801 | 0.667 | -13.5pp |
| 0.9–1.0 | 12 | 0.966 | 0.917 | -4.9pp |

## Known limitations

- **The model is deaf to news.** Its worst historical call was a +48.5c week predicted at +6.5c, driven by a geopolitical supply shock. Momentum is a lagging echo when news drives price, not a leading signal. Expect the calibration to degrade in exactly those weeks.
- **`PRIOR_SIGMA_C = 1.0` cents is a guess**, derived loosely from weekly EIA variance. Daily autocorrelation has never been measured. Replacing it with a measured value at n >= 60 is milestone M5.
- **`PRIOR_SHRINK = 0.35` has no empirical basis.** Placeholder, also due to die at M5.

