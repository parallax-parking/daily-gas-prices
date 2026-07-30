"""Parser tests against a saved copy of the AAA fuel-gauge table markup.

Run with: python -m unittest discover -s scraper/tests
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aaa_gas_prices import (  # noqa: E402
    Reading,
    ScrapeError,
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
            self.assertEqual(rows[1]["regular"], "4.091")
            self.assertEqual(rows[1]["premium"], "")

            # ...unless forced.
            self.assertTrue(write_csv(path, self.reading("2026-07-30", 9.999), force=True))
            self.assertEqual(read_existing(path)[1]["regular"], "9.999")

    def test_keeps_rows_sorted_by_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.csv"
            write_csv(path, self.reading("2026-07-30", 4.091))
            write_csv(path, self.reading("2026-07-28", 4.071))
            self.assertEqual(
                [r["date"] for r in read_existing(path)],
                ["2026-07-28", "2026-07-30"],
            )


if __name__ == "__main__":
    unittest.main()
