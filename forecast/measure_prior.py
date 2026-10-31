#!/usr/bin/env python3
"""Measure the prior constants from the daily record (DESIGN.md §8, M5).

Until M5, `PRIOR_SIGMA_C` and `PRIOR_SHRINK` in model.py were labelled guesses:
sigma derived loosely from weekly EIA variance, shrink a pure placeholder.
This script replaces guessing with measurement, from the same observations CSV
the forecasts are built on. It prints; it changes nothing. The measured values
are transcribed by hand into model.py and DESIGN.md §0/§6.5/§8, with the
measurement date and n, so the constants stay pinned and inspectable rather
than drifting silently with each run.

What is measured, on consecutive-day changes in cents:

  sigma_daily   sample sd of daily changes — the unconditional spread.
  rho1          lag-1 autocorrelation of daily changes — the quantity §6.5
                says had never been measured on daily data.
  shrink        OLS slope (through the origin, matching the prior's form
                mu = shrink * mean(last 7 changes)) of the next-day change on
                the trailing 7-day mean change.
  sigma_prior   sd of the residuals around that shrunk-mean predictor — the
                honest spread of the prior's own one-step errors, which is
                what PRIOR_SIGMA_C claims to be.

Regime windows (news-driven stretches, data/regime_windows.csv) are annotation
only everywhere else in this project and are not excluded here either; the
prior must live in the same weather as the forecasts it bootstraps.

Usage:
    python forecast/measure_prior.py --observations data/aaa_national_average.csv
"""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import features as feat  # noqa: E402

WINDOW = 7  # trailing-mean window the prior uses (model.predict_from_prior)


def daily_changes(prices: dict) -> list[float]:
    """Changes in cents between consecutive calendar days only.

    A change across a gap is a multi-day move and would fatten every statistic
    below; the record currently has zero gaps, but this stays correct if one
    ever appears.
    """
    days = sorted(prices)
    return [
        prices[b] - prices[a]
        for a, b in zip(days, days[1:])
        if b - a == timedelta(days=1)
    ]


def lag1_autocorr(series: np.ndarray) -> float:
    a, b = series[:-1], series[1:]
    return float(np.corrcoef(a, b)[0, 1])


def measure(changes: list[float]) -> dict[str, float]:
    c = np.asarray(changes, dtype=float)

    # Pairs (trailing 7-day mean, next change), exactly the prior's inputs.
    ma = np.array([c[i - WINDOW : i].mean() for i in range(WINDOW, len(c))])
    nxt = c[WINDOW:]

    # Slope through the origin: the prior has no intercept, so neither does
    # the measurement of its coefficient.
    shrink = float((ma @ nxt) / (ma @ ma))
    residuals = nxt - shrink * ma

    return {
        "n_changes": len(c),
        "n_pairs": len(nxt),
        "sigma_daily": float(np.std(c, ddof=1)),
        "rho1": lag1_autocorr(c),
        "shrink": shrink,
        "sigma_prior": float(np.std(residuals, ddof=1)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--observations", type=Path, default=Path("data/aaa_national_average.csv")
    )
    parser.add_argument("--grade", default="regular")
    args = parser.parse_args(argv)

    prices = feat.load_observations(args.observations, args.grade)
    changes = daily_changes(prices)
    if len(changes) < 60:
        print(
            f"error: {len(changes)} daily changes on file; M5 requires n >= 60",
            file=sys.stderr,
        )
        return 1

    m = measure(changes)
    days = sorted(prices)
    print(f"observations: {len(prices)} ({days[0]} to {days[-1]})")
    print(f"consecutive daily changes: {m['n_changes']}, prior pairs: {m['n_pairs']}")
    print(f"sigma_daily  = {m['sigma_daily']:.3f}c   (unconditional sd of daily change)")
    print(f"rho1         = {m['rho1']:+.3f}    (lag-1 autocorrelation of daily change)")
    print(f"shrink       = {m['shrink']:.3f}    (slope of next change on 7-day mean, no intercept)")
    print(f"sigma_prior  = {m['sigma_prior']:.3f}c   (residual sd around the shrunk-mean prior)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
