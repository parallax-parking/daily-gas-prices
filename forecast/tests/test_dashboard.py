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

    def test_interval_matches_mu_and_sigma(self):
        page = dashboard.render_site(
            [], {}, [], [self.row()], {"model": [], "prior": []}, {},
            None, "- held", None, 0,
        )
        # 4.0121 - 0.004195 = 4.007905 centre; +/- 1.28155 * 0.01
        self.assertIn("$3.9951", page)   # low
        self.assertIn("$4.0207", page)   # high
        self.assertIn("$4.0079", page)   # centre

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

    def test_absolute_prices_match_the_stored_thresholds(self):
        page = dashboard.render_site(
            [], {}, [], [self.row()], {"model": [], "prior": []}, {},
            None, "- held", None, 0,
        )
        for offset in (-2, -1, 0, 1, 2):
            self.assertIn(f"${4.0121 + offset / 100.0:.4f}", page)


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


if __name__ == "__main__":
    unittest.main()
