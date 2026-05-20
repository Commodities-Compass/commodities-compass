# ICE COT EU Scraper

ICE Europe Commitments of Traders → `pl_cot_eu_weekly`. Weekly cadence (ICE publishes Fridays for Tuesday snapshots), daily idempotent UPSERT.

## Usage

```bash
poetry run ice-cot-eu-scraper                # current year, live
poetry run ice-cot-eu-scraper --dry-run      # fetch + parse + log only
poetry run ice-cot-eu-scraper --year 2024    # specific year (manual backfill)
poetry run ice-cot-eu-scraper --verbose      # debug logging
poetry run ice-cot-eu-scraper --force        # bypass non-trading-day skip
```

## Source

- URL template: `https://www.theice.com/publicdocs/futures/COTHistYYYY.csv`
- Free, no auth, UTF-8 BOM CSV (175 columns)
- One file per calendar year (~250 rows = ~52 weeks × 5 markets)
- We filter for `Market_and_Exchange_Names = "ICE Cocoa Futures - ICE Futures Europe"` + `FutOnly_or_Combined = "FutOnly"` (standard CFTC convention, matches R&D pipeline)

## Cron

`10 19 * * 1-5` — 19:10 UTC weekdays. Daily run is idempotent (UPSERT on `(release_date, contract_market)`); most weekdays are no-ops since ICE only publishes Fridays.

## Schema target

`pl_cot_eu_weekly`, multi-market via `contract_market` column (default `'cocoa'`). The `prod_merc_net` and `m_money_net` columns are **GENERATED ALWAYS** by Postgres — never written directly.

## Derived dates

- `report_date` = Tuesday snapshot (from CSV `As_of_Date_Form_MM/DD/YYYY`)
- `release_date` = `report_date + 3 days` = Friday publication (matches ICE/CFTC convention)
- UNIQUE on `(release_date, contract_market)`. The engine merges via `merge_asof backward` on `report_date`.

## Z-scores not stored here

Per `.claude/rules/north-star-alignment.md` (rolling normalization rule), the engine computes z-scores (26w) and percentiles in compute-time from this table's raw values.

## Fail-loud

- HTTP non-200 / network error / empty body → `IceCotEuScraperError`, exit 1, Sentry alert.
- No cocoa EU FutOnly rows in the CSV → fail (masks format change upstream).
- Per-row data corruption (bad date, missing position integer) → row skipped silently. Aggregate stats logged.
- No auto-retry, no fallback source. Aligned with `.claude/rules/pipeline-error-handling.md`.

## Tests

```bash
poetry run pytest tests/test_ice_cot_eu_scraper.py -v
```
