# Compass Brief Generator

Generates a structured `.txt` brief from market data and uploads to Google Drive for NotebookLM podcast consumption. Supports two data sources:

- **`--db` mode** (new, Phase 3.4): Reads from `pl_*` tables. No Sheets dependency.
- **Default mode** (legacy): Reads from Google Sheets.

## What it does

1. Reads the **last 2 days** of market data (technicals, indicators, press review, weather)
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
# DB mode (recommended)
poetry run compass-brief --db --dry-run        # preview from DB
poetry run compass-brief --db                  # generate + upload from DB

# Legacy Sheets mode
poetry run compass-brief --dry-run             # preview from Sheets
poetry run compass-brief                       # generate + upload from Sheets

# Save locally
poetry run compass-brief --db --output /tmp/brief.txt
```

## CLI flags

| Flag | Default | Description |
|------|---------|-------------|
| `--db` | off | Read from `pl_*` tables instead of Google Sheets |
| `--dry-run` | off | Print brief to stdout, skip Drive upload |
| `--output` | none | Save brief to local file path |
| `--verbose` | off | DEBUG logging |

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GOOGLE_SHEETS_SCRAPER_CREDENTIALS_JSON` | yes | Service account JSON (read+write). Used for both Sheets reads and Drive uploads |
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
| **Cloud Scheduler** | `30 21 * * 1-5` (9:30 PM UTC, weekdays) |
| **Sentry monitor slug** | `compass-brief` |

### Pipeline position

```
 9:00 PM UTC  -- Barchart scraper       -> TECHNICALS (CLOSE, HIGH, LOW, VOL, OI, IV)
 9:10 PM UTC  -- ICE stocks + CFTC      -> TECHNICALS (STOCK US, COM NET US)
 9:10 PM UTC  -- Press review agent     -> BIBLIO_ALL
 9:10 PM UTC  -- Meteo agent            -> METEO_ALL
 9:20 PM UTC  -- Daily analysis          -> INDICATOR + TECHNICALS (DECISION, SCORE)
 9:30 PM UTC  -- Compass brief          -> Drive (.txt)  ← this (reads all 4 sheets)
```



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
├── main.py              # CLI entry point: --db (new) or legacy Sheets
├── config.py            # Column mappings, env var helpers, spreadsheet ID
├── db_reader.py         # [NEW] Read from pl_* tables
├── sheets_reader.py     # [LEGACY] Read from Google Sheets
├── brief_generator.py   # Formats data into structured text (shared)
├── drive_uploader.py    # Uploads .txt to Shared Drive folder (shared)
├── run_brief.sh         # Railway cron entry point
└── README.md
```

## Data sources

### DB mode (`--db`)

| Table | Data |
|-------|------|
| `pl_contract_data_daily` + `pl_derived_indicators` | OHLCV, technicals (last 2 days) |
| `pl_indicator_daily` | Scores, norms, decision, ECO (last 2 days) |
| `pl_fundamental_article` (fallback: `market_research`) | Press review summaries |
| `pl_weather_observation` (fallback: `weather_data`) | Weather + market impact |

### Legacy Sheets mode

| Sheet | Range | Data |
|-------|-------|------|
| TECHNICALS | A:AR (last 2 rows) | OHLCV, technicals, decision, score text |
| INDICATOR | A:T (last 2 rows) | Normalised scores, conclusion, ECO analysis |
| BIBLIO_ALL | A:C (filtered by date) | Press review summaries |
| METEO_ALL | A:E (filtered by date) | Weather conditions + market impact |
