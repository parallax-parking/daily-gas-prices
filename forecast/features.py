"""Causal feature construction for the daily gas-price forecast.

Everything here is a pure function of observations dated on or before
`made_on`. Nothing reads the target. See DESIGN.md §3 invariant 2 and §6.2.

Units: all prices arrive in dollars and are converted to **cents** at the
boundary. The model, its coefficients, mu and sigma are all in cents, which is
the unit the calibration record is quoted in.

Lags are looked up by calendar date, not by row position. A missing day
therefore produces NaN features rather than a lag that silently spans a gap —
a wrong feature is far more expensive here than an absent one.
"""

from __future__ import annotations

import csv
import math
from datetime import date as date_cls
from datetime import timedelta
from pathlib import Path

FEATURE_NAMES = ["d1", "d2", "d3", "ma3", "ma7", "vol7", "wk", "dow"]

NAN = float("nan")


def load_observations(path: Path, grade: str = "regular") -> dict[date_cls, float]:
    """Read the scraper's CSV into {date: price_in_cents}.

    Rows with a blank price for `grade` are skipped — backfilled rows carry
    `regular` only, so they participate for regular and vanish for the rest.
    """
    if not path.exists():
        return {}

    prices: dict[date_cls, float] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            raw = (row.get(grade) or "").strip()
            if not raw:
                continue
            try:
                prices[date_cls.fromisoformat(row["date"])] = float(raw) * 100.0
            except (ValueError, KeyError):
                continue
    return prices


def _change(prices: dict[date_cls, float], day: date_cls) -> float:
    """One-day change ending on `day`, in cents. NaN if either end is missing."""
    today, prior = prices.get(day), prices.get(day - timedelta(days=1))
    if today is None or prior is None:
        return NAN
    return today - prior


def recent_changes(
    prices: dict[date_cls, float], made_on: date_cls, count: int
) -> list[float]:
    """The last `count` daily changes ending at `made_on`, newest first.

    Missing days are dropped rather than returned as NaN — callers use this for
    means over "whatever we have", which is the right behaviour during the
    bootstrap when the series is short and possibly gappy.
    """
    changes = []
    for offset in range(count):
        value = _change(prices, made_on - timedelta(days=offset))
        if not math.isnan(value):
            changes.append(value)
    return changes


def build_features(
    prices: dict[date_cls, float], made_on: date_cls
) -> dict[str, float]:
    """Feature vector for predicting the change from `made_on` to the next day.

    Returns NaN for any feature whose inputs are missing. Callers decide
    whether a NaN-bearing vector is usable; `is_complete` is the usual test.
    """
    d1 = _change(prices, made_on)
    d2 = _change(prices, made_on - timedelta(days=1))
    d3 = _change(prices, made_on - timedelta(days=2))

    # ma7/vol7 need seven consecutive daily changes, i.e. eight consecutive
    # observations. Require all of them; a partial window is a different
    # statistic wearing the same name.
    window = [_change(prices, made_on - timedelta(days=k)) for k in range(7)]
    if any(math.isnan(v) for v in window):
        ma7 = vol7 = NAN
    else:
        ma7 = sum(window) / 7.0
        mean = ma7
        vol7 = math.sqrt(sum((v - mean) ** 2 for v in window) / 6.0)

    trio = [d1, d2, d3]
    ma3 = NAN if any(math.isnan(v) for v in trio) else sum(trio) / 3.0

    week_ago = prices.get(made_on - timedelta(days=7))
    today = prices.get(made_on)
    wk = NAN if (week_ago is None or today is None) else today - week_ago

    # Day of week of the *target*, not of made_on — weekend pricing behaviour
    # is a property of the day being predicted.
    dow = float((made_on + timedelta(days=1)).weekday())

    return {
        "d1": d1,
        "d2": d2,
        "d3": d3,
        "ma3": ma3,
        "ma7": ma7,
        "vol7": vol7,
        "wk": wk,
        "dow": dow,
    }


def is_complete(features: dict[str, float]) -> bool:
    return not any(math.isnan(features[name]) for name in FEATURE_NAMES)


def training_set(
    prices: dict[date_cls, float], made_on: date_cls
) -> tuple[list[list[float]], list[float]]:
    """Every (features, realised next-day change) pair strictly before the target.

    A pair is included only when its features are complete and its own outcome
    is already observed, so the training set can never contain the value being
    forecast today.
    """
    rows: list[list[float]] = []
    targets: list[float] = []

    for day in sorted(prices):
        if day > made_on:
            break
        outcome = _change(prices, day + timedelta(days=1))
        if math.isnan(outcome):
            continue
        features = build_features(prices, day)
        if not is_complete(features):
            continue
        rows.append([features[name] for name in FEATURE_NAMES])
        targets.append(outcome)

    return rows, targets


def jsonable(features: dict[str, float]) -> dict[str, float | None]:
    """NaN is not valid JSON; null is."""
    return {
        k: (None if isinstance(v, float) and math.isnan(v) else round(v, 6))
        for k, v in features.items()
    }
