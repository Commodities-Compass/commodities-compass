# CFTC Scraper - Simple Daily Scraper

Standalone scraper for CFTC Commitments of Traders data (COM NET US field).

## Features

- **Dual-write**: Writes to GCP Cloud SQL (`pl_contract_data_daily.com_net_us`) and Google Sheets
- **Non-blocking DB write**: If DB fails, Sheets write proceeds normally
- **Last row update**: Finds last row with date and updates column I (Sheets) / latest row for active contract (DB)
- **Dry-run mode**: Test without writing to DB or Sheets
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
- `DATABASE_SYNC_URL` - GCP Cloud SQL connection string

## Deployment (GCP Cloud Run Jobs)

| Setting | Value |
|---------|-------|
| **Cloud Run Job** | `cc-cftc-scraper` |
| **Image** | `Dockerfile.jobs` |
| **Cloud Scheduler** | `10 21 * * 1-5` (9:10 PM UTC weekdays) |
| **Required env vars** | `GOOGLE_SHEETS_SCRAPER_CREDENTIALS_JSON`, `DATABASE_SYNC_URL` |

Idempotent: Mon-Thu rewrites same value, Friday picks up new report. Env vars configured in Cloud Run Job env vars or Secret Manager.

## How It Works

1. **Download CFTC report** from Agriculture Long Format page
2. **Parse cocoa section** to extract Producer/Merchant Long/Short positions
3. **Calculate COM NET US** = Long - Short
4. **Validate range** (-100k to +100k)
5. **Write to GCP PostgreSQL** — update `com_net_us` on latest `pl_contract_data_daily` row for active contract (non-blocking)
6. **Find last row** with date in column A of TECHNICALS sheet
7. **Update column I** of that row with COM NET US value

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
- All logs go to stdout (Cloud Run captures automatically)
- Sentry cron monitoring for missed/failed runs

### Success Criteria
- Exit code 0
- "SUCCESS" in logs
- Google Sheets column I updated with new value

## Maintenance

### Daily Schedule (Weekdays)
- **21:10 UTC (10:10 PM CET)**: Automated run via Cloud Scheduler → Cloud Run Job
- Idempotent — always reads the latest published CFTC report (updated Fridays ~9:30 PM CET)

### Manual Run
If automation fails, run manually:

```bash
# Via gcloud CLI
gcloud run jobs execute cc-cftc-scraper --region europe-west9

# Or run locally
poetry run python -m scripts.cftc_scraper.main --sheet=staging
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

## GCP Database Write

Updates `com_net_us` on the most recent `pl_contract_data_daily` row for the active contract (queried via `ref_contract.is_active`). The row must already exist — Barchart scraper creates it at 9:00 PM UTC. If no row exists, logs an error and continues to Sheets.

Writer: `db_writer.py` — `write_com_net_us(session, commercial_net, dry_run=False)`

## Future Enhancements

- Smart detection: Extract report date and skip if unchanged
- Forward-fill: Update all empty cells instead of just last row
