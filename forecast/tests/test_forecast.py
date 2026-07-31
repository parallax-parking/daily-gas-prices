"""Acceptance tests for the forecast loop — DESIGN.md §9.

Every test here corresponds to a bullet in that section. They are acceptance
criteria rather than unit tests: each one guards an invariant whose violation
silently destroys the calibration record instead of raising.

Run with: python -m unittest discover -s forecast/tests
"""

from __future__ import annotations

import contextlib
import csv
import io
import math
import random
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "forecast"))
sys.path.insert(0, str(ROOT / "scraper"))

import aaa_gas_prices as scraper  # noqa: E402
import features as feat  # noqa: E402
import forecast as fc  # noqa: E402
import model as mdl  # noqa: E402
import score as sc  # noqa: E402
from thresholds import PROB_COLUMNS, THRESHOLDS_C  # noqa: E402

OBS_HEADER = scraper.FIELDNAMES


def run_forecast(argv: list[str]) -> int:
    """fc.main with stdout swallowed — the walk-forward tests make hundreds of
    calls and their progress lines would bury the actual test results."""
    with contextlib.redirect_stdout(io.StringIO()):
        return fc.main(argv)


def run_score(argv: list[str]) -> int:
    with contextlib.redirect_stdout(io.StringIO()):
        return sc.main(argv)


def write_observations(path: Path, series: list[tuple[str, float]]) -> None:
    """Write an observations CSV in the scraper's current schema."""
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OBS_HEADER)
        writer.writeheader()
        previous = None
        for day, price in series:
            row = {k: "" for k in OBS_HEADER}
            row["date"] = day
            row["regular"] = f"{price:.4f}"
            if previous is not None:
                row["regular_yesterday"] = f"{previous:.4f}"
            row["retrieved_at_utc"] = f"{day}T13:00:00+00:00"
            row["source_url"] = scraper.SOURCE_URL
            writer.writerow(row)
            previous = price


def random_walk(days: int, seed: int = 7, sigma_c: float = 1.2) -> list[tuple[str, float]]:
    """A synthetic daily series with mild momentum, in dollars."""
    rng = random.Random(seed)
    start = date(2026, 1, 1)
    price = 3.500
    drift = 0.0
    out = []
    for i in range(days):
        # AR(1) drift gives the momentum the model is supposed to find.
        drift = 0.45 * drift + rng.gauss(0, sigma_c)
        price = max(1.0, price + drift / 100.0)
        out.append(((start + timedelta(days=i)).isoformat(), price))
    return out


class RefusesToOverwrite(unittest.TestCase):
    """§9: refuses a second row for an existing target_date+grade, exits 0."""

    def test_second_run_is_a_noop_and_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            obs = Path(tmp) / "obs.csv"
            out = Path(tmp) / "forecasts.csv"
            write_observations(obs, random_walk(40))

            self.assertEqual(run_forecast(["--observations", str(obs), "--out", str(out)]), 0)
            first = out.read_text(encoding="utf-8")

            self.assertEqual(run_forecast(["--observations", str(obs), "--out", str(out)]), 0)
            self.assertEqual(out.read_text(encoding="utf-8"), first)

            with out.open(newline="", encoding="utf-8") as handle:
                self.assertEqual(len(list(csv.DictReader(handle))), 1)


class ColdStart(unittest.TestCase):
    """§9: runs without crashing on a 1-row observations file."""

    def test_single_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            obs = Path(tmp) / "obs.csv"
            out = Path(tmp) / "forecasts.csv"
            write_observations(obs, [("2026-07-30", 4.0980)])

            self.assertEqual(run_forecast(["--observations", str(obs), "--out", str(out)]), 0)

            with out.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["mode"], "prior")
            self.assertEqual(rows[0]["target_date"], "2026-07-31")
            self.assertEqual(rows[0]["level_at_forecast"], "4.0980")
            # No changes available, so the prior falls back to zero drift.
            self.assertAlmostEqual(float(rows[0]["mu_cents"]), 0.0, places=6)

    def test_empty_observations_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            obs = Path(tmp) / "obs.csv"
            write_observations(obs, [])
            self.assertEqual(
                run_forecast(["--observations", str(obs), "--out", str(Path(tmp) / "f.csv")]),
                1,
            )


