# daily-gas-prices

A daily probabilistic forecast of the AAA national average gas price, and an
auditable record of how well calibrated it is.

**The forecast is not the product. The calibration record is.** Anyone can guess
gas prices. What's useful is knowing how much to trust the guesses — so that
when this says "70%", you know from accumulated evidence that those turn out
true about 70% of the time.

## Where to look

| | |
|---|---|
| **[Dashboard](https://parallax-parking.github.io/daily-gas-prices/)** | How trustworthy the model is right now, and tomorrow's price range. Start here. |
| [`CONTEXT.md`](CONTEXT.md) | The full report behind the dashboard, regenerated every morning. |
| [`DESIGN.md`](DESIGN.md) | Why everything is the way it is, including what was tried and rejected. |
| [`data/aaa_national_average.csv`](data/aaa_national_average.csv) | One observation per day. |
| [`data/forecasts.csv`](data/forecasts.csv) | One forecast per day, append-only, never edited. |
| [`scraper/`](scraper/README.md) | Collection. |
| [`forecast/`](forecast/README.md) | Forecasting and scoring. |

## How it runs

A GitHub Actions job fires daily at 13:17 UTC and, in one job so the three
steps share a working tree and land in a single commit:

1. scrapes today's AAA national average
2. scores yesterday's forecast against what actually happened, regenerating
   both `CONTEXT.md` and the dashboard from the same joined record
3. writes a new forecast for tomorrow

The dashboard is plain static HTML in `docs/`, served by GitHub Pages from
`main`. No scripts, no external requests, no second workflow — it updates
because the daily commit includes it.

A weekly Claude Code Routine reads the record each Monday and opens an issue
only if something is wrong — see [`forecast/REVIEW_ROUTINE.md`](forecast/REVIEW_ROUTINE.md).

## Provenance

This project began in
[`parallax-parking/nantucket-late-august`](https://github.com/parallax-parking/nantucket-late-august)
and moved here on 2026-08-06 with **full commit history preserved**.

That preservation is not housekeeping. The record's evidentiary value rests on
forecasts having been committed *before* their outcomes existed, and git commit
timestamps are the only proof of that. Every row of `data/forecasts.csv` also
carries the `git_sha` of the commit that produced it; those SHAs resolve in this
repository because the history was moved rather than rewritten.

Commits before 2026-08-06 therefore include some unrelated to gas prices — the
original repository hosted a trip-planning page, whose files were removed in the
migration commit but remain in the history. That noise is the price of keeping
the audit trail intact, and it was the right trade.
