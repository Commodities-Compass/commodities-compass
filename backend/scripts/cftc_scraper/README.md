# CFTC Scraper - Simple Daily Scraper

Standalone scraper for CFTC Commitments of Traders data (COM NET US field).

## Features

- **Simple daily execution**: Scrapes CFTC data and updates Google Sheets
- **Last row update**: Finds last row with date and updates column I
- **Dry-run mode**: Test without writing to sheets
- **Environment selection**: Staging or production sheets

## Usage

### Local Development

```bash
# Test scrape (dry run)
poetry run python -m scripts.cftc_scraper.main --dry-run --sheet=staging

# Live run (staging)
poetry run python -m scripts.cftc_scraper.main --sheet=staging

# Live run (production) - ⚠️ Use with caution
poetry run python -m scripts.cftc_scraper.main --sheet=production
```

### Environment Variables

Required:
- `GOOGLE_SHEETS_SCRAPER_CREDENTIALS_JSON` - Google Sheets service account credentials

## Deployment (Railway)

### Setup

1. **Create new Railway service**: "cftc-scraper"

2. **Configure environment variables** (Railway dashboard):
   ```
   GOOGLE_SHEETS_SCRAPER_CREDENTIALS_JSON=<json-credentials>
   ```

3. **Set cron schedule** (Railway settings):
   - **Cron expression**: `0 19 * * *` (Every day at 19:00 UTC = 8:00 PM CET)
   - **Command**: `poetry run python -m scripts.cftc_scraper.main --sheet=staging`
   - ⚠️ **Start with staging** for initial testing

### Why Daily?

- Simple approach - runs every day regardless of CFTC publication schedule
- CFTC publishes Fridays at 3:30 PM ET (9:30 PM CET)
- Can optimize later to only run after new publication

## How It Works

1. **Download CFTC report** from Agriculture Long Format page
2. **Parse cocoa section** to extract Producer/Merchant Long/Short positions
3. **Calculate COM NET US** = Long - Short
4. **Validate range** (-100k to +100k)
5. **Find last row** with date in column A of TECHNICALS sheet
6. **Update column I** of that row with COM NET US value

## Sheet Structure

### Data Column
- **Column I** (index 8): COM NET US values

### Update Logic
- Finds last row with date in column A
- Updates column I of that row only
- No metadata, no forward-fill

## Error Handling

- **Scraping error**: Logs error, exit 1
- **Sheets error**: Logs error, exit 1
- **Unexpected error**: Logs error, exit 1

## Testing

```bash
# Test scraper only (no sheets)
poetry run python -c "
from scripts.cftc_scraper.scraper import CFTCScraper
scraper = CFTCScraper()
result = scraper.scrape()
print(f'COM NET US: {result:,.0f}')
"

# Test full flow (dry run)
poetry run python -m scripts.cftc_scraper.main --dry-run --sheet=staging
```

## Monitoring

### Logs
- Local: `cftc_scraper.log`
- Railway: Cloud Logs in Railway dashboard

### Success Criteria
- Exit code 0
- "SUCCESS" in logs
- Google Sheets column I updated with new value

## Maintenance

### Daily Schedule
- **19:00 UTC (8:00 PM CET)**: Automated run via Railway cron

### Manual Run
If automation fails, run manually:

```bash
# Via Railway CLI
railway run poetry run python -m scripts.cftc_scraper.main --sheet=staging

# Or trigger from Railway dashboard
```

### Troubleshooting

**Scraping errors**:
- Check CFTC website HTML structure hasn't changed
- Verify Agriculture Long Format URL still valid: https://www.cftc.gov/dea/futures/ag_lf.htm
- Check regex patterns in scraper.py

**Sheets errors**:
- Verify service account permissions
- Check spreadsheet ID correct
- Ensure sheet name (TECHNICALS or TECHNICALS_STAGING) exists
- Confirm column A has dates and column I exists

## Future Enhancements (P2)

- Smart detection: Extract report date and skip if unchanged
- Alerting: Integrate with Sentry for error notifications
- Forward-fill: Update all empty cells instead of just last row
