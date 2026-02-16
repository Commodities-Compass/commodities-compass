# CFTC Scraper - Independent Weekly Scraper

Standalone scraper for CFTC Commitments of Traders data (COM NET US field).

## Features

- **Smart report detection**: Extracts report date, only updates if new
- **Forward-fill logic**: Fills all empty rows with latest value
- **Alert system**: Slack/Email notifications for success/failure
- **Metadata tracking**: Stores last report date to avoid duplicate updates
- **Dry-run mode**: Test without writing to sheets

## Usage

### Local Development

```bash
# Test scrape (dry run)
poetry run python -m scripts.cftc_scraper.main --dry-run --sheet=staging

# Live run (staging)
poetry run python -m scripts.cftc_scraper.main --sheet=staging

# Live run (production)
poetry run python -m scripts.cftc_scraper.main --sheet=production

# Force update even if report date unchanged
poetry run python -m scripts.cftc_scraper.main --sheet=production --force
```

### Environment Variables

Required:
- `GOOGLE_SHEETS_SCRAPER_CREDENTIALS_JSON` - Google Sheets service account credentials

Optional (for alerts):
- `SLACK_WEBHOOK_URL` - Slack webhook for notifications
- `SENDGRID_API_KEY` - SendGrid API key for email alerts
- `ALERT_EMAIL_FROM` - From email address
- `ALERT_EMAIL_TO` - Comma-separated recipient emails

## Deployment (Railway)

### Setup

1. **Create new Railway service**: "cftc-scraper"

2. **Configure environment variables** (Railway dashboard):
   ```
   GOOGLE_SHEETS_SCRAPER_CREDENTIALS_JSON=<json-credentials>
   SLACK_WEBHOOK_URL=<slack-webhook>  # Optional
   ```

3. **Set cron schedule** (Railway settings):
   - **Cron expression**: `0 4 * * 6` (Every Saturday at 4 AM UTC = 5 AM CET)
   - **Command**: `poetry run python -m scripts.cftc_scraper.main --sheet=production`

### Why Saturday?

- CFTC publishes Fridays at 3:30 PM ET (9:30 PM CET)
- Running Saturday morning ensures report is available
- Handles federal holiday delays automatically (report still scraped when available)

## How It Works

1. **Download CFTC report** from Agriculture Long Format page
2. **Extract report date** (e.g., "February 10, 2026")
3. **Compare with last report date** stored in Google Sheets metadata (cell K1)
4. **If new report**:
   - Parse Producer/Merchant Long/Short positions
   - Calculate COM NET US = Long - Short
   - Forward-fill: Update all empty column I cells
   - Save new report date to metadata
   - Send success alert
5. **If same report**:
   - Log info message
   - Send info alert
   - No sheet updates (data already current)
6. **If scraping error**:
   - Log error
   - Send critical alert
   - Sheets retain last known value (forward-fill continues)

## Sheet Structure

### Data Column
- **Column I** (index 8): COM NET US values

### Metadata Cell
- **Cell K1**: Last CFTC report date (format: YYYY-MM-DD)

## Alert Levels

- **INFO**: No new report published (same date as last)
- **SUCCESS**: Successfully updated sheets with new data
- **WARNING**: (Reserved for future use)
- **CRITICAL**: Scraping failed or sheets update failed

## Error Handling

- **No new report**: Info alert, no updates, exit 0
- **Scraping error**: Critical alert, no updates, exit 1
- **Sheets error**: Critical alert, exit 1 (scraped data logged)
- **Unexpected error**: Critical alert, exit 1

## Testing

```bash
# Test scraper only (no sheets)
poetry run python -c "
from scripts.cftc_scraper.scraper import CFTCScraper
scraper = CFTCScraper()
result = scraper.scrape_with_date()
print(result)
"

# Test full flow (dry run)
poetry run python -m scripts.cftc_scraper.main --dry-run --sheet=staging
```

## Monitoring

### Logs
- Local: `cftc_scraper.log`
- Railway: Cloud Logs in Railway dashboard

### Alerts
- Slack notifications (if configured)
- Email alerts (if configured)

### Success Criteria
- Exit code 0
- "SUCCESS" in logs
- Slack success alert received
- Google Sheets updated with new value

## Maintenance

### Weekly Schedule
- **Saturday 4 AM UTC**: Automated run via Railway cron

### Manual Run
If automation fails, run manually:

```bash
# Via Railway CLI
railway run poetry run python -m scripts.cftc_scraper.main --sheet=production

# Or trigger from Railway dashboard
```

### Troubleshooting

**"No new report" every week**:
- Check if CFTC website is down
- Verify report date extraction regex
- Check metadata cell K1 value

**Scraping errors**:
- Check CFTC website HTML structure hasn't changed
- Verify Agriculture Long Format URL still valid
- Check regex patterns in scraper.py

**Sheets errors**:
- Verify service account permissions
- Check spreadsheet ID correct
- Ensure sheet name (TECHNICALS) exists
