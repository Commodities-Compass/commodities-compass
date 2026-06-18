# CFTC Scraper - US Disaggregated COT Weekly

Standalone scraper for CFTC Commitments of Traders data (cocoa ICE Futures U.S.). Refactored 2026-05-27 to write full COT decomposition to `pl_cot_us_weekly` instead of updating a single field on `pl_contract_data_daily`.

## Features

- **Full COT decomposition**: Extracts Producer/Merchant, Swap Dealers, Managed Money, Other Reportables, Non-Reportable positions (long/short) plus Open Interest
- **Idempotent UPSERT**: Keyed on `(release_date, contract_market)` — re-running Friday after a CFTC revision overwrites the row with latest numbers
- **Fail-loud design**: Exits 1 on any parser error, stale report, or validation failure (no silent degradation)
- **Dry-run mode**: Test without writing to database
- **Staleness check**: Raises error if CFTC report is older than 14 days (publisher down detection)

## Usage

### Local Development

```bash
# Test scrape (dry run)
poetry run cftc-scraper --dry-run

# Live run
poetry run cftc-scraper
```

### Environment Variables

Required:
- `DATABASE_SYNC_URL` - GCP Cloud SQL connection string

Optional:
- `LOG_LEVEL` - logging level (default: INFO)

## Deployment (GCP Cloud Run Jobs)

| Setting | Value |
|---------|-------|
| **Cloud Run Job** | `cc-cftc-scraper` |
| **Image** | `Dockerfile.jobs` |
| **Cloud Scheduler** | `5 19 * * 1-5` (7:05 PM UTC weekdays) |
| **Required env vars** | `DATABASE_SYNC_URL` |

Runs weekday evenings only, idempotent on release_date. Env vars configured in Cloud Run Job env vars or Secret Manager.

## How It Works

1. **Download CFTC report** from Agriculture Long Format page (`https://www.cftc.gov/dea/futures/ag_lf.htm`)
2. **Parse report date** from section header (e.g., "Disaggregated Commitments of Traders - Futures Only, May 19, 2026")
3. **Derive release_date** = report_date + 3 days (CFTC Tuesday→Friday convention)
4. **Extract cocoa section** — anchors on code 073732 (cocoa ICE Futures U.S.)
5. **Parse "All" row** — extracts 14 numeric fields (open interest, producer/merchant long/short, swap dealers long/short/spreading, managed money long/short/spreading, other reportables long/short/spreading, non-reportables long/short)
6. **Validate** — prod_merc_net (long - short) must be in range [-100k, +100k]
7. **UPSERT to pl_cot_us_weekly** — keyed on (release_date, contract_market="cocoa"), idempotent on CFTC publisher revisions

## Database Target

Writes one row per CFTC publication to `pl_cot_us_weekly`:

| Column | Source | Notes |
|--------|--------|-------|
| `release_date` | Derived from report_date + 3 days | Friday when CFTC publishes |
| `report_date` | Parsed from section header | Tuesday snapshot covered |
| `contract_market` | Hardcoded | "cocoa" (ICE Futures U.S.) |
| `prod_merc_long`, `prod_merc_short` | "All" row columns | Producer/Merchant positions |
| `m_money_long`, `m_money_short` | "All" row columns | Managed Money positions |
| `swap_long`, `swap_short`, `swap_spreading` | "All" row columns | Swap Dealers positions |
| `other_rept_long`, `other_rept_short`, `other_rept_spreading` | "All" row columns | Other Reportables |
| `non_rept_long`, `non_rept_short` | "All" row columns | Non-Reportable positions |
| `open_interest` | "All" row column 1 | Total open interest |
| `prod_merc_net` | GENERATED column | prod_merc_long - prod_merc_short (never written) |
| `m_money_net` | GENERATED column | m_money_long - m_money_short (never written) |

## Error Handling

Per `.claude/rules/pipeline-error-handling.md`, the scraper fails loud and never silently recovers:

- **Missing CFTC section** (code 073732 not found): Logs error, exit 1, Sentry alert
- **Malformed "All" row** (fewer/more tokens than expected): Logs error, exit 1, Sentry alert
- **Unparseable numbers**: Logs error, exit 1, Sentry alert
- **Stale report** (report_date > 14 days old): Logs error, exit 1, Sentry alert (publisher down)
- **Validation failure** (prod_merc_net outside [-100k, +100k]): Logs error, exit 1, Sentry alert
- **Unexpected exception**: Logs full traceback, exit 1, Sentry alert

## Testing

```bash
# Test scraper only (dry run)
poetry run cftc-scraper --dry-run

# View parsed observation
poetry run python -c "
from scripts.cftc_scraper.scraper import CFTCScraper
scraper = CFTCScraper()
obs = scraper.scrape()
print(f'Report: {obs.report_date}, Release: {obs.release_date}')
print(f'Prod/Merc Net: {obs.prod_merc_net:,}, M-Money Net: {obs.m_money_net:,}')
print(f'Open Interest: {obs.open_interest:,}')
"
```

## Monitoring

### Logs
- All logs go to stdout (Cloud Run captures automatically)
- Sentry cron monitor for missed/failed runs (`@monitor(monitor_slug="cftc-scraper")`)
- Detailed context logged on success (release_date, report_date, net positions, open interest)

### Success Criteria
- Exit code 0
- "SUCCESS: CFTC scraper completed" in logs
- `pl_cot_us_weekly` has one new or updated row for the latest CFTC release

## Maintenance

### Daily Schedule (Weekdays)
- **19:05 UTC (7:05 PM CET)**: Automated run via Cloud Scheduler → Cloud Run Job
- Idempotent — UPSERT on (release_date, contract_market) means re-running after a CFTC revision overwrites the row

### Manual Run
If automation fails, run manually:

```bash
# Via gcloud CLI
gcloud run jobs execute cc-cftc-scraper --region europe-west9

# Or run locally
poetry run cftc-scraper
```

### Troubleshooting

**Scraping errors**:
- Verify CFTC report is current: https://www.cftc.gov/dea/futures/ag_lf.htm (updated Friday ~9:30 PM CET)
- Check HTML structure hasn't changed (look for code 073732 and "Disaggregated Commitments of Traders" header)
- Verify regex patterns in scraper.py match actual CFTC format

**Validation errors** (prod_merc_net outside range):
- Confirm scraped numbers match the CFTC website manually
- Check that the "All" row parser picked the correct line (not a different commodity's "All" row)

**Stale report errors** (report > 14 days old):
- CFTC may have stopped publishing (unlikely; they publish every Friday)
- Scraper may be hitting a cache or archived page
- Verify URL is correct and returning current report

## References

- CFTC Disaggregated COT: https://www.cftc.gov/dea/futures/ag_lf.htm
- Producer/Merchant (commercial hedgers) + Managed Money (speculators) = key R&D signals for ensemble
- Report date is Tuesday snapshot; release_date (Friday) is when public CFTC data becomes available
- Mirrors `cc-ice-cot-eu-scraper` for pattern consistency (EU weekly COT → `pl_cot_eu_weekly`)
