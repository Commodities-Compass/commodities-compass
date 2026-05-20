# Barchart Stocks EU Scraper

Fetches ICE Europe certified cocoa stocks (in 60kg bags) from Barchart cmdty
and updates `pl_contract_data_daily.stock_eu_bags60kg` for the row matching
the most recent reported date.

## Source

- URL: <https://www.barchart.com/cmdty/data/fundamental/explore/IC345DRW.CS>
- No authentication required (public commodity statistics page).
- HTML server-rendered, two `<table class="cmdty-quote-table">` blocks:
  1. Metadata (Most Recent Value/Date, Unit, Multiplier, Prior Value, ...).
  2. 7-day history (date → value).
- Native unit: `60 Kg Bag` (Multiplier 1). No conversion at write time.

## Usage

```bash
poetry run barchart-stocks-eu-scraper            # live (skips non-trading days)
poetry run barchart-stocks-eu-scraper --dry-run  # log only
poetry run barchart-stocks-eu-scraper --force    # bypass trading-day skip
poetry run barchart-stocks-eu-scraper --verbose  # DEBUG logging
```

## Schedule

Daily 19:10 UTC weekdays (10 min after the OHLCV `barchart-scraper`). The
OHLCV row must exist first — this scraper UPDATEs, never INSERTs.

## Fail-loud guarantees

- HTTP non-200 → `BarchartStocksEuScraperError`
- Empty body → `BarchartStocksEuScraperError`
- Missing `cmdty-quote-table` → `BarchartStocksEuParseError`
- Unexpected `Unit` (≠ "60 Kg Bag") → `BarchartStocksEuParseError`
- Unexpected `Multiplier` (≠ "1") → `BarchartStocksEuParseError`
- Missing OHLCV row for target date → `StockEuRowMissingError` (no row updated)

Per `.claude/rules/pipeline-error-handling.md`: no auto-retry, no silent
fallback. Pipeline operators must diagnose and re-run manually after a fix.