class ProbabilityRoundTrip(unittest.TestCase):
    """§9: recomputing p_gt_* from stored mu/sigma reproduces them to 4dp."""

    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            obs = Path(tmp) / "obs.csv"
            out = Path(tmp) / "forecasts.csv"
            write_observations(obs, random_walk(50))
            run_forecast(["--observations", str(obs), "--out", str(out)])

            with out.open(newline="", encoding="utf-8") as handle:
                row = list(csv.DictReader(handle))[0]

            mu, sigma = float(row["mu_cents"]), float(row["sigma_cents"])
            for threshold, column in zip(THRESHOLDS_C, PROB_COLUMNS):
                self.assertAlmostEqual(
                    float(row[column]),
                    mdl.prob_greater_than(threshold, mu, sigma),
                    places=4,
                    msg=f"{column} does not round-trip",
                )

    def test_any_absolute_threshold_is_recoverable(self):
        """§5.2: mu/sigma make any absolute threshold recoverable after the fact."""
        level, mu, sigma = 4.0980, 0.6, 1.1
        target_price = 4.1100
        implied_change_c = (target_price - level) * 100.0
        self.assertAlmostEqual(
            mdl.prob_greater_than(implied_change_c, mu, sigma),
            0.5 * math.erfc((implied_change_c - mu) / (sigma * math.sqrt(2))),
            places=9,
        )


class ScoringWithNothingScored(unittest.TestCase):
    """§9: score.py produces valid CONTEXT.md with zero scored forecasts."""

    def test_zero_scored(self):
        with tempfile.TemporaryDirectory() as tmp:
            obs = Path(tmp) / "obs.csv"
            forecasts = Path(tmp) / "forecasts.csv"
            context = Path(tmp) / "CONTEXT.md"
            write_observations(obs, [("2026-07-30", 4.0980)])
            run_forecast(["--observations", str(obs), "--out", str(forecasts)])

            code = run_score(
                [
                    "--observations", str(obs),
                    "--forecasts", str(forecasts),
                    "--out", str(context),
                ]
            )
            self.assertEqual(code, 0)
            text = context.read_text(encoding="utf-8")
            self.assertIn("Nothing scored yet", text)
            self.assertIn("Forecasts written: **1**", text)
            self.assertIn("Awaiting outcome: **1**", text)

    def test_no_forecasts_at_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            obs = Path(tmp) / "obs.csv"
            context = Path(tmp) / "CONTEXT.md"
            write_observations(obs, [("2026-07-30", 4.0980)])
            self.assertEqual(
                run_score(
                    [
                        "--observations", str(obs),
                        "--forecasts", str(Path(tmp) / "missing.csv"),
                        "--out", str(context),
                    ]
                ),
                0,
            )
            self.assertIn("Nothing scored yet", context.read_text(encoding="utf-8"))


