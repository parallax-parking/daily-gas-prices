#!/usr/bin/env python3
"""Append one immutable forecast row for tomorrow's AAA national average.

Invariants this file exists to protect (DESIGN.md §3):

  - A forecast is written *before* its outcome exists and is never edited.
    Re-running for a target date already on file is a no-op that exits 0,
    because reruns are expected and are not errors.
  - Nothing here reads the value being predicted. Inputs are the observations
    CSV as of the current commit, and nothing else.
  - No LLM is involved. This is deterministic code with a pinned model version,
    so that a Brier score measures the model rather than the weather in a
    context window.

Usage:
    python forecast/forecast.py --out data/forecasts.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import date as date_cls
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import features as feat  # noqa: E402
import model as mdl  # noqa: E402
from thresholds import PROB_COLUMNS, THRESHOLDS_C, snap  # noqa: E402

FIELDNAMES = [
    "target_date",
    "made_at_utc",
    "made_on_date",
    "grade",
    "level_at_forecast",
    "mu_cents",
    "sigma_cents",
    "n_train",
    "mode",
    "model_version",
    "git_sha",
    "features",
    *PROB_COLUMNS,
]


def git_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        return result.stdout.strip() or "unknown"
    except (subprocess.SubprocessError, OSError):
        return "unknown"


def read_forecasts(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def already_forecast(rows: list[dict[str, str]], target: str, grade: str) -> bool:
    return any(
        r.get("target_date") == target and r.get("grade") == grade for r in rows
    )


def build_row(
    prices: dict[date_cls, float], made_on: date_cls, grade: str
) -> dict[str, str]:
    """Produce the forecast row for the day after `made_on`."""
    rows, targets = feat.training_set(prices, made_on)
    current = feat.build_features(prices, made_on)

    if len(targets) >= mdl.MIN_TRAIN and feat.is_complete(current):
        prediction = mdl.predict(
            rows, targets, [current[name] for name in feat.FEATURE_NAMES]
        )
    else:
        # Bootstrap. Note this deliberately uses whatever recent changes exist
        # rather than requiring a complete window — during the first weeks
        # there is no complete window to require.
        prediction = mdl.predict_from_prior(feat.recent_changes(prices, made_on, 7))

    level_cents = prices[made_on]
    row = {
        "target_date": (made_on + timedelta(days=1)).isoformat(),
        "made_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "made_on_date": made_on.isoformat(),
        "grade": grade,
        "level_at_forecast": f"{level_cents / 100.0:.4f}",
        "mu_cents": f"{prediction.mu_cents:.4f}",
        "sigma_cents": f"{prediction.sigma_cents:.4f}",
        "n_train": str(prediction.n_train),
        "mode": prediction.mode,
        "model_version": mdl.MODEL_VERSION,
        "git_sha": git_sha(),
        # Not optional. Without the feature vector you cannot diagnose a bad
        # forecast weeks later, and that diagnosis is most of the value here.
        "features": json.dumps(feat.jsonable(current), sort_keys=True),
    }

    for threshold, column in zip(THRESHOLDS_C, PROB_COLUMNS):
        row[column] = f"{mdl.prob_greater_than(threshold, prediction.mu_cents, prediction.sigma_cents):.4f}"

    return row


def append(path: Path, row: dict[str, str]) -> None:
    existing = read_forecasts(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        for old in sorted(existing, key=lambda r: (r.get("target_date", ""), r.get("grade", ""))):
            writer.writerow({k: old.get(k, "") for k in FIELDNAMES})
        writer.writerow(row)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--observations", type=Path, default=Path("data/aaa_national_average.csv")
    )
    parser.add_argument("--out", type=Path, default=Path("data/forecasts.csv"))
    parser.add_argument("--grade", default="regular")
    args = parser.parse_args(argv)

    prices = feat.load_observations(args.observations, args.grade)
    if not prices:
        print(
            f"error: no {args.grade} observations in {args.observations}",
            file=sys.stderr,
        )
        return 1

    made_on = max(prices)
    target = (made_on + timedelta(days=1)).isoformat()

    existing = read_forecasts(args.out)
    if already_forecast(existing, target, args.grade):
        # Not an error. The job is idempotent by design and reruns are routine.
        print(f"forecast for {target} ({args.grade}) already on file; leaving it alone")
        return 0

    row = build_row(prices, made_on, args.grade)
    append(args.out, row)

    # Each threshold is echoed back as an absolute price as well as a relative
    # change. The stored form has to be relative (§6.4), but "P(price >
    # $4.1080)" is what a human can sanity-check at a glance against the pump.
    level = float(row["level_at_forecast"])
    print(
        f"{row['target_date']} {args.grade}: level ${level:.4f}  "
        f"mu {float(row['mu_cents']):+.2f}c  sigma {float(row['sigma_cents']):.2f}c  "
        f"[{row['mode']}, n_train={row['n_train']}]"
    )
    for threshold, column in zip(THRESHOLDS_C, PROB_COLUMNS):
        print(
            f"    P(change > {threshold:+.0f}c) = {float(row[column]) * 100:5.1f}%"
            f"   i.e. P(price > ${level + threshold / 100.0:.4f})"
        )

    # The lines above mirror what was stored, at the exact relative thresholds
    # §6.4 requires. This one is for a human reading the log: the same
    # distribution as a price range on the half-cent grid, snapped outward so
    # the stated range holds at least the stated probability.
    mu, sigma = float(row["mu_cents"]), float(row["sigma_cents"])
    centre = level + mu / 100.0
    print(
        f"    -> at least 80% between ${snap(centre - 1.2816 * sigma / 100, mode='down'):.3f}"
        f" and ${snap(centre + 1.2816 * sigma / 100, mode='up'):.3f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
