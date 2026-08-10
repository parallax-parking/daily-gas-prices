"""Tests for the GitHub Pages dashboard.

The page's job is to be glanceable, which is exactly what makes it dangerous:
a number on a dashboard reads as authoritative whether or not it means
anything. Most of these tests are about what it must NOT claim.

Run with: python -m unittest discover -s forecast/tests
"""

from __future__ import annotations

import contextlib
import csv
import io
import re
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "forecast"))
sys.path.insert(0, str(ROOT / "scraper"))

import dashboard  # noqa: E402
import forecast as fc  # noqa: E402
import score as sc  # noqa: E402

from test_forecast import random_walk, write_observations  # noqa: E402


def build(tmp: str, days: int) -> str:
    obs, forecasts = Path(tmp) / "obs.csv", Path(tmp) / "fc.csv"
    context, site = Path(tmp) / "CONTEXT.md", Path(tmp) / "docs" / "index.html"
    series = random_walk(days)
    with contextlib.redirect_stdout(io.StringIO()):
        for cut in range(2, len(series) + 1):
            write_observations(obs, series[:cut])
            fc.main(["--observations", str(obs), "--out", str(forecasts)])
        sc.main([
            "--observations", str(obs), "--forecasts", str(forecasts),
            "--out", str(context), "--site", str(site),
        ])
    return site.read_text(encoding="utf-8")


class SelfContained(unittest.TestCase):
    """GitHub Pages serves this directly; it must not depend on anything."""

    def test_no_scripts_and_no_external_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            page = build(tmp, 40)
        self.assertNotIn("<script", page)
        urls = [u for u in re.findall(r'(?:src|href)="([^"]+)', page)
                if not u.startswith("#")]
        for url in urls:
            self.assertTrue(
                url.startswith("https://github.com/parallax-parking/"),
                f"unexpected external reference: {url}",
            )

    def test_renders_with_nothing_scored(self):
        with tempfile.TemporaryDirectory() as tmp:
            page = build(tmp, 2)
        self.assertIn("How much to trust", page)
        self.assertNotIn("Calibrated read available", page)


class TellsTheTruthAboutTrust(unittest.TestCase):
    def test_bootstrap_only_is_never_called_calibrated(self):
        """The prior's scores say nothing about the fitted model. The page has
        to say so, because a Brier score printed large looks like a verdict."""
        with tempfile.TemporaryDirectory() as tmp:
            page = build(tmp, 20)
        self.assertIn("Not the real model yet", page)
        self.assertNotIn("Calibrated read available", page)
        self.assertNotIn("Directional read only", page)

    def test_verdict_never_claims_more_than_the_gate_allows(self):
        for days in (10, 20, 45, 90):
            with tempfile.TemporaryDirectory() as tmp:
                page = build(tmp, days)
            if "Calibrated read available" in page:
                match = re.search(r'Effective n</div>\s*<div class="v">([\d.]+)', page)
                self.assertIsNotNone(match, f"days={days}: no effective n shown")
                self.assertGreaterEqual(
                    float(match.group(1)), 50.0,
                    f"days={days}: claimed calibration below the n_eff=50 gate",
                )

    def test_effective_n_is_shown_not_just_raw_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            page = build(tmp, 40)
        self.assertIn("Effective n", page)


class NextDayRange(unittest.TestCase):
    def row(self, level="4.0121", mu="-0.4195", sigma="1.0000", mode="prior"):
        row = {
            "target_date": "2026-08-10", "level_at_forecast": level,
            "mu_cents": mu, "sigma_cents": sigma, "mode": mode,
        }
        row.update({c: "0.5000" for c in dashboard.PROB_COLUMNS})
        return row

    def test_interval_is_snapped_outward_onto_the_display_grid(self):
        """Exact interval is 3.99510 - 4.02070 around a centre of 4.00791.
        Displayed ends must sit on the half-cent grid and must widen, never
        narrow - a narrower stated range would claim more confidence than the
        forecast supports."""
        page = dashboard.render_site(
            [], {}, [], [self.row()], {"model": [], "prior": []}, {},
            None, "- held", None, 0,
        )
        self.assertIn("$3.995 – $4.025", page)
        self.assertIn("At least 80% confidence", page)
        self.assertIn("$4.010", page)          # centre, snapped to nearest
        self.assertNotIn("$3.9951", page)      # no 4dp noise survives
        self.assertNotIn("$4.0207", page)

    def test_flags_that_a_prior_range_is_a_guess(self):
        page = dashboard.render_site(
            [], {}, [], [self.row()], {"model": [], "prior": []}, {},
            None, "- held", None, 0,
        )
        self.assertIn("bootstrap prior", page)
        self.assertIn("guess rather than a measurement", page)

    def test_handles_no_pending_forecast(self):
        page = dashboard.render_site(
            [], {}, [], [], {"model": [], "prior": []}, {}, None, "- held", None, 0,
        )
        self.assertIn("No forecast is currently awaiting an outcome", page)

    def test_ladder_brackets_todays_level(self):
        """The ladder has to span the current price, or the reader cannot see
        which way the forecast leans."""
        import thresholds as th
        page = dashboard.render_site(
            [], {}, [], [self.row()], {"model": [], "prior": []}, {},
            None, "- held", None, 0,
        )
        rungs = [p for p, _ in th.price_ladder(4.0121, -0.4195, 1.0)]
        self.assertLess(min(rungs), 4.0121)
        self.assertGreater(max(rungs), 4.0121)
        self.assertIn("(today)", page)