class SyntheticCalibration(unittest.TestCase):
    """§9: on a synthetic 90-day series, calibration output is sane."""

    def build(self, tmp: str, days: int = 90):
        obs, forecasts, context = (
            Path(tmp) / "obs.csv",
            Path(tmp) / "forecasts.csv",
            Path(tmp) / "CONTEXT.md",
        )
        series = random_walk(days)

        # Walk the series forward one day at a time, exactly as the daily job
        # does: forecast from a prefix, never from the whole thing.
        for cut in range(2, len(series)):
            write_observations(obs, series[:cut])
            run_forecast(["--observations", str(obs), "--out", str(forecasts)])

        write_observations(obs, series)
        run_score(
            [
                "--observations", str(obs),
                "--forecasts", str(forecasts),
                "--out", str(context),
            ]
        )
        return obs, forecasts, context

    def test_pit_and_reliability_are_sane(self):
        with tempfile.TemporaryDirectory() as tmp:
            obs, forecasts, _ = self.build(tmp)

            prices = feat.load_observations(obs)
            with forecasts.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            scored = sc.join(rows, prices)
            self.assertGreater(len(scored), 60)

            pit = sc.pit_summary(scored)
            self.assertGreaterEqual(pit["mean"], 0.40, f"PIT mean {pit['mean']}")
            self.assertLessEqual(pit["mean"], 0.60, f"PIT mean {pit['mean']}")

            curve = sc.reliability(scored)
            self.assertTrue(curve, "reliability curve should not be empty")
            wide = [e for e in curve if abs(e["gap_pp"]) > 15.0]
            self.assertLessEqual(
                len(wide),
                len(curve) // 2,
                f"most reliability gaps should be under 15pp; got {curve}",
            )

    def test_model_mode_engages_and_is_not_pooled_with_prior(self):
        """§9: prior and model rows are never pooled in a headline number."""
        with tempfile.TemporaryDirectory() as tmp:
            _, forecasts, context = self.build(tmp)

            with forecasts.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            modes = {r["mode"] for r in rows}
            self.assertEqual(modes, {"prior", "model"}, "both modes should appear")

            # The switch happens exactly at MIN_TRAIN, not before.
            for row in rows:
                expected = "model" if int(row["n_train"]) >= mdl.MIN_TRAIN else "prior"
                self.assertEqual(row["mode"], expected, f"{row['target_date']}")

            text = context.read_text(encoding="utf-8")
            self.assertIn("mode = `model`", text)
            self.assertIn("mode = `prior`", text)
            self.assertIn("never pooled", text)


class EffectiveN(unittest.TestCase):
    def test_correlated_series_reports_fewer_effective_observations(self):
        independent = [(-1) ** i * 0.5 for i in range(60)]
        n_eff_alt, _ = sc.effective_n(independent)

        correlated = [math.sin(i / 8.0) for i in range(60)]
        n_eff_corr, r = sc.effective_n(correlated)

        self.assertGreater(r, 0.5, "sine series should be strongly autocorrelated")
        self.assertLess(n_eff_corr, 60)
        self.assertLess(n_eff_corr, n_eff_alt)

    def test_gate_language_appears_for_small_samples(self):
        with tempfile.TemporaryDirectory() as tmp:
            obs = Path(tmp) / "obs.csv"
            forecasts = Path(tmp) / "forecasts.csv"
            context = Path(tmp) / "CONTEXT.md"
            series = random_walk(8)
            for cut in range(2, len(series)):
                write_observations(obs, series[:cut])
                run_forecast(["--observations", str(obs), "--out", str(forecasts)])
            write_observations(obs, series)
            run_score(
                [
                    "--observations", str(obs),
                    "--forecasts", str(forecasts),
                    "--out", str(context),
                ]
            )
            self.assertIn("Nothing is concludable", context.read_text(encoding="utf-8"))


class FeatureCausality(unittest.TestCase):
    def test_training_set_never_contains_the_target(self):
        series = random_walk(40)
        write_target = date.fromisoformat(series[-1][0])
        with tempfile.TemporaryDirectory() as tmp:
            obs = Path(tmp) / "obs.csv"
            write_observations(obs, series)
            prices = feat.load_observations(obs)

            rows, targets = feat.training_set(prices, write_target)
            # The last usable training pair ends one day before made_on, since
            # made_on's own outcome has not happened yet.
            self.assertEqual(len(rows), len(targets))
            self.assertGreater(len(targets), 0)

            last_day = max(
                day
                for day in prices
                if day <= write_target
                and not math.isnan(feat._change(prices, day + timedelta(days=1)))
                and feat.is_complete(feat.build_features(prices, day))
            )
            self.assertLess(last_day, write_target)

    def test_gap_produces_nan_not_a_wrong_lag(self):
        prices = {
            date(2026, 1, 1): 350.0,
            date(2026, 1, 2): 351.0,
            # 2026-01-03 missing
            date(2026, 1, 4): 353.0,
        }
        features = feat.build_features(prices, date(2026, 1, 4))
        self.assertTrue(math.isnan(features["d1"]), "d1 must not span the gap")
        self.assertFalse(feat.is_complete(features))


if __name__ == "__main__":
    unittest.main()
