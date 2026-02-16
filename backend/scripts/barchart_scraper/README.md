# Barchart Scraper — London Cocoa Futures

Automates daily data collection for Commodities Compass.

## What It Does

Scrapes 6 fields from Barchart.com for London cocoa front-month futures (CC*0):
- **Close**, **High**, **Low**: Price data (GBP/tonne)
- **Volume**: Trading volume (contracts × 10 = tonnes)
- **Open Interest**: Open interest (contracts)
- **Implied Volatility**: Percentage (from volatility-greeks page)

Writes to Google Sheets **TECHNICALS** tab (replaces manual Google Form entry).

## Architecture

- **Browser**: Playwright (WebKit on macOS, Chromium on Linux) — proven working patterns from `backend/scraper.py`
- **Extraction**: Regex patterns matching Barchart's embedded JSON data blocks
- **Validation**: Range checks, logical checks (HIGH ≥ CLOSE ≥ LOW), non-null checks
- **Output**: Google Sheets API (append row to TECHNICALS or TECHNICALS_STAGING)

## Setup

### 1. Install Playwright browsers

```bash
cd backend/scripts/barchart_scraper
playwright install webkit chromium
```

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure credentials

```bash
cp .env.example .env
# Edit .env and add GOOGLE_SHEETS_CREDENTIALS_JSON
```

To get Google Sheets credentials:
1. Go to GCP Console → IAM & Admin → Service Accounts
2. Find `commodities-compass-sheets@cacaooo.iam.gserviceaccount.com`
3. Keys → Add Key → Create new key → JSON
4. Copy the entire JSON content into `.env` as `GOOGLE_SHEETS_CREDENTIALS_JSON='...'`

### 4. Verify service account scope

The service account must have **write** access to Google Sheets:
- Required scope: `https://www.googleapis.com/auth/spreadsheets` (read-write)
- Check: The code uses this scope by default in `sheets_writer.py`

## Usage

### Dry run (test without writing)

```bash
python -m backend.scripts.barchart_scraper.main --dry-run
```

### Write to staging sheet

```bash
python -m backend.scripts.barchart_scraper.main --sheet=staging
```

### Write to production

```bash
python -m backend.scripts.barchart_scraper.main --sheet=production
```

### Debug mode (verbose logs)

```bash
python -m backend.scripts.barchart_scraper.main --verbose --dry-run
```

### Headful mode (visible browser, for debugging)

```bash
python -m backend.scripts.barchart_scraper.main --headful --dry-run
```

## Testing Workflow

### Phase 1: Dry Run (Day 1)

1. Run dry-run to test scraping + validation without writing:
   ```bash
   python -m backend.scripts.barchart_scraper.main --dry-run --verbose
   ```

2. Expected output:
   ```
   INFO - Fetching https://www.barchart.com/futures/quotes/CC*0/overview
   INFO - Extracted from raw block: H=2750.0 L=2720.0 C=2736.0 V=50480.0 OI=42150.0
   INFO - Fetching https://www.barchart.com/futures/quotes/CAK26/volatility-greeks?futuresOptionsView=merged
   INFO - Extracted IV: 51.15
   INFO - Validation passed
   INFO - [DRY RUN] Would append to 'TECHNICALS_STAGING': ['02/16/2026', 2736.0, 2750.0, 2720.0, 50480.0, 42150.0, 51.15]
   INFO - SUCCESS
   ```

3. Manually verify values against Barchart.com in browser

### Phase 2: Staging Write (Day 2)

1. Create staging sheet (if not exists):
   - Open Google Sheets
   - Duplicate TECHNICALS tab → rename to TECHNICALS_STAGING
   - Clear data rows (keep header)

2. Run staging write:
   ```bash
   python -m backend.scripts.barchart_scraper.main --sheet=staging
   ```

3. Verify in Google Sheets:
   - Row appended to TECHNICALS_STAGING
   - Columns A-G filled
   - Formulas in columns J-AT auto-calculate

### Phase 3: Parallel Testing (Days 3-5)

Run scraper → staging each day alongside Julien's manual → production entry:

```bash
# Daily at 7:00 PM
python -m backend.scripts.barchart_scraper.main --sheet=staging

# Then Julien fills manual form → production at 8:00 PM
# Compare outputs at 9:00 PM
```

Compare 6 fields side-by-side:
- Price fields (CLOSE/HIGH/LOW): Delta ≤ 0.5 GBP
- Volume/OI: Delta ≤ 100 contracts
- IV: Delta ≤ 0.5%

### Phase 4: Production Cutover (Day 6-7)

After 3 successful parallel tests:

```bash
python -m backend.scripts.barchart_scraper.main --sheet=production
```

Monitor downstream pipeline:
- Make.com DAILY BOT AI (~11:00 PM)
- Railway Daily Import (~11:15 PM)
- Dashboard displays correctly

## Rollback Procedure

If scraper fails or produces bad data:

1. **Stop using scraper** — revert to manual Google Form entry
2. **Delete bad rows** from TECHNICALS sheet (if any written)
3. **Delete scraper directory** (isolated in `backend/scripts/`, safe to remove):
   ```bash
   rm -rf backend/scripts/barchart_scraper
   ```
4. No production code affected — API/ETL/Dashboard unchanged

## Troubleshooting

### Issue: "Pattern not found in HTML"

**Cause**: Barchart changed HTML structure
**Fix**: Inspect page source, update regex patterns in `scraper.py`

### Issue: "Validation failed: Field 'X' outside valid range"

**Cause**: Scraped value is legitimate but outside expected range
**Fix**: Adjust `VALIDATION_RANGES` in `config.py`

### Issue: "Failed to extract Implied Volatility"

**Cause**: volatility-greeks page structure different than expected
**Fix**: Run with `--headful --verbose`, inspect IV page, update `extract_implied_volatility()` patterns

### Issue: "Google Sheets API error: 403 Forbidden"

**Cause**: Service account lacks write permission
**Fix**: Verify scope in code (`SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]`), re-download service account key if needed

### Issue: Playwright browser not found

**Cause**: Playwright browsers not installed
**Fix**: Run `playwright install webkit chromium`

## Deployment

**Week 1 (Manual)**: Run locally as replacement for browser workflow

**Week 2+ (Automated)**: Schedule via GCP Cloud Scheduler + Cloud Run Job (daily 7:00 PM CET)

## Files

- `config.py` — URLs, mappings, validation ranges
- `scraper.py` — Playwright scraper with proven regex patterns
- `validator.py` — Data validation logic
- `sheets_writer.py` — Google Sheets API writer
- `main.py` — CLI orchestrator
- `requirements.txt` — Python dependencies
- `.env.example` — Credentials template
- `README.md` — This file

## References

- Original scraper: `backend/scraper.py` (proven working Playwright + regex patterns)
- Plan document: `experiments/Quick_Win_Daily_Bot/quickwin-1-barchart-scraper-implementation-plan.md`
- Daily process: `experiments/Quick_Win_Daily_Bot/daily-process-documentation.md`