class Chart(unittest.TestCase):
    def test_sparkline_omitted_when_there_is_nothing_to_draw(self):
        self.assertEqual(dashboard._sparkline({date(2026, 8, 1): 400.0}, None), "")
        self.assertEqual(dashboard._sparkline({}, None), "")

    def test_sparkline_drawn_with_history(self):
        prices = {date(2026, 8, 1) + timedelta(days=i): 400.0 + i for i in range(10)}
        svg = dashboard._sparkline(prices, None)
        self.assertIn("<svg", svg)
        self.assertIn("polyline", svg)
        self.assertNotIn("nan", svg.lower())

    def test_flat_series_does_not_divide_by_zero(self):
        prices = {date(2026, 8, 1) + timedelta(days=i): 400.0 for i in range(10)}
        svg = dashboard._sparkline(prices, None)
        self.assertIn("<svg", svg)
        self.assertNotIn("nan", svg.lower())


class HalfCentDisplay(unittest.TestCase):
    """Absolute prices are shown on a readable grid; stored ones are untouched."""

    def test_ladder_rungs_are_all_multiples_of_the_step(self):
        import thresholds as th
        for price, _ in th.price_ladder(4.0121, -0.4195, 1.0):
            self.assertAlmostEqual(
                price / th.DISPLAY_STEP, round(price / th.DISPLAY_STEP), places=9,
                msg=f"${price} is not on the ${th.DISPLAY_STEP} grid",
            )

    def test_ladder_probabilities_are_exact_for_their_price(self):
        """Rounding the price must not mean rounding the probability off some
        neighbouring stored threshold — each rung is recomputed."""
        import thresholds as th
        level, mu, sigma = 4.0121, -0.4195, 1.0
        for price, prob in th.price_ladder(level, mu, sigma):
            self.assertAlmostEqual(
                prob, th.prob_above_price(price, level, mu, sigma), places=12
            )

    def test_ladder_descends_monotonically(self):
        import thresholds as th
        probs = [p for _, p in th.price_ladder(4.0121, -0.4195, 1.0)]
        self.assertEqual(probs, sorted(probs, reverse=True))
        self.assertTrue(all(0.0 <= p <= 1.0 for p in probs))

    def test_ladder_widens_with_sigma(self):
        import thresholds as th
        tight = th.price_ladder(4.0000, 0.0, 0.5)
        wide = th.price_ladder(4.0000, 0.0, 2.0)
        self.assertGreater(len(wide), len(tight))

    def test_snap_rounds_intervals_outward_never_inward(self):
        import thresholds as th
        self.assertLessEqual(th.snap(3.9951, mode="down"), 3.9951)
        self.assertGreaterEqual(th.snap(4.0207, mode="up"), 4.0207)
        self.assertEqual(th.snap(3.9951, mode="down"), 3.995)
        self.assertEqual(th.snap(4.0207, mode="up"), 4.025)

    def test_snap_survives_binary_representation_of_0_005(self):
        import thresholds as th
        for raw in (3.995, 4.010, 4.025, 3.9950000001):
            snapped = th.snap(raw)
            self.assertAlmostEqual(snapped * 200, round(snapped * 200), places=9)

    def test_page_shows_only_grid_prices_in_the_ladder(self):
        with tempfile.TemporaryDirectory() as tmp:
            page = build(tmp, 12)
        body = page.split("Chance the price is above")[1].split("</table>")[0]
        for price in re.findall(r"\$(\d+\.\d+)", body):
            self.assertEqual(len(price.split(".")[1]), 3, f"${price} not 3dp")
            self.assertAlmostEqual(
                float(price) * 200, round(float(price) * 200), places=6,
                msg=f"${price} is not a half-cent multiple",
            )

    def test_stored_thresholds_are_unchanged_by_any_of_this(self):
        """§6.4: what goes on disk stays relative to the level. The display
        grid must never leak into the record."""
        import thresholds as th
        self.assertEqual(th.THRESHOLDS_C, [-2.0, -1.0, 0.0, 1.0, 2.0])
        self.assertEqual(
            th.PROB_COLUMNS,
            ["p_gt_m2c", "p_gt_m1c", "p_gt_0c", "p_gt_p1c", "p_gt_p2c"],
        )
        with tempfile.TemporaryDirectory() as tmp:
            obs, out = Path(tmp) / "obs.csv", Path(tmp) / "fc.csv"
            write_observations(obs, random_walk(6))
            with contextlib.redirect_stdout(io.StringIO()):
                fc.main(["--observations", str(obs), "--out", str(out)])
            with out.open(newline="", encoding="utf-8") as handle:
                row = list(csv.DictReader(handle))[0]
            level = float(row["level_at_forecast"])
            # The stored level is the raw observation, not snapped to the grid.
            self.assertEqual(f"{level:.4f}", row["level_at_forecast"])


