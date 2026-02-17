# ICE Certified Cocoa Stocks Scraper (Report 41)

Automated daily scraper for ICE US Cocoa Certified Stocks data. Downloads public XLS files from ice.com, parses warehouse stock totals, converts to tonnes, and writes to Google Sheets column H (STOCK US).

## Discovery (2026-02-17)

### Initial Assumptions vs Reality

The [automation plan](../../../ice-stocks-automation-plan.md) assumed ice.com/report/41 was protected by Cloudflare WAF, requiring browser automation or proxy rotation. We ran a systematic recon to determine the actual protection.

**Findings:**
- **No Cloudflare WAF** on the report page — the plan was wrong
- Protection is **Google reCAPTCHA v2** on the React SPA (`ice.com/report/41`)
- The SPA calls an internal API (`/marketdata/api/reports/41/results`) which returns **download links** to XLS files
- Those XLS files are hosted at **public, predictable URLs** — no auth, no cookies, no reCAPTCHA

### Recon Timeline

1. **Playwright + stealth** — ran headless recon against `ice.com/report/41`. Discovered reCAPTCHA v2 (not Cloudflare). Captured internal API endpoints.
2. **Interactive reCAPTCHA** — attempted headful Playwright with manual checkbox click. Google detected automation, served endless image challenges (4 rounds, all failed within 120s).
3. **Cookie/session approach** — extracted session cookies via Chrome DevTools. Session TTL ~minutes, expired before API calls could complete. Not viable for automation.
4. **API response analysis** — POST to `/marketdata/api/reports/41/results` returned download links, not inline data. Links pointed to `/publicdocs/futures_us_reports/cocoa/cocoa_cert_stock_YYYYMMDD.xls`.
5. **Direct XLS download** — tested the public URL without any cookies or auth. **HTTP 200. No protection at all.**

### Conclusion

The entire reCAPTCHA + SPA + API chain is unnecessary. ICE publishes daily XLS files at a public, predictable URL pattern. The scraper is a simple httpx GET + xlrd parse. No browser, no authentication, no CAPTCHA solving, no proxy needed.

## Architecture

```
ice_stocks_scraper/
  config.py          # URLs, sheet IDs, column index, validation ranges
  scraper.py         # download_xls() + parse_xls() + scrape()
  sheets_manager.py  # Google Sheets column H writer
  main.py            # CLI entry point
  run_scraper.sh     # Railway cron job entry point
```

**Dependencies:** `httpx`, `xlrd`, `pandas`, `google-api-python-client` (all already in pyproject.toml)

**No browser dependencies.** No Playwright, no stealth, no proxy.

## Data Flow

```
ICE public XLS (ice.com/publicdocs/...)
  → httpx GET (no auth)
  → xlrd/pandas parse
  → Extract "GRAND TOTAL" warehouse bags
  → Convert: bags × 70 / 1000 = tonnes (truncated)
  → Write to Google Sheets TECHNICALS column H
```

### XLS URL Pattern

```
https://www.ice.com/publicdocs/futures_us_reports/cocoa/cocoa_cert_stock_YYYYMMDD.xls
```

Some dates have an `a` suffix variant (e.g., `cocoa_cert_stock_20260205a.xls`). The scraper tries both.

### XLS Structure (Report 41)

| Row | Content | Value (2026-02-16) |
|-----|---------|-------------------|
| Header | `Date: M/D/YYYY` | 2/16/2026 |
| "Port of Delaware River" | DR warehouse bags | 1,909,849 |
| "Port of New York" | NY warehouse bags | 90,816 |
| "Total Bags" | Certified stock total | 461,934 |
| "GRAND TOTAL" | All US warehouse bags | 2,000,665 |

**STOCK US = GRAND TOTAL bags × 70 / 1000 = 140,046 tonnes**

### Fallback Strategy

If today's XLS is not yet published (typically available after market close):
1. Try today's date
2. Try today's date with `a` suffix
3. Fall back to previous days (up to 5 attempts)
4. Weekend dates converted to previous Friday

## Usage

```bash
# Dry run (download + parse + validate, no Sheets write)
poetry run python -m scripts.ice_stocks_scraper.main --dry-run

# Write to staging sheet
poetry run python -m scripts.ice_stocks_scraper.main --sheet=staging

# Write to production sheet
poetry run python -m scripts.ice_stocks_scraper.main --sheet=production

# Specific date
poetry run python -m scripts.ice_stocks_scraper.main --date=2026-02-14

# Verbose logging (debug HTTP requests)
poetry run python -m scripts.ice_stocks_scraper.main --dry-run --verbose
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GOOGLE_SHEETS_SCRAPER_CREDENTIALS_JSON` | Yes | Service account JSON for Sheets API |

## Railway Deployment

### Service Configuration

| Setting | Value |
|---------|-------|
| **Root directory** | `backend` |
| **Start command** | `bash scripts/ice_stocks_scraper/run_scraper.sh` |
| **Cron schedule** | `0 23 * * 1-5` (11 PM UTC / 7 PM ET, weekdays only) |
| **Restart policy** | Never (cron job, not long-running) |

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GOOGLE_SHEETS_SCRAPER_CREDENTIALS_JSON` | Yes | Service account JSON with **write** access to the TECHNICALS spreadsheet |

No other env vars needed. No database, no Auth0, no AWS.

### Why This Schedule

ICE Report 41 is published after US market close (~5-6 PM ET). Running at 7 PM ET / 11 PM UTC gives margin for late publications. The scraper auto-falls back to the previous business day if today's file isn't available yet.

### No Special Dependencies

No browser, no Playwright, no system packages. Uses `httpx` for HTTP + `xlrd` for XLS parsing — both are pure Python, already in `pyproject.toml`.

## Validation

- Grand total must be between 1,000 and 10,000,000 bags
- If the value falls outside this range, the scraper errors out (no write)
- If grand total cannot be extracted from XLS, the scraper errors out
