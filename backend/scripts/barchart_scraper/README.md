# Barchart Scraper — London Cocoa Futures

Automates daily data collection for Commodities Compass (columns A–G of TECHNICALS sheet).

## What It Does

Scrapes 6 fields from Barchart.com for the active London cocoa #7 contract (ICE Europe, GBP/tonne):
- **Close**, **High**, **Low**: Price data (GBP/tonne)
- **Volume**: Trading volume (raw contracts)
- **Open Interest**: Open interest (contracts)
- **Implied Volatility**: Percentage (from volatility-greeks page)

Writes to Google Sheets **TECHNICALS** tab (replaces manual Google Form entry).

## Contract Selection & Roll Logic

The scraper targets a **specific contract code** (e.g., `CAH26`), never Barchart's `CA*0` continuous alias. We control the roll, not Barchart.

**Roll rule:** Switch to the next contract **15 calendar days before expiry** (last business day of the delivery month). This avoids near-expiry bias on both prices and IV.

**Delivery months:** H(Mar), K(May), N(Jul), U(Sep), Z(Dec)

**Example (2026):**
- CAH26 expires ~March 31 → roll date March 16
- Before March 16: scrape `CAH26/overview` + `CAH26/volatility-greeks`
- From March 16: scrape `CAK26/overview` + `CAK26/volatility-greeks`

**Why not CA\*0?** Barchart's continuous symbol rolls based on their own volume-shift heuristic, which doesn't match our 15-day rule. In Feb 2026, Barchart had already rolled CA\*0 to CAK26 (May) while we should still track CAH26 (March). Using CA\*0 means scraping the wrong contract → wrong OI and volume data.

## Architecture

- **Browser**: Playwright (WebKit on macOS, Chromium on Linux/Railway)
- **Extraction**: Two strategies with fallback:
  1. **Primary — HTML inline JSON** (has all 6 fields including OI): Finds ALL `"raw"` JSON blocks in server-rendered HTML, picks the one with highest volume (max-volume heuristic). The main contract always has the highest volume among the 4+ blocks on the page.
  2. **Backup — XHR interception** (C/H/L/V only, no OI): Intercepts Barchart's internal API responses via `page.on("response")`. API omits `openInterest`.
- **IV**: Separate page (`/volatility-greeks`). XHR interception primary, HTML regex fallback.
- **Validation**: Range checks, logical checks (HIGH ≥ CLOSE ≥ LOW), non-null checks
- **Output**: Google Sheets API (append row to TECHNICALS or TECHNICALS_STAGING)

### Barchart Page Structure

Barchart is an Angular SPA. Key observations (2026-02-18 investigation):

- **4+ raw blocks** in server-rendered HTML: main quote, next-month contract, related instruments. Only 1 block has complete OHLCV+OI data (the main quote with highest volume).
- **XHR API** (`/proxies/core-api/v1/quotes/get`): Returns C/H/L/V for all contract months as formatted strings, but **omits OI entirely**.
- **`networkidle` never fires** due to persistent analytics/ad polling. Use `wait_until="load"` + fixed 5s wait.
- **`x-xsrf-token`** required for direct API calls — not viable for scraping.

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
# Edit .env and add GOOGLE_SHEETS_SCRAPER_CREDENTIALS_JSON
```

## Usage

```bash
# Dry run (scrape + validate, no Sheets write)
poetry run python -m scripts.barchart_scraper.main --dry-run --verbose

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

## Troubleshooting

### "Failed to extract data from both HTML and XHR"
Barchart changed their HTML structure or Angular app. Run `--headful --verbose`, inspect page source, check if `"raw"` blocks still exist with `lastPrice`/`highPrice`/`lowPrice`/`volume`/`openInterest` fields.

### "Close price is None after extraction"
HTML raw block exists but doesn't contain `lastPrice`. Check if Barchart renamed the field in their inline JSON.

### Wrong OI or Volume values
The max-volume heuristic should pick the correct block. If values look wrong, run the diagnostic script to dump all raw blocks and identify which block was selected. Check that the contract code in the URL matches the expected active contract.

### "Page timeout but XHR data captured — continuing"
Normal. Barchart never reaches `networkidle`. If XHR data was captured, the scraper continues. OI will be missing (XHR doesn't include it) — falls back to HTML extraction.

## Files

- `config.py` — URLs (via roll logic), column mappings, validation ranges, browser settings
- `scraper.py` — Playwright scraper with HTML + XHR extraction
- `validator.py` — Data validation logic
- `sheets_writer.py` — Google Sheets API writer
- `main.py` — CLI orchestrator

## Known Issues & Forensics (2026-02-18)

### Wrong raw block selection (old scraper)
The original scraper used `re.search` (finds FIRST match) on Barchart HTML that contains 4+ `"raw"` JSON blocks. It non-deterministically picked the wrong block → garbage V and OI.

**Forensic proof (CAH26 page, Feb 18):**
- Block 0: CAK26 partial (Close only, no V/OI)
- Block 2: Main quote (Close=2311, V=1383, **OI=36,333**)
- Only Block 2 has complete data

The prod manual entry of OI=36,333 came from looking at the **CAH26 page** (March, expiring). The correct front-month (CAK26, May) has OI=52,754. The `previousPrice=2438` on CAH26 matched the prod Close exactly — confirming the human was reading the wrong contract.

### CA*0 vs specific contract
Barchart's `CA*0` continuous symbol had already rolled to CAK26 in February, before our 15-day window. Using CA*0 meant scraping CAK26 data when we should track CAH26. Fixed by using explicit contract codes for both prices and IV URLs.