if __name__ == "__main__":
    unittest.main()


class DailyCycleOrder(unittest.TestCase):
    """The job runs score -> forecast. The page is rendered by the score pass,
    so without a second render it describes the world as it was one forecast
    ago and reports nothing pending.

    This went unnoticed for ten days because the other tests in this file run
    score *last*, which is not what the workflow does. A test harness whose
    ordering differs from production tests something production never does.
    """

    def cycle(self, tmp: str, days: int, refresh: bool) -> str:
        obs, forecasts = Path(tmp) / "obs.csv", Path(tmp) / "fc.csv"
        context, site = Path(tmp) / "CONTEXT.md", Path(tmp) / "docs" / "index.html"
        series = random_walk(days)
        score_args = [
            "--observations", str(obs), "--forecasts", str(forecasts),
            "--out", str(context), "--site", str(site),
        ]
        fc_args = ["--observations", str(obs), "--out", str(forecasts)]

        with contextlib.redirect_stdout(io.StringIO()):
            # Warm up so there is a record to score at all.
            for cut in range(2, days):
                write_observations(obs, series[:cut])
                fc.main(fc_args)
            # Then one full day in the workflow's exact order.
            write_observations(obs, series[:days])
            sc.main(score_args)          # 1. score yesterday
            fc.main(fc_args)             # 2. forecast tomorrow
            if refresh:
                sc.main(score_args)      # 3. re-render with it
        return site.read_text(encoding="utf-8")

    def test_without_the_refresh_the_page_hides_tomorrows_forecast(self):
        """Regression: this is what the live page did every day."""
        with tempfile.TemporaryDirectory() as tmp:
            page = self.cycle(tmp, 12, refresh=False)
        self.assertIn("No forecast is currently awaiting an outcome", page)

    def test_the_refresh_makes_tomorrows_forecast_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            page = self.cycle(tmp, 12, refresh=True)
        self.assertNotIn("No forecast is currently awaiting an outcome", page)
        self.assertRegex(page, r"<h2>Where \d{4}-\d{2}-\d{2} lands</h2>")
        self.assertIn("confidence", page)

    def test_the_refresh_scores_nothing_extra(self):
        """Re-rendering must not quietly score the forecast just written -
        that would be scoring against its own input, which invariant 4 forbids.
        """
        with tempfile.TemporaryDirectory() as tmp:
            obs, forecasts = Path(tmp) / "obs.csv", Path(tmp) / "fc.csv"
            context, site = Path(tmp) / "CONTEXT.md", Path(tmp) / "docs" / "x.html"
            series = random_walk(12)
            args = [
                "--observations", str(obs), "--forecasts", str(forecasts),
                "--out", str(context), "--site", str(site),
            ]
            with contextlib.redirect_stdout(io.StringIO()):
                for cut in range(2, 13):
                    write_observations(obs, series[:cut])
                    fc.main(["--observations", str(obs), "--out", str(forecasts)])
                sc.main(args)
                first = context.read_text(encoding="utf-8")
                fc.main(["--observations", str(obs), "--out", str(forecasts)])
                sc.main(args)
                second = context.read_text(encoding="utf-8")

        scored = lambda text: re.search(r"Forecasts scored: \*\*(\d+)\*\*", text).group(1)
        self.assertEqual(scored(first), scored(second))
