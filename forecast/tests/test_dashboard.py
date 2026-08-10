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


def verdict_of(page: str) -> str:
    """The verdict line only.

    "Extremely trustworthy" is also printed as the right-hand end of the gauge
    scale, so a bare substring search cannot tell a claim from a label.
    """
    match = re.search(r'<p class="verdict[^"]*">(.*?)</p>', page, re.S)
    return match.group(1).strip() if match else ""


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
        self.assertIn('<svg class="gauge"', page)
        self.assertNotIn("trustworthy</p>", page.lower())

    def test_no_literal_markdown_leaks_into_the_html(self):
        """score.py speaks markdown for CONTEXT.md. The page rendered
        '**held**' verbatim until _md was added."""
        with tempfile.TemporaryDirectory() as tmp:
            page = build(tmp, 20)
        self.assertNotIn("**", page)


class TellsTheTruthAboutTrust(unittest.TestCase):
    def test_bootstrap_only_never_moves_the_needle_far(self):
        """The prior's scores say nothing about the fitted model, however well
        they happen to come out, so the gauge stays near Empty."""
        with tempfile.TemporaryDirectory() as tmp:
            page = build(tmp, 20)
        self.assertEqual(verdict_of(page), "Warming up")
        fraction, label, _ = dashboard.trust_score(
            [1] * 19, {"model": [], "prior": [1] * 19}, {}, None, 29
        )
        self.assertLess(fraction, 0.20, "bootstrap should sit near Empty")

    def test_never_claims_trustworthy_below_the_gate(self):
        for days in (10, 20, 45, 90):
            with tempfile.TemporaryDirectory() as tmp:
                page = build(tmp, days)
            if "rustworthy" in verdict_of(page):
                match = re.search(
                    r'Independent days</div>\s*<div class="v">([\d.]+)', page
                )
                self.assertIsNotNone(match, f"days={days}: no independent-day count")
                self.assertGreaterEqual(
                    float(match.group(1)), 50.0,
                    f"days={days}: claimed trustworthy below the 50-day gate",
                )

    def test_independent_days_is_shown_not_just_raw_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            page = build(tmp, 40)
        self.assertIn("Independent days", page)


class Gauge(unittest.TestCase):
    """The needle is the whole message, so its position has to be defensible."""

    def score(self, n_scored, model, n_eff, brier, n_train):
        by_mode = {"model": [1] * model, "prior": [1] * (n_scored - model)}
        sizes = {"model": {"binding": n_eff}} if model else {}
        head = {"brier": brier} if brier is not None else None
        return dashboard.trust_score([1] * n_scored, by_mode, sizes, head, n_train)

    def test_fraction_always_within_bounds(self):
        for case in [(0, 0, 0, None, 0), (10, 0, 0, None, 9), (30, 30, 8, None, 30),
                     (90, 90, 60, 0.26, 90), (120, 120, 80, 0.02, 120)]:
            fraction, _, _ = self.score(*case)
            self.assertGreaterEqual(fraction, 0.0)
            self.assertLessEqual(fraction, 1.0)

    def test_measured_and_bad_scores_lower_than_merely_unmeasured(self):
        """A model shown to be no better than a coin flip has earned less
        trust than one that simply has not been tested yet."""
        unmeasured, _, _ = self.score(30, 30, 8, None, 30)
        measured_bad, label, _ = self.score(90, 90, 60, 0.26, 90)
        self.assertLess(measured_bad, unmeasured)
        self.assertIn("not good", label)

    def test_full_requires_both_evidence_and_skill(self):
        strong_but_thin, _, _ = self.score(30, 30, 10, 0.10, 30)
        self.assertLess(strong_but_thin, 0.6, "skill alone must not fill the tank")
        thick_but_weak, _, _ = self.score(120, 120, 80, 0.249, 120)
        self.assertLess(thick_but_weak, 0.72, "evidence alone must not either")
        both, label, _ = self.score(120, 120, 80, 0.15, 120)
        self.assertGreaterEqual(both, 0.85)
        self.assertEqual(label, "Extremely trustworthy")

    def test_more_skill_never_lowers_the_needle(self):
        previous = -1.0
        for brier in (0.245, 0.23, 0.20, 0.17, 0.14):
            fraction, _, _ = self.score(120, 120, 80, brier, 120)
            self.assertGreaterEqual(fraction, previous)
            previous = fraction

    def test_needle_stays_inside_the_arc(self):
        for fraction in (-5.0, 0.0, 0.5, 1.0, 42.0):
            svg = dashboard._gauge(fraction)
            self.assertIn("<svg", svg)
            self.assertNotIn("nan", svg.lower())
            for value in re.findall(r'(?:x|y)[12]?="(-?[\d.]+)"', svg):
                self.assertGreater(float(value), -60.0)
                self.assertLess(float(value), 380.0)


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
