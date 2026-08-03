#!/usr/bin/env python3
"""Join forecasts to outcomes, score them, and regenerate CONTEXT.md.

The calibration record is the product (DESIGN.md §1). This file is what makes
it auditable.

Two things it is careful about, both of which quietly destroy the record if got
wrong:

  - `prior` and `model` rows are scored as separate populations and never
    pooled into a headline number. Prior-mode rows are not evidence about model
    skill (§6.5).
  - Sample size is reported as n_eff, not n. Consecutive daily forecasts are
    very nearly the same bet, so nominal n overstates the evidence — often by a
    factor of several (§7).

Usage:
    python forecast/score.py --out CONTEXT.md
"""

from __future__ import annotations

import argparse
import csv
import math
import statistics
import sys
from datetime import date as date_cls
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import features as feat  # noqa: E402
from thresholds import (  # noqa: E402
    HEADLINE_THRESHOLD_C,
    PROB_COLUMNS,
    THRESHOLDS_C,
    threshold_key,
)

# A coin-flip forecaster scores 0.25. Everything is quoted against that.
NO_SKILL_BRIER = 0.25

RELIABILITY_BINS = [0.0, 0.1, 0.3, 0.5, 0.7, 0.9, 1.0]
MIN_BIN_COUNT = 3

# Below this many effective observations, nothing is concludable and the report
# must say so rather than printing a number that invites over-reading.
N_EFF_NOTHING = 20
N_EFF_DIRECTIONAL = 50

# Residual spread this much larger than claimed sigma means the model is
# advertising more precision than it has.
OVERCONFIDENCE_RATIO = 1.25

# ...and this much smaller means the opposite: intervals wider than the errors
# justify. Less dangerous than overconfidence — a vague forecast misleads nobody
# — but still miscalibration, and it makes every probability drift toward 50%,
# which is the same as having no opinion. Both bands are deliberately loose so
# ordinary sampling noise doesn't trip them.
UNDERCONFIDENCE_RATIO = 0.75

# Neither flag fires below this many effective observations. A residual sd
# computed from a handful of correlated days says nothing about sigma, and a
# flag that cries wolf in month one is a flag nobody reads in month six.
MIN_N_EFF_FOR_SPREAD_FLAG = N_EFF_NOTHING


