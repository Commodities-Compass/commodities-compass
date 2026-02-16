# Quick Setup Guide

## Current Status

✅ All code complete and ready for testing
✅ Playwright installed in Poetry dev dependencies
✅ WebKit browser downloaded
✅ IV extraction pattern verified (48.99% extracted successfully from CAK26)

## Next Steps

### 1. Configure Credentials (5 min)

```bash
cd backend/scripts/barchart_scraper
cp .env.example .env
```

Edit `.env` and add your Google Sheets credentials:

```bash
GOOGLE_SHEETS_CREDENTIALS_JSON='{"type":"service_account",...}'
```

**To get credentials:**
1. GCP Console → IAM & Admin → Service Accounts
2. Find `commodities-compass-sheets@cacaooo.iam.gserviceaccount.com`
3. Keys → Add Key → Create new key → JSON
4. Copy entire JSON into `.env`

### 2. First Dry Run (2 min)

```bash
cd /Users/hediblagui/Developer/work/commodities-compass
poetry run python -m backend.scripts.barchart_scraper.main --dry-run --verbose
```

**Expected output:**
```
INFO - Fetching https://www.barchart.com/futures/quotes/CC*0/overview
INFO - Extracted from raw block: H=... L=... C=... V=... OI=...
INFO - Fetching https://www.barchart.com/futures/quotes/CAK26/volatility-greeks...
INFO - Extracted IV: 48.99
INFO - Validation passed
INFO - [DRY RUN] Would append to 'TECHNICALS_STAGING': ['02/16/2026', ...]
INFO - SUCCESS
```

### 3. Create Staging Sheet (5 min)

1. Open: https://docs.google.com/spreadsheets/d/16VXIrG9ybjjaorTeiR8sh5nrPIj9I7EFGr2iBSAjSSA/edit
2. Right-click **TECHNICALS** tab → Duplicate
3. Rename to: `TECHNICALS_STAGING`
4. Clear all data rows (keep header row)

### 4. First Staging Write (1 min)

```bash
poetry run python -m backend.scripts.barchart_scraper.main --sheet=staging
```

Verify in Google Sheets:
- Row appended to TECHNICALS_STAGING
- Columns A-G filled with today's data
- Formulas in columns J-AT auto-calculate

### 5. Compare with Barchart.com (2 min)

Open Barchart manually:
- Prices: https://www.barchart.com/futures/quotes/CC*0/overview
- IV: https://www.barchart.com/futures/quotes/CAK26/volatility-greeks

Compare scraped values with browser display.

## Troubleshooting

### "Module not found: backend.scripts..."

Run from project root:
```bash
cd /Users/hediblagui/Developer/work/commodities-compass
poetry run python -m backend.scripts.barchart_scraper.main --dry-run
```

### "GOOGLE_SHEETS_CREDENTIALS_JSON not set"

Create `.env` file in `backend/scripts/barchart_scraper/` with credentials.

Or set environment variable:
```bash
export GOOGLE_SHEETS_CREDENTIALS_JSON='{"type":"service_account",...}'
```

### "Playwright browser not found"

Install browsers:
```bash
poetry run playwright install webkit
```

## Timeline

**Today (Day 1)**:
- ✅ Code complete (30 min - DONE)
- ⏳ Configure credentials (5 min)
- ⏳ Dry run test (2 min)
- ⏳ Staging write (1 min)

**Tomorrow (Day 2)**:
- Parallel test #1 (scraper → staging, Julien → production, compare)

**Days 3-4**:
- Parallel test #2-3

**Days 5-6**:
- Production cutover
- Monitor downstream pipeline

## Files Created

```
backend/scripts/barchart_scraper/
├── __init__.py           # Package init
├── config.py             # URLs, mappings, validation ranges
├── scraper.py            # Playwright scraper (proven patterns from backend/scraper.py)
├── validator.py          # Data validation
├── sheets_writer.py      # Google Sheets API writer
├── main.py               # CLI orchestrator
├── requirements.txt      # Dependencies
├── .env.example          # Credentials template
├── README.md             # Full documentation
├── SETUP.md              # This file
└── tests/                # Test directory (empty)
```

## Key Decisions Made

1. **Playwright instead of httpx** - Barchart requires browser automation
2. **Reused proven patterns** from `backend/scraper.py` (extract_ohlc_data function)
3. **Isolated location** - `backend/scripts/` for easy rollback
4. **IV pattern confirmed** - `Implied Volatility[^>]*>(\d+(?:\.\d+)?)%` works (tested on CAK26)
5. **Poetry dev dependency** - Playwright added to dev group

## Rollback Plan

If scraper fails validation:
```bash
# Remove scraper directory
rm -rf backend/scripts/barchart_scraper

# Remove Playwright from Poetry (optional)
poetry remove playwright --group dev
```

No production code affected - completely isolated.
