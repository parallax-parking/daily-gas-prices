# AAA national average scraper

Records "Today's AAA National Average" from <https://gasprices.aaa.com/> once a
day, one row per day, into [`data/aaa_national_average.csv`](../data/aaa_national_average.csv).

```
date,regular,mid_grade,premium,diesel,e85,retrieved_at_utc,source_url
2026-07-30,4.098,4.601,4.981,5.339,3.135,2026-07-30T12:45:38+00:00,https://gasprices.aaa.com/
```

`date` is the US Eastern date of the reading, since that's the clock AAA
publishes on. Re-running on the same day is a no-op unless you pass `--force`,
so the job is safe to retry.

## Scheduling

The scheduled run is [`.github/workflows/aaa-gas-prices.yml`](../.github/workflows/aaa-gas-prices.yml):
GitHub Actions fires it at 13:00 UTC daily (9am ET in summer, 8am in winter),
it scrapes, appends a row, and commits the CSV back to the repo. Nothing to
host or keep running.

Two things to know about Actions cron:

- **It only runs from the default branch.** The workflow has to be merged to
  `main` before the schedule takes effect — a cron on a feature branch never
  fires. The same goes for the **Run workflow** button: GitHub only lists
  `workflow_dispatch` workflows that exist on the default branch, though once
  it's there you can dispatch it against any branch. To try it before merging,
  run it locally (below).
- **Scheduled runs are best-effort.** GitHub delays or drops them under load,
  usually by minutes but occasionally longer, and disables schedules entirely
  after 60 days of no repository activity. The daily commit generally counts as
  activity, but if the run has been quiet for a while, check the Actions tab.
  Because the reading is keyed by date, a skipped day is a gap, not a
  duplicate — a manual dispatch that day fills it.

### Alternatives, if you'd rather not use Actions

- **cron on an always-on machine** (a home server or VPS — a laptop that sleeps
  will miss days):
  ```
  0 9 * * * cd /path/to/daily-gas-prices && /usr/bin/python3 scraper/aaa_gas_prices.py --out data/aaa_national_average.csv >> /tmp/aaa.log 2>&1
  ```
  On macOS use `launchd` instead; unlike cron, it runs jobs it missed while the
  machine was asleep.
- **Google Apps Script** with a time-driven trigger, if the Sheet is the only
  destination you care about. No repo, no runner — but you'd be rewriting the
  parser in Apps Script, and `UrlFetchApp` needs the same browser
  `User-Agent` spoof this script uses.
- **A scheduled cloud function** (Cloud Run Jobs + Cloud Scheduler, or Lambda +
  EventBridge) if you want the data in a database rather than a file. More
  reliable timing than Actions cron, and more setup.

## Google Sheets (optional)

The CSV is always written. To also append each row to a Sheet:

1. Create a Google Cloud service account, enable the Google Sheets API, and
   download its JSON key.
2. Share the target sheet with the service account's email as an **Editor**.
3. In the repo: add the JSON key's full contents as the secret
   `GOOGLE_SERVICE_ACCOUNT_JSON`, and the sheet ID (the long string in its URL)
   as the variable `AAA_SHEET_ID`.

The workflow picks both up automatically and installs the extra dependencies
only when `AAA_SHEET_ID` is set.

## Running it locally

```sh
pip install -r scraper/requirements.txt
python scraper/aaa_gas_prices.py --dry-run                       # print, store nothing
python scraper/aaa_gas_prices.py --out data/aaa_national_average.csv
python -m unittest discover -s scraper/tests
```

## When it breaks

AAA has no public API, so this parses the page. Two failure modes, both loud —
the script exits non-zero and the Actions run goes red:

- **403 on fetch.** AAA blocks non-browser clients; the script already sends a
  browser `User-Agent`. If they tighten this further, the fix is a headless
  browser rather than a header tweak.
- **"no 'Current Avg.' row found".** The page layout moved. The parser matches
  on table *shape* (a fuel-grade header plus a row labelled "Current Avg.")
  rather than CSS classes, so it tolerates re-themes, but not a restructure.
  Save a copy of the new page into `tests/fixtures/` and update
  `parse_national_average()`.

Please keep it to one request a day — the data only changes daily anyway.
