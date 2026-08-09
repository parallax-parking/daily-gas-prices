# forecast/

A daily probabilistic forecast of the change in the AAA national average, and
an auditable record of how well calibrated it is.

**The forecast is not the product. The calibration record is.** A forecast that
happens to be right is worth less than one whose reliability can be quantified.
See [`DESIGN.md`](../DESIGN.md) for the full rationale, the measured results
behind the model choices, and the alternatives already tried and rejected.

Current state of the system is always in [`CONTEXT.md`](../CONTEXT.md), which is
regenerated on every run.

## Layout

| file | role |
|---|---|
| `features.py` | Causal feature construction. Pure functions of observations dated ≤ `made_on`. |
| `model.py` | Ridge fit/predict, plus the bootstrap prior used before 30 training rows exist. |
| `thresholds.py` | The threshold grid, shared by writer and scorer. |
| `forecast.py` | CLI. Appends exactly one immutable forecast row. |
| `score.py` | CLI. Joins forecasts to outcomes, scores them, regenerates `CONTEXT.md` and the dashboard. |
| `dashboard.py` | Renders the GitHub Pages page. Named `dashboard` and not `site` because `import site` resolves to Python's stdlib module. |

## Running it

```sh
pip install -r forecast/requirements.txt

python forecast/score.py    --out CONTEXT.md --site docs/index.html   # score first
python forecast/forecast.py --out data/forecasts.csv    # then forecast
```

**Order matters.** Scoring consumes the reading that just landed; forecasting
takes that same reading as an input. Reversed, you score a forecast against its
own input and the record is quietly worthless.

## The invariants

These are not style preferences. Violating any of them destroys the value of
the record, usually without raising an error.

1. **A forecast row is written before its outcome exists, and is never edited.**
   Git commit timestamps are the proof. To change the model, bump
   `MODEL_VERSION` in `model.py` and leave the old rows standing.
2. **`forecast.py` never sees the value it is predicting.** Its only input is
   the observations CSV as of the current commit.
3. **No LLM in the forecast path.** Deterministic code, pinned model version. An
   agent that reasons freshly each morning is a moving target, and a Brier score
   against a moving target measures nothing. Agents belong in the review layer.
4. **Score before forecast, within a run.**
5. **Thresholds are relative to the level at forecast time**, never absolute.
   Absolute thresholds make each day a structurally different bet — some already
   resolved before being asked — and pooling those into a reliability curve is
   meaningless.

## Reading the output

Judge the system on the **`> +0c`** threshold, secondarily `±1c`. The `±2c`
thresholds routinely resolve before they are asked; a Brier near zero against a
base rate of 0 or 1 measures nothing. Do not average across the grid and quote
the result as "the Brier score."

Three guards `CONTEXT.md` applies automatically:

- **`prior` and `model` rows are never pooled.** Bootstrap output says nothing
  about model skill.
- **Sample size is reported as `n_eff`, not `n`.** Consecutive daily forecasts
  are very nearly the same bet. Below `n_eff = 20` the report states plainly
  that nothing is concludable, rather than printing a number that invites
  over-reading.

  `n_eff` is computed two ways — from how correlated the *errors* are, and from
  how correlated the *price changes* are — and conclusions gate on the lower of
  the two. The first relaxes as the model improves; the second stays pinned near
  a constant fraction of `n` because gas prices are autocorrelated whether or
  not the model is any good. When the two figures sit close together, the model
  is not yet removing the overlap between consecutive days, and `CONTEXT.md`
  says so.

- **The spread check runs in both directions.** Residual sd more than 1.25×
  the claimed sigma is overconfidence — intervals narrower than the errors
  justify. Below 0.75× is underconfidence — intervals so wide that every
  probability drifts toward 50% and the forecast stops telling one day from
  another. The second failure is easy to miss precisely because it never looks
  wrong. Both are gated at `n_eff >= 20`; below that the report says the check
  is held rather than firing on noise.

## Known limitations

- **The model is deaf to news.** Its worst call in 160 holdout weeks was
  2026-03-09: actual +48.5c, predicted +6.5c — a geopolitical supply shock, and
  the second-largest weekly move in the 33-year record. When news drives price
  rather than diffusion, momentum is a lagging echo, not a leading signal.
- **`PRIOR_SIGMA_C = 1.0` cents is a guess.** It comes from weekly EIA variance,
  which pins the daily figure only loosely. The daily autocorrelation ρ it
  depends on has never been measured — doing so is the main scientific output of
  the first two months.
- **`PRIOR_SHRINK = 0.35` has no empirical basis at all.** Placeholder.

Both constants are due to be replaced with measured values once n ≥ 60.
