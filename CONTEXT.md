# CONTEXT.md

_Regenerated 2026-07-31T12:31:29+00:00 by `forecast/score.py`. Do not hand-edit._

This file is the working state of a daily gas-price forecast calibration loop. It is written for two readers: a human skimming, and a fresh Claude session with no memory of this project. If you are the latter, read DESIGN.md next — it holds the reasoning, the rejected alternatives, and the invariants.

## What this system does

Every day a GitHub Actions job scrapes the AAA national average, scores yesterday's forecast against what actually happened, then makes a new forecast for tomorrow. The forecast is not the product — **the calibration record is**. The question being answered is 'when this system says 70%, does it happen about 70% of the time?'

The target is always the **change** in price, never the level, and thresholds are relative to the level at forecast time.

## Data on hand

- Observations: **1**
- Range: `2026-07-30` to `2026-07-30`
- Gaps: **0**
- Forecasts written: **1**
- Forecasts scored: **0**
- Awaiting outcome: **1**

## What the model is keying on

**Not fitted yet.** The ridge model needs 30 complete training rows and has **0**. Until then every forecast comes from the bootstrap prior, which is a rule of thumb with no coefficients to show.

## Calibration

**Nothing scored yet.** This is the expected state for the first day or two of operation: a forecast can only be scored once its target date has been observed, which is the following day at the earliest. No numbers below because there is nothing honest to put there.

## What to do next

Nothing. Let it run. The first scored forecast appears the day after the first forecast is written. Meaningful calibration needs n_eff >= 20, realistically a month or more of daily observations.

