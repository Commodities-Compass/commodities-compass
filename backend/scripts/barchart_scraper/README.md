# Barchart Scraper — London Cocoa Futures

Automates daily data collection for Commodities Compass (columns A–G of TECHNICALS sheet).

## What It Does

Scrapes 6 fields from Barchart.com for the active London cocoa #7 contract (ICE Europe, GBP/tonne):
- **Close**, **High**, **Low**: Price data (GBP/tonne)
- **Volume**: Trading volume (raw contracts)
- **Open Interest**: Open interest (contracts)
- **Implied Volatility**: Percentage (from volatility-greeks page)

Dual-writes to **GCP Cloud SQL** (`pl_contract_data_daily`) and **Google Sheets** TECHNICALS tab.

## Contract Selection

The active contract is set via the **`ACTIVE_CONTRACT`** environment variable (e.g., `CAK26`). This drives:
- **Barchart URLs**: `https://www.barchart.com/futures/quotes/CAK26/overview`
- **IV URL**: `https://www.barchart.com/futures/quotes/CAK26/volatility-greeks`

There is no automatic roll logic. Contract switches are explicit — set the env var when ready to roll.

**Delivery months:** H(Mar), K(May), N(Jul), U(Sep), Z(Dec)

**Why not CA\*0?** Barchart's continuous symbol rolls based on their own volume-shift heuristic. Using explicit contract codes ensures we scrape exactly the contract we intend.

## Architecture

- **Browser**: Playwright (WebKit on macOS, Chromium on Linux/Railway)
- **Extraction**: Two strategies with fallback:
  1. **Primary — HTML inline JSON** (has all 6 fields including OI): Finds ALL `"raw"` JSON blocks in server-rendered HTML, picks the one with highest volume (max-volume heuristic).
  2. **Backup — XHR interception** (C/H/L/V only, no OI): Intercepts Barchart's internal API responses via `page.on("response")`. API omits `openInterest`.
- **IV**: Separate page (`/volatility-greeks`). XHR interception primary, HTML regex fallback.
- **Validation**: Range checks, logical checks (HIGH ≥ CLOSE ≥ LOW), non-null checks
- **DB Output**: GCP PostgreSQL `pl_contract_data_daily` table (upsert by date+contract_id). Contract resolved via `resolve_by_code()` using `ACTIVE_CONTRACT` env var. IV converted from percentage to decimal (/ 100).
- **Sheets Output**: Google Sheets API (append row to TECHNICALS or TECHNICALS_STAGING)
- **Post-write**: After appending, writes CONCLUSION formula to column AS of the new row. This formula scores INDICATOR decisions (OPEN/HEDGE/MONITOR) against next-day price moves for YTD performance tracking.
- **Dual-write**: DB write is non-blocking — if it fails, Sheets write still proceeds. DB write happens first.

### Barchart Page Structure

Barchart is an Angular SPA. Key observations (2026-02-18 investigation):

- **4+ raw blocks** in server-rendered HTML: main quote, next-month contract, related instruments. Only 1 block has complete OHLCV+OI data (the main quote with highest volume).
- **XHR API** (`/proxies/core-api/v1/quotes/get`): Returns C/H/L/V for all contract months as formatted strings, but **omits OI entirely**.
- **`networkidle` never fires** due to persistent analytics/ad polling. Use `wait_until="load"` + fixed 5s wait.

### IV Conversion

- **Volume**: Raw contract count from Barchart (no conversion)
- **IV**: Sheets stores as decimal (e.g., Barchart shows `55.38%` → scraper sends `0.5538`)

## Setup

### 1. Install Playwright browsers

```bash
cd backend
playwright install webkit chromium
```

### 2. Install Python dependencies

```bash
poetry install
```

### 3. Configure credentials

```bash
cp .env.example .env
# Edit .env and add:
#   GOOGLE_SHEETS_SCRAPER_CREDENTIALS_JSON
#   ACTIVE_CONTRACT=CAK26
```

## Usage

```bash
# Dry run (scrape + validate, no Sheets write)
ACTIVE_CONTRACT=CAK26 poetry run python -m scripts.barchart_scraper.main --dry-run --verbose

# Write to staging sheet
poetry run python -m scripts.barchart_scraper.main --sheet staging

# Write to production
poetry run python -m scripts.barchart_scraper.main --sheet production

# Headful mode (visible browser, for debugging)
poetry run python -m scripts.barchart_scraper.main --headful --dry-run
```

## Deployment

| Setting | Value |
|---------|-------|
| **Root directory** | `backend` |
| **Start command** | Dockerfile-based |
| **Cron schedule** | `0 21 * * 1-5` (9 PM UTC weekdays only) |
| **Restart policy** | Never (cron job) |
| **Required env vars** | `ACTIVE_CONTRACT`, `GOOGLE_SHEETS_SCRAPER_CREDENTIALS_JSON`, `DATABASE_SYNC_URL` (GCP Cloud SQL) |

## Troubleshooting

### "ACTIVE_CONTRACT env var not set"
Set `ACTIVE_CONTRACT` to the current contract code (e.g., `CAK26`) in Railway or `.env`.

### "Failed to extract data from both HTML and XHR"
Barchart changed their HTML structure or Angular app. Run `--headful --verbose`, inspect page source, check if `"raw"` blocks still exist with `lastPrice`/`highPrice`/`lowPrice`/`volume`/`openInterest` fields.

### Wrong OI or Volume values
The max-volume heuristic should pick the correct block. If values look wrong, run the diagnostic script to dump all raw blocks and identify which block was selected. Check that the contract code in the URL matches the expected active contract.

## Files

- `config.py` — Contract resolution, sheet names, validation ranges, browser settings
- `scraper.py` — Playwright scraper with HTML + XHR extraction
- `validator.py` — Data validation logic
- `db_writer.py` — GCP PostgreSQL writer (`write_ohlcv()` upsert to `pl_contract_data_daily`)
- `sheets_writer.py` — Google Sheets API writer
- `main.py` — CLI orchestrator (dual-write: DB then Sheets)
