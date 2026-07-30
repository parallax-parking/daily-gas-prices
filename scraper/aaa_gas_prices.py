#!/usr/bin/env python3
"""Scrape "Today's AAA National Average" and append it to a daily time series.

Reads the fuel-gauge table at https://gasprices.aaa.com/ and records the
"Current Avg." row (Regular, Mid-Grade, Premium, Diesel, E85) as one row per
day in a CSV, and optionally appends the same row to a Google Sheet.

Running twice in one day is a no-op unless --force is passed, so the job is
safe to retry.

Usage:
    python aaa_gas_prices.py --out data/aaa_national_average.csv
    python aaa_gas_prices.py --out data/aaa_national_average.csv --sheet-id <id>
    python aaa_gas_prices.py --dry-run
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

SOURCE_URL = "https://gasprices.aaa.com/"

# AAA publishes on US Eastern time; the "date" of a reading is its ET date.
EASTERN = ZoneInfo("America/New_York")

# AAA rejects requests that don't look like a browser (403 with an empty body).
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Column order in the CSV. Grade keys match normalize_grade() output.
GRADES = ["regular", "mid_grade", "premium", "diesel", "e85"]
FIELDNAMES = ["date", *GRADES, "retrieved_at_utc", "source_url"]


class ScrapeError(RuntimeError):
    """The page could not be fetched, or its national-average table moved."""


@dataclass
class Reading:
    date: str
    prices: dict[str, float | None]
    retrieved_at_utc: str

    def as_row(self) -> dict[str, object]:
        row: dict[str, object] = {"date": self.date}
        for grade in GRADES:
            value = self.prices.get(grade)
            row[grade] = "" if value is None else f"{value:.3f}"
        row["retrieved_at_utc"] = self.retrieved_at_utc
        row["source_url"] = SOURCE_URL
        return row


def fetch(url: str = SOURCE_URL, attempts: int = 4, timeout: int = 30) -> str:
    """GET the page, retrying transient failures with exponential backoff."""
    last_error: Exception | None = None
    for attempt in range(attempts):
        if attempt:
            time.sleep(2**attempt)
        try:
            response = requests.get(url, headers=HEADERS, timeout=timeout)
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            last_error = exc
    raise ScrapeError(f"could not fetch {url} after {attempts} attempts: {last_error}")


def normalize(text: str) -> str:
    """Collapse whitespace (including &nbsp;) and lowercase."""
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip().lower()


def normalize_grade(header: str) -> str | None:
    """Map a column header to a CSV key, or None if it isn't a fuel grade."""
    key = re.sub(r"[^a-z0-9]+", "_", normalize(header)).strip("_")
    aliases = {
        "regular": "regular",
        "mid_grade": "mid_grade",
        "midgrade": "mid_grade",
        "mid": "mid_grade",
        "plus": "mid_grade",
        "premium": "premium",
        "diesel": "diesel",
        "e85": "e85",
    }
    return aliases.get(key)


def parse_price(text: str) -> float | None:
    """Pull a dollar figure out of a cell; None for 'N/A' and friends."""
    match = re.search(r"\d+(?:\.\d+)?", text.replace(",", ""))
    return float(match.group()) if match else None


def parse_national_average(html: str) -> dict[str, float | None]:
    """Extract the Current Avg. prices from the national-average table.

    Matched by shape rather than by CSS class: the table we want has a header
    containing fuel grades and a row labelled "Current Avg.". That survives the
    theme changes that break class-based selectors.
    """
    soup = BeautifulSoup(html, "html.parser")

    for table in soup.find_all("table"):
        header_cells = table.find_all("th")
        grades = [normalize_grade(cell.get_text()) for cell in header_cells]
        if "regular" not in grades:
            continue

        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if len(cells) < 2 or not normalize(cells[0].get_text()).startswith("current"):
                continue

            # The header's leading cell is a blank corner; drop leading
            # non-grade headers so grades line up with the value cells.
            offset = next((i for i, g in enumerate(grades) if g), 0)
            aligned = grades[offset:]
            values = cells[1:]
            if len(aligned) != len(values):
                continue

            prices = {
                grade: parse_price(cell.get_text())
                for grade, cell in zip(aligned, values)
                if grade
            }
            if prices.get("regular") is not None:
                return prices

    raise ScrapeError(
        "no 'Current Avg.' row found under a fuel-grade header — the AAA page "
        "layout likely changed; re-check the selectors in parse_national_average()"
    )


def scrape(url: str = SOURCE_URL) -> Reading:
    now_utc = datetime.now(timezone.utc)
    return Reading(
        date=now_utc.astimezone(EASTERN).strftime("%Y-%m-%d"),
        prices=parse_national_average(fetch(url)),
        retrieved_at_utc=now_utc.replace(microsecond=0).isoformat(),
    )


def read_existing(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, reading: Reading, force: bool = False) -> bool:
    """Append the reading. Returns False if the date was already recorded."""
    rows = read_existing(path)
    existing = next((r for r in rows if r.get("date") == reading.date), None)

    if existing and not force:
        return False
    if existing:
        rows[rows.index(existing)] = {k: str(v) for k, v in reading.as_row().items()}
    else:
        rows.append({k: str(v) for k, v in reading.as_row().items()})

    rows.sort(key=lambda r: r.get("date", ""))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows([{k: row.get(k, "") for k in FIELDNAMES} for row in rows])
    return True


def append_to_sheet(sheet_id: str, reading: Reading, worksheet: str = "Sheet1") -> None:
    """Append the reading to a Google Sheet.

    Requires `pip install gspread google-auth` and service-account credentials
    in GOOGLE_SERVICE_ACCOUNT_JSON (the raw JSON, not a path). Share the sheet
    with the service account's email as an Editor first.
    """
    import json

    import gspread
    from google.oauth2.service_account import Credentials

    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        raise ScrapeError("GOOGLE_SERVICE_ACCOUNT_JSON is not set")

    credentials = Credentials.from_service_account_info(
        json.loads(raw),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    sheet = gspread.authorize(credentials).open_by_key(sheet_id).worksheet(worksheet)

    if not sheet.get_all_values():
        sheet.append_row(FIELDNAMES, value_input_option="USER_ENTERED")
    if reading.date in sheet.col_values(1):
        print(f"sheet already has {reading.date}; skipping append")
        return

    row = reading.as_row()
    sheet.append_row([str(row[k]) for k in FIELDNAMES], value_input_option="USER_ENTERED")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("data/aaa_national_average.csv"))
    parser.add_argument("--url", default=SOURCE_URL)
    parser.add_argument(
        "--sheet-id",
        default=os.environ.get("AAA_SHEET_ID", ""),
        help="Google Sheet ID to append to (also read from $AAA_SHEET_ID)",
    )
    parser.add_argument("--worksheet", default="Sheet1")
    parser.add_argument("--force", action="store_true", help="overwrite today's row")
    parser.add_argument("--dry-run", action="store_true", help="print, don't store")
    args = parser.parse_args(argv)

    try:
        reading = scrape(args.url)
    except ScrapeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    summary = "  ".join(
        f"{g}={reading.prices[g]:.3f}" for g in GRADES if reading.prices.get(g) is not None
    )
    print(f"{reading.date}  {summary}")

    if args.dry_run:
        return 0

    if write_csv(args.out, reading, force=args.force):
        print(f"wrote {args.out}")
    else:
        print(f"{args.out} already has {reading.date}; use --force to overwrite")

    if args.sheet_id:
        append_to_sheet(args.sheet_id, reading, worksheet=args.worksheet)
        print(f"appended to sheet {args.sheet_id}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
