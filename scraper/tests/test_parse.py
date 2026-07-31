"""Parser tests against a saved copy of the AAA fuel-gauge table markup.

Run with: python -m unittest discover -s scraper/tests
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aaa_gas_prices import (  # noqa: E402
    BACKFILL_SOURCE,
    Reading,
    ScrapeError,
    backfill,
    check_revision,
    parse_fuel_gauge,
    parse_national_average,
    read_existing,
    write_csv,
)

FIXTURE = Path(__file__).parent / "fixtures" / "gasprices_home.html"


class ParseNationalAverage(unittest.TestCase):
    def test_reads_current_avg_row(self):
        prices = parse_national_average(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(
            prices,
            {
                "regular": 4.091,
                "mid_grade": 4.523,
                "premium": 4.874,
                "diesel": 4.216,
                "e85": 3.402,
            },
        )

    def test_handles_missing_e85_column(self):
        html = """
        <table>
          <thead><tr><th></th><th>Regular</th><th>Mid-Grade</th>
            <th>Premium</th><th>Diesel</th></tr></thead>
          <tbody>
            <tr><td>Current Avg.</td><td>$3.101</td><td>$3.550</td>
              <td>$3.900</td><td>N/A</td></tr>
            <tr><td>Yesterday Avg.</td><td>$3.099</td><td>$3.548</td>
              <td>$3.898</td><td>$3.700</td></tr>
          </tbody>
        </table>
        """
        prices = parse_national_average(html)
        self.assertEqual(prices["regular"], 3.101)
        self.assertIsNone(prices["diesel"])
        self.assertNotIn("e85", prices)

    def test_ignores_unrelated_tables(self):
        html = """
        <table><tr><th>Rank</th><th>State</th></tr>
          <tr><td>1</td><td>Current Avg. of nothing</td></tr></table>
        <table>
          <tr><th>&nbsp;</th><th>Regular</th><th>Diesel</th></tr>
          <tr><td>Current&nbsp;Avg.</td><td>$2.825</td><td>$3.100</td></tr>
        </table>
        """
        self.assertEqual(
            parse_national_average(html), {"regular": 2.825, "diesel": 3.100}
        )

    def test_raises_when_layout_changes(self):
        with self.assertRaises(ScrapeError):
            parse_national_average("<table><tr><th>Something Else</th></tr></table>")


class WriteCsv(unittest.TestCase):
    def reading(self, date, regular):
        return Reading(
            date=date,
            prices={"regular": regular, "diesel": 4.2},
            retrieved_at_utc="2026-07-30T13:00:00+00:00",
        )

    def test_appends_and_dedupes_by_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.csv"

            self.assertTrue(write_csv(path, self.reading("2026-07-29", 4.081)))
            self.assertTrue(write_csv(path, self.reading("2026-07-30", 4.091)))
            # Second run on the same day is a no-op...
            self.assertFalse(write_csv(path, self.reading("2026-07-30", 9.999)))
            rows = read_existing(path)
            self.assertEqual([r["date"] for r in rows], ["2026-07-29", "2026-07-30"])
            self.assertEqual(rows[1]["regular"], "4.0910")
            self.assertEqual(rows[1]["premium"], "")

            # ...unless forced.
            self.assertTrue(write_csv(path, self.reading("2026-07-30", 9.999), force=True))
            self.assertEqual(read_existing(path)[1]["regular"], "9.9990")

    def test_keeps_rows_sorted_by_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.csv"
            write_csv(path, self.reading("2026-07-30", 4.091))
            write_csv(path, self.reading("2026-07-28", 4.071))
            self.assertEqual(
                [r["date"] for r in read_existing(path)],
                ["2026-07-28", "2026-07-30"],
            )


class FuelGaugeLags(unittest.TestCase):
    """DESIGN.md §5.1 — the lag rows AAA already renders on the same page."""

    def test_captures_every_labelled_row(self):
        gauge = parse_fuel_gauge(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(
            set(gauge),
            {"current", "yesterday", "week_ago", "month_ago", "year_ago"},
        )
        self.assertEqual(gauge["yesterday"]["regular"], 4.086)
        self.assertEqual(gauge["week_ago"]["regular"], 4.042)
        self.assertEqual(gauge["month_ago"]["regular"], 3.918)
        self.assertEqual(gauge["year_ago"]["regular"], 3.512)

    def test_reading_stores_lags_to_four_places(self):
        gauge = parse_fuel_gauge(FIXTURE.read_text(encoding="utf-8"))
        reading = Reading(
            date="2026-07-30",
            prices=gauge["current"],
            retrieved_at_utc="2026-07-30T13:00:00+00:00",
            lags={k: gauge[k]["regular"] for k in ("yesterday", "week_ago", "month_ago", "year_ago")},
        )
        row = reading.as_row()
        self.assertEqual(row["regular"], "4.0910")
        self.assertEqual(row["regular_yesterday"], "4.0860")
        self.assertEqual(row["regular_year_ago"], "3.5120")


class GapRepair(unittest.TestCase):
    """§9: deleting a middle row and re-running backfill reconstructs it."""

    def series(self, path):
        for day, price, yesterday in (
            ("2026-07-28", 4.0710, 4.0700),
            ("2026-07-29", 4.0810, 4.0710),
            ("2026-07-30", 4.0980, 4.0810),
        ):
            write_csv(
                path,
                Reading(
                    date=day,
                    prices={"regular": price},
                    retrieved_at_utc=f"{day}T13:00:00+00:00",
                    lags={"yesterday": yesterday},
                ),
            )

    def test_reconstructs_a_deleted_middle_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "obs.csv"
            self.series(path)

            rows = [r for r in read_existing(path) if r["date"] != "2026-07-29"]
            with path.open("w", newline="", encoding="utf-8") as handle:
                import csv as _csv

                writer = _csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            self.assertEqual([r["date"] for r in read_existing(path)], ["2026-07-28", "2026-07-30"])

            # 07-29 is the gap being repaired; 07-27 falls out of the earliest
            # row's own `yesterday`, which extends the series one day backward.
            # That is real AAA data too, so it is kept rather than suppressed.
            added = backfill(path)
            self.assertEqual(added, ["2026-07-27", "2026-07-29"])

            repaired = read_existing(path)
            self.assertEqual(
                [r["date"] for r in repaired],
                ["2026-07-27", "2026-07-28", "2026-07-29", "2026-07-30"],
            )
            recovered = next(r for r in repaired if r["date"] == "2026-07-29")
            self.assertEqual(recovered["regular"], "4.0810")
            # Only `regular` is recoverable this way, and the row says so.
            self.assertEqual(recovered["premium"], "")
            self.assertEqual(recovered["source_url"], BACKFILL_SOURCE)

    def test_backfill_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "obs.csv"
            self.series(path)
            self.assertEqual(backfill(path), ["2026-07-27"])
            self.assertEqual(backfill(path), [])


class RevisionDetection(unittest.TestCase):
    """§8 M0 — warn when AAA's 'yesterday' disagrees with what we stored."""

    def reading(self, claimed_yesterday):
        return Reading(
            date="2026-07-30",
            prices={"regular": 4.0980},
            retrieved_at_utc="2026-07-30T13:00:00+00:00",
            lags={"yesterday": claimed_yesterday},
        )

    def stored(self, price):
        return [{"date": "2026-07-29", "regular": f"{price:.4f}"}]

    def test_silent_when_they_agree(self):
        self.assertIsNone(check_revision(self.stored(4.0810), self.reading(4.0810)))

    def test_warns_when_aaa_revised(self):
        warning = check_revision(self.stored(4.0810), self.reading(4.0830))
        self.assertIsNotNone(warning)
        self.assertIn("4.0830", warning)
        self.assertIn("4.0810", warning)
        self.assertIn("+0.0020", warning)

    def test_silent_with_no_prior_row(self):
        self.assertIsNone(check_revision([], self.reading(4.0810)))


if __name__ == "__main__":
    unittest.main()