def normal_cdf(z: float) -> float:
    return 0.5 * math.erfc(-z / math.sqrt(2.0))


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def as_float(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def join(
    forecasts: list[dict[str, str]], prices: dict[date_cls, float]
) -> list[dict[str, object]]:
    """Attach the realised change to every forecast whose target has landed."""
    scored = []
    for row in forecasts:
        try:
            target = date_cls.fromisoformat(row["target_date"])
        except (KeyError, ValueError):
            continue

        actual_level = prices.get(target)
        level_at_forecast = as_float(row.get("level_at_forecast"))
        mu = as_float(row.get("mu_cents"))
        sigma = as_float(row.get("sigma_cents"))
        if actual_level is None or level_at_forecast is None or mu is None or sigma is None:
            continue

        actual_change = actual_level - level_at_forecast * 100.0
        scored.append(
            {
                "target_date": row["target_date"],
                "mode": row.get("mode", "unknown"),
                "model_version": row.get("model_version", "unknown"),
                "actual_c": actual_change,
                "mu_c": mu,
                "sigma_c": sigma,
                "z": (actual_change - mu) / sigma if sigma > 0 else 0.0,
                "probs": {
                    column: as_float(row.get(column)) for column in PROB_COLUMNS
                },
            }
        )
    return scored


def lag1_autocorr(values: list[float]) -> float:
    if len(values) < 3:
        return 0.0
    mean = statistics.fmean(values)
    numerator = sum(
        (values[i] - mean) * (values[i + 1] - mean) for i in range(len(values) - 1)
    )
    denominator = sum((v - mean) ** 2 for v in values)
    if denominator == 0:
        return 0.0
    return max(-0.99, min(0.99, numerator / denominator))


def effective_n(values: list[float]) -> tuple[float, float]:
    """n_eff = n(1-r)/(1+r) on the lag-1 autocorrelation of the z series.

    Daily forecasts made one day apart share almost all of their inputs, so
    treating them as independent trials overstates the evidence. Returns
    (n_eff, r).
    """
    n = len(values)
    if n < 3:
        return float(n), 0.0
    r = lag1_autocorr(values)
    # Negative autocorrelation drives the formula above n. Anti-correlated
    # errors genuinely do carry more information per observation, but claiming
    # more independent evidence than there are observations is not a claim this
    # report should make, so n is a hard ceiling.
    return min(float(n), max(1.0, n * (1 - r) / (1 + r))), r


def sample_size(rows: list[dict[str, object]]) -> dict[str, float]:
    """Effective sample size, computed two ways, gated on the lower.

    There is a real choice about which series carries the overlap between
    consecutive forecasts, and the two answers diverge by a factor of ~2.5:

      - **residual** — how correlated the system's *errors* are. If the model
        genuinely captures momentum, its errors decorrelate and n_eff
        approaches n. Risks overstating the evidence when errors only look
        independent.
      - **outcome** — how correlated the *price changes themselves* are. Gas
        prices are persistently autocorrelated whether or not the model is any
        good, so this pins the discount near a constant fraction of n. Risks
        sitting on a sound result for months.

    Reporting both costs nothing and the gap between them is informative in its
    own right: if they stay close, the model is not actually removing the
    day-to-day overlap, which neither number alone would tell you. Conclusions
    gate on the smaller, so the cautious reading always wins.
    """
    n_resid, r_resid = effective_n([row["z"] for row in rows])
    n_outcome, r_outcome = effective_n([row["actual_c"] for row in rows])
    return {
        "n": float(len(rows)),
        "residual": n_resid,
        "residual_r": r_resid,
        "outcome": n_outcome,
        "outcome_r": r_outcome,
        "binding": min(n_resid, n_outcome),
        "binding_name": "residual" if n_resid <= n_outcome else "outcome",
    }


def brier(scored: list[dict[str, object]], threshold_c: float) -> dict[str, float] | None:
    column = f"p_gt_{threshold_key(threshold_c)}"
    pairs = [
        (row["probs"][column], 1.0 if row["actual_c"] > threshold_c else 0.0)
        for row in scored
        if row["probs"].get(column) is not None
    ]
    if not pairs:
        return None
    return {
        "brier": statistics.fmean((p - o) ** 2 for p, o in pairs),
        "base_rate": statistics.fmean(o for _, o in pairs),
        "n": len(pairs),
    }


def reliability(scored: list[dict[str, object]]) -> list[dict[str, float]]:
    """Pooled across thresholds — bin counts are otherwise unusable for months."""
    pairs: list[tuple[float, float]] = []
    for row in scored:
        for threshold, column in zip(THRESHOLDS_C, PROB_COLUMNS):
            probability = row["probs"].get(column)
            if probability is not None:
                pairs.append((probability, 1.0 if row["actual_c"] > threshold else 0.0))

    out = []
    for low, high in zip(RELIABILITY_BINS, RELIABILITY_BINS[1:]):
        bucket = [
            (p, o) for p, o in pairs if (low <= p < high or (high == 1.0 and p == 1.0))
        ]
        if len(bucket) < MIN_BIN_COUNT:
            continue
        predicted = statistics.fmean(p for p, _ in bucket)
        observed = statistics.fmean(o for _, o in bucket)
        out.append(
            {
                "low": low,
                "high": high,
                "n": len(bucket),
                "predicted": predicted,
                "observed": observed,
                "gap_pp": (observed - predicted) * 100.0,
            }
        )
    return out


def pit_summary(scored: list[dict[str, object]]) -> dict[str, float] | None:
    if not scored:
        return None
    pits = [normal_cdf(row["z"]) for row in scored]
    inside = [1.0 if 0.1 <= p <= 0.9 else 0.0 for p in pits]
    residuals = [row["actual_c"] for row in scored]
    claimed = statistics.fmean(row["sigma_c"] for row in scored)
    residual_sd = statistics.stdev(residuals) if len(residuals) > 1 else float("nan")
    return {
        "mean": statistics.fmean(pits),
        "coverage80": statistics.fmean(inside) * 100.0,
        "claimed_sigma": claimed,
        "residual_sd": residual_sd,
        "ratio": residual_sd / claimed if claimed > 0 else float("nan"),
    }


FEATURE_GLOSS = {
    "d1": "yesterday's change",
    "d2": "the change 2 days ago",
    "d3": "the change 3 days ago",
    "ma3": "mean of the last 3 daily changes",
    "ma7": "mean of the last 7 daily changes",
    "vol7": "volatility of the last 7 daily changes",
    "wk": "7-day change",
    "dow": "day of week (of the target)",
}


def current_coefficients(
    prices: dict[date_cls, float]
) -> tuple[list[tuple[str, float]] | None, int]:
    """Refit on everything observed so far and return the standardised weights.

    Computed fresh at report time rather than stored per forecast row: this
    answers "what does the model believe *now*", which is a property of the
    current data, not of any one past prediction. Storing it per row would also
    put eight numbers on every line of an append-only file to say something that
    barely changes day to day.

    Returns (weights_sorted_by_magnitude, n_train); weights is None when there
    is not yet enough history to fit.
    """
    if not prices:
        return None, 0

    rows, targets = feat.training_set(prices, max(prices))
    try:
        import model as mdl  # noqa: PLC0415 — keep numpy off the import path
    except ImportError:
        # numpy missing. The rest of the report is still worth producing;
        # a missing optional section beats no CONTEXT.md at all.
        return None, len(targets)

    if len(targets) < mdl.MIN_TRAIN:
        return None, len(targets)

    weights = mdl.coefficients(rows, targets)
    pairs = list(zip(feat.FEATURE_NAMES, weights))
    pairs.sort(key=lambda pair: abs(pair[1]), reverse=True)
    return pairs, len(targets)


def spread_verdict(ratio: float, n_eff: float) -> str:
    """One line on whether sigma matches the errors it is supposed to describe.

    Miscalibration runs in both directions and the report used to name only one
    of them. Overconfidence — intervals narrower than the errors justify — is
    the dangerous side, because it invites acting on precision that isn't there.
    Underconfidence is the quieter failure: every probability drifts toward 50%,
    the forecast stops distinguishing between days, and it looks well behaved
    the whole time because it is never badly wrong.

    Both are gated on n_eff. A residual sd from a handful of correlated days is
    noise, and a flag that fires in week one is a flag nobody reads in month six.
    """
    if math.isnan(ratio):
        return "- Spread check: not enough scored forecasts to compare yet."

    if n_eff < MIN_N_EFF_FOR_SPREAD_FLAG:
        # Subject of the sentence is the errors, not the intervals, and the two
        # run opposite ways: ratio = residual_sd / sigma, so a high ratio means
        # errors *wider* than sigma (and therefore intervals too narrow).
        direction = (
            "wider than"
            if ratio > OVERCONFIDENCE_RATIO
            else "narrower than" if ratio < UNDERCONFIDENCE_RATIO else "close to"
        )
        return (
            f"- Spread check: **held** at n_eff = {n_eff:.1f} (needs "
            f"{MIN_N_EFF_FOR_SPREAD_FLAG}). Errors currently look {direction} "
            "the claimed sigma, but that comparison is not yet evidence."
        )

    if ratio > OVERCONFIDENCE_RATIO:
        return (
            f"- ⚠︎ **Overconfident.** Residual spread is {ratio:.2f}× the claimed "
            f"sigma, past the {OVERCONFIDENCE_RATIO}× line. The intervals are "
            "narrower than the errors justify, so the stated probabilities "
            "promise more precision than the model has."
        )
    if ratio < UNDERCONFIDENCE_RATIO:
        return (
            f"- ⚠︎ **Underconfident.** Residual spread is {ratio:.2f}× the "
            f"claimed sigma, below the {UNDERCONFIDENCE_RATIO}× line. The "
            "intervals are wider than the errors justify, which pulls every "
            "threshold probability toward 50% and costs the forecast its "
            "ability to distinguish one day from another. Less harmful than "
            "overconfidence, but it means sigma is set too high — see M5."
        )
    return (
        f"- Spread looks right: residual sd is {ratio:.2f}× the claimed sigma, "
        f"inside the {UNDERCONFIDENCE_RATIO}–{OVERCONFIDENCE_RATIO}× band."
    )


def fmt(value: float | None, places: int = 3) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "n/a"
    return f"{value:.{places}f}"


def cents(value: float | None, places: int = 2) -> str:
    """Like fmt, but the unit rides along so "n/a" doesn't come out as "n/ac"."""
    text = fmt(value, places)
    return text if text == "n/a" else f"{text}c"


def render(
    scored: list[dict[str, object]],
    prices: dict[date_cls, float],
    forecasts: list[dict[str, str]],
    pending: list[dict[str, str]],
) -> str:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    lines: list[str] = []
    add = lines.append

    add("# CONTEXT.md")
    add("")
    add(f"_Regenerated {now} by `forecast/score.py`. Do not hand-edit._")
    add("")
    add(
        "This file is the working state of a daily gas-price forecast "
        "calibration loop. It is written for two readers: a human skimming, and "
        "a fresh Claude session with no memory of this project. If you are the "
        "latter, read DESIGN.md next — it holds the reasoning, the rejected "
        "alternatives, and the invariants."
    )
    add("")

    add("## What this system does")
    add("")
    add(
        "Every day a GitHub Actions job scrapes the AAA national average, scores "
        "yesterday's forecast against what actually happened, then makes a new "
        "forecast for tomorrow. The forecast is not the product — **the "
        "calibration record is**. The question being answered is 'when this "
        "system says 70%, does it happen about 70% of the time?'"
    )
    add("")
    add(
        "The target is always the **change** in price, never the level, and "
        "thresholds are relative to the level at forecast time."
    )
    add("")

    add("## Data on hand")
    add("")
    observed = sorted(prices)
    add(f"- Observations: **{len(observed)}**")
    if observed:
        add(f"- Range: `{observed[0]}` to `{observed[-1]}`")
        gaps = [
            (observed[i - 1], observed[i])
            for i in range(1, len(observed))
            if (observed[i] - observed[i - 1]).days > 1
        ]
        add(f"- Gaps: **{len(gaps)}**" + (f" — {gaps[:5]}" if gaps else ""))
    add(f"- Forecasts written: **{len(forecasts)}**")
    add(f"- Forecasts scored: **{len(scored)}**")
    add(f"- Awaiting outcome: **{len(pending)}**")
    add("")

    if scored:
        # One concrete call, stated plainly. A fresh reader gets something they
        # can check against reality before wading into any aggregate.
        latest = max(scored, key=lambda r: r["target_date"])
        error = latest["actual_c"] - latest["mu_c"]
        add(
            f"Most recent scored call — `{latest['target_date']}` "
            f"(`{latest['mode']}` mode): predicted **{latest['mu_c']:+.2f}c**, "
            f"actual **{latest['actual_c']:+.2f}c**, error **{error:+.2f}c**."
        )
        add("")

    # --- what the model is currently keying on ----------------------------
    weights, n_train = current_coefficients(prices)
    add("## What the model is keying on")
    add("")
    if weights is None:
        add(
            "**Not fitted yet.** The ridge model needs 30 complete training "
            f"rows and has **{n_train}**. Until then every forecast comes from "
            "the bootstrap prior, which is a rule of thumb with no coefficients "
            "to show."
        )
    else:
        add(
            f"Standardised ridge coefficients, refit on all **{n_train}** "
            "training rows available today. Units are cents of predicted "
            "next-day change per one standard deviation of the feature, so the "
            "magnitudes are directly comparable to each other."
        )
        add("")
        add("| feature | weight | what it is |")
        add("|---|---|---|")
        for name, weight in weights:
            add(f"| `{name}` | {weight:+.3f} | {FEATURE_GLOSS.get(name, '')} |")
        add("")
        top, second = weights[0], weights[1] if len(weights) > 1 else None
        add(
            f"Largest: `{top[0]}` at {top[1]:+.3f}"
            + (
                f", {abs(top[1]) / abs(second[1]):.1f}× the next-largest "
                f"(`{second[0]}`)."
                if second and abs(second[1]) > 1e-9
                else "."
            )
        )
        add("")
        add(
            "DESIGN.md §10 found on weekly data that last period's change "
            "dominates everything else by roughly 3×, with the mechanism being "
            "staggered repricing — stations don't all move at once, so a shock "
            "keeps propagating for days. **If `d1` is not on top here, that is "
            "a genuine finding about daily data**, not a bug: it would mean the "
            "daily dynamics differ from the weekly ones this design was built "
            "on. Worth investigating before trusting the forecasts."
        )
    add("")

    if not scored:
        add("## Calibration")
        add("")
        add(
            "**Nothing scored yet.** This is the expected state for the first "
            "day or two of operation: a forecast can only be scored once its "
            "target date has been observed, which is the following day at the "
            "earliest. No numbers below because there is nothing honest to put "
            "there."
        )
        add("")
        add("## What to do next")
        add("")
        add(
            "Nothing. Let it run. The first scored forecast appears the day "
            "after the first forecast is written. Meaningful calibration needs "
            f"n_eff >= {N_EFF_NOTHING}, realistically a month or more of daily "
            "observations."
        )
        add("")
        return "\n".join(lines) + "\n"

    by_mode = {
        "model": [r for r in scored if r["mode"] == "model"],
        "prior": [r for r in scored if r["mode"] == "prior"],
    }

    add("## Calibration")
    add("")
    add(
        "`prior` and `model` rows are reported separately and never pooled. "
        "Prior-mode rows are bootstrap output and say nothing about model skill."
    )
    add("")

    for mode, rows in by_mode.items():
        if not rows:
            continue
        size = sample_size(rows)
        n_eff = size["binding"]

        add(f"### mode = `{mode}` (n = {len(rows)})")
        add("")
        add(
            f"- Effective n, by error correlation: **{size['residual']:.1f}** "
            f"(lag-1 r = {size['residual_r']:+.2f})"
        )
        add(
            f"- Effective n, by price-change correlation: "
            f"**{size['outcome']:.1f}** (lag-1 r = {size['outcome_r']:+.2f})"
        )
        add(
            f"- **Gating on the lower: n_eff = {n_eff:.1f}** "
            f"(the {size['binding_name']} figure)."
        )
        if size["n"] >= 3 and size["outcome"] > 0:
            ratio = size["residual"] / size["outcome"]
            if ratio < 1.25:
                add(
                    "- The two figures are close, which means the model is not "
                    "yet removing much of the day-to-day overlap between "
                    "consecutive forecasts."
                )
        add("")

        if n_eff < N_EFF_NOTHING:
            add(
                f"- **Nothing is concludable at n_eff = {n_eff:.1f}.** The "
                "numbers below are recorded so the series exists, not because "
                "they support a claim. Do not quote them as skill."
            )
        elif n_eff < N_EFF_DIRECTIONAL:
            add(
                f"- **Directional read only** at n_eff = {n_eff:.1f}. Treat any "
                "gap under 10 percentage points as noise."
            )
        else:
            add(
                f"- n_eff = {n_eff:.1f} supports a first honest calibration read."
            )
        add("")

        add("| threshold | Brier | vs 0.25 | base rate | n |")
        add("|---|---|---|---|---|")
        for threshold in THRESHOLDS_C:
            result = brier(rows, threshold)
            if result is None:
                continue
            skill = NO_SKILL_BRIER - result["brier"]
            flag = ""
            if result["base_rate"] in (0.0, 1.0):
                flag = " ⚠︎ degenerate"
            headline = " **(headline)**" if threshold == HEADLINE_THRESHOLD_C else ""
            add(
                f"| > {threshold:+.0f}c{headline} | {result['brier']:.4f} | "
                f"{skill:+.4f} | {result['base_rate']:.2f}{flag} | {result['n']} |"
            )
        add("")
        add(
            "Judge this system on the `> +0c` row, secondarily `±1c`. The ±2c "
            "thresholds routinely resolve before they are asked — a Brier near "
            "zero against a base rate of 0 or 1 measures nothing. **Do not "
            "average across the grid and quote the result as 'the Brier "
            "score'.**"
        )
        add("")

        pit = pit_summary(rows)
        if pit:
            add("**Predictive distribution**")
            add("")
            add(f"- PIT mean: **{fmt(pit['mean'])}** (target 0.500)")
            add(
                f"- 80% interval coverage: **{fmt(pit['coverage80'], 1)}%** "
                "(target 80.0%)"
            )
            add(
                f"- Residual sd {cents(pit['residual_sd'])} vs claimed sigma "
                f"{cents(pit['claimed_sigma'])} (ratio {fmt(pit['ratio'], 2)})"
            )
            add(spread_verdict(pit["ratio"], n_eff))
            add("")

        curve = reliability(rows)
        if curve:
            add("**Reliability** (pooled across thresholds; bins with n<3 suppressed)")
            add("")
            add("| bin | n | predicted | observed | gap |")
            add("|---|---|---|---|---|")
            for entry in curve:
                add(
                    f"| {entry['low']:.1f}–{entry['high']:.1f} | {entry['n']} | "
                    f"{entry['predicted']:.3f} | {entry['observed']:.3f} | "
                    f"{entry['gap_pp']:+.1f}pp |"
                )
            add("")

    add("## Known limitations")
    add("")
    add(
        "- **The model is deaf to news.** Its worst historical call was a "
        "+48.5c week predicted at +6.5c, driven by a geopolitical supply shock. "
        "Momentum is a lagging echo when news drives price, not a leading "
        "signal. Expect the calibration to degrade in exactly those weeks."
    )
    add(
        "- **`PRIOR_SIGMA_C = 1.0` cents is a guess**, derived loosely from "
        "weekly EIA variance. Daily autocorrelation has never been measured. "
        "Replacing it with a measured value at n >= 60 is milestone M5."
    )
    add(
        "- **`PRIOR_SHRINK = 0.35` has no empirical basis.** Placeholder, also "
        "due to die at M5."
    )
    add("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--observations", type=Path, default=Path("data/aaa_national_average.csv")
    )
    parser.add_argument("--forecasts", type=Path, default=Path("data/forecasts.csv"))
    parser.add_argument("--out", type=Path, default=Path("CONTEXT.md"))
    parser.add_argument("--grade", default="regular")
    args = parser.parse_args(argv)

    prices = feat.load_observations(args.observations, args.grade)
    forecasts = [
        r for r in read_csv(args.forecasts) if r.get("grade", "regular") == args.grade
    ]
    scored = join(forecasts, prices)
    scored_dates = {row["target_date"] for row in scored}
    pending = [r for r in forecasts if r.get("target_date") not in scored_dates]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(scored, prices, forecasts, pending), encoding="utf-8")

    print(
        f"scored {len(scored)} of {len(forecasts)} forecast(s); "
        f"{len(pending)} awaiting outcome -> {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
