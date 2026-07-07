# Compass Brief Generator

Generates a structured `.txt` brief from PostgreSQL market data and uploads to Google Drive for NotebookLM podcast consumption.

## What it does

1. Reads the **last 2 days** of market data from `pl_*` tables (technicals, indicators, press review, weather)
2. Generates a single `.txt` file with two dated sections: **VEILLE** (yesterday) and **AUJOURD'HUI** (today)
3. Uploads to a **Shared Drive** folder ("Compass Briefs")
4. Idempotent: re-running for the same date updates the existing file

## Content structure

The brief mirrors the Looker PDF content:

- **Signal du jour** (OPEN/MONITOR/HEDGE) from INDICATOR.CONCLUSION
- **Decision / Confiance / Direction** from TECHNICALS (cols AO-AR)
- **Donnees techniques** (CLOSE, HIGH, LOW, VOL, OI, IV, RSI, MACD, %K, %D, ATR, PIVOT, S1, R1, EMA9, EMA21, Bollinger, STOCK US, COM NET US)
- **Scores indicateurs** (normalised scores from INDICATOR sheet)
- **Analyse macroeconomique** (ECO text from INDICATOR col T)
- **Recommandations du jour** (SCORE text from TECHNICALS col AR)
- **Press review** (BIBLIO_ALL RESUME col C)
- **Meteo** (METEO_ALL RESUME col C + IMPACT col E)

## Usage

```bash
# Generate and upload to Drive
poetry run compass-brief

# Preview to stdout (no upload)
poetry run compass-brief --dry-run

# Save locally
poetry run compass-brief --output /tmp/brief.txt

# Run for a specific trading session date (Phase B backfill/rerun)
poetry run compass-brief --session-date 2026-06-13

# Override the trading-day gate (e.g., for backfills on non-trading days)
poetry run compass-brief --force

# Verbose logging
poetry run compass-brief --verbose
```

## CLI flags

| Flag | Default | Description |
|------|---------|-------------|
| `--dry-run` | off | Print brief to stdout, skip Drive upload |
| `--output` | none | Save brief to local file path |
| `--verbose` | off | DEBUG logging |
| `--force` | off | Run even on non-trading days (for backfills/debugging) |
| `--session-date` | auto | Session date to (re)generate — the row date the brief covers and its filename stem (YYYY-MM-DD). Defaults (cron) to the last completed trading session via `resolve_phase_b_dates()` |

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GOOGLE_SHEETS_SCRAPER_CREDENTIALS_JSON` | yes | Service account JSON (read+write). Used for Drive uploads |
| `GOOGLE_DRIVE_BRIEFS_FOLDER_ID` | yes | Folder ID of "Compass Briefs" in Shared Drive |
| `SENTRY_DSN` | no | Sentry monitoring DSN |

## Google Drive setup

The service account cannot create files in regular (My Drive) folders due to Google storage quota restrictions on SAs. The workaround is a **Shared Drive**:

1. Create a Shared Drive (e.g. "Commodities Compass")
2. Create a "Compass Briefs" folder inside it
3. Add `commodities-compass-data@cacaooo.iam.gserviceaccount.com` as a **Content Manager** on the Shared Drive
4. Copy the folder ID from the URL and set `GOOGLE_DRIVE_BRIEFS_FOLDER_ID` in `.env`

## Deployment (GCP Cloud Run Jobs)

| Field | Value |
|-------|-------|
| **Cloud Run Job** | `cc-compass-brief` |
| **Image** | `Dockerfile.jobs` |
| **Cloud Scheduler** | `30 19 * * 1-5` (7:30 PM UTC, weekdays) |
| **Sentry monitor slug** | `compass-brief` |

### Pipeline position

```
 7:00 PM UTC  -- Barchart scraper       -> pl_contract_data_daily (OHLCV + IV)
 7:05 PM UTC  -- ICE stocks + CFTC      -> pl_contract_data_daily (STOCK US, COM NET US)
 7:05 PM UTC  -- Press review agent     -> pl_fundamental_article
 7:10 PM UTC  -- Meteo agent            -> pl_weather_observation
 7:15 PM UTC  -- Compute indicators     -> pl_derived_indicators + pl_indicator_daily
 7:20 PM UTC  -- Daily analysis         -> pl_indicator_daily (LLM decision + score)
 7:30 PM UTC  -- Compass brief          -> Google Drive (.txt)  ← this (reads all pl_* tables)
```

## Phase B gate (P2b)

The compass-brief job runs daily but gates on `is_eve_of_trading_day()`:

- **Weekdays (Mon-Thu)**: the job fires at 19:30 UTC and generates a brief for the next trading day
- **Friday evening**: generates a brief for Monday
- **Saturday/Sunday**: exits cleanly (exit 0) — no false alert to Sentry cron monitor
- **Holidays**: exits cleanly

Use `--force` to bypass this gate for backfills or manual reruns on non-trading days.

## Manual workflow (current)

After the brief is uploaded:

1. Open NotebookLM
2. Add the `.txt` file from the Shared Drive as a source
3. Paste the podcast prompt, generate audio
4. Download the m4a, rename to `YYYYMMDD-CompassAudio.m4a`, upload to the audio Drive folder

Steps 1-3 remain manual until the audio agent (US-008) is implemented.

## Module structure

```
backend/scripts/compass_brief/
├── __init__.py
├── main.py              # CLI entry point with Phase B gate logic
├── config.py            # Column mappings, env var helpers
├── db_reader.py         # Read from pl_* tables (contract-centric, roll-robust)
├── brief_generator.py   # Formats BriefData into structured text
├── drive_uploader.py    # Uploads .txt to Shared Drive folder
└── README.md
```

## Data sources

| Table | Data | Notes |
|-------|------|-------|
| `pl_contract_data_daily` + `pl_derived_indicators` | OHLCV, technicals (last 2 days) | Latest 2 sessions via `v_contract_data_chained` (roll-robust) |
| `pl_indicator_daily` | Scores, norms, decision, ECO (last 2 days) | Joins `pl_algorithm_version` for active rows only |
| `pl_fundamental_article` (fallback: `market_research`) | Press review summaries | Filtered by `is_active=true` |
| `pl_weather_observation` (fallback: `weather_data`) | Weather + market impact | Latest summary + impact_assessment |
| `pl_stock_observation` | ICE US certified stocks (tonnes) | Weekly cadence, `latest-on-or-before-date` pattern |
| `pl_cot_us_weekly` | CFTC commercial net positioning | Weekly cadence, `latest-on-or-before-date` pattern |
| `v_contract_data_chained` | Front-month chain by OI (roll-robust) | Ensures brief spans contract roll boundaries cleanly |

## Contract roll handling

The brief reader uses `v_contract_data_chained` to resolve the front-month contract for each date, rather than filtering by `ref_contract.is_active`. This makes the brief resilient across contract rolls:

- **Old contracts** (rolled out but still in data): correctly resolved from the chained view
- **New contracts** (just activated): included as soon as they appear in the chain

See [contract roll procedure](../../docs/runbooks/contract-roll-procedure.md) for full details.

## Fail-loud behavior

- Missing credentials → raises `RuntimeError` with clear env var name
- No recent market data (< 2 days) → raises `ValueError`
- Stale data detected (brief data < previous session) → logs warning, skips upload, exits 0 (non-fatal, caller can retry with `--force`)
- Drive upload fails → logs exception, exits 1 (Sentry alert)
