# Compass Brief Generator

Replaces the manual Looker Studio PDF export step in the daily audio podcast workflow. Reads market data from Google Sheets and uploads a structured `.txt` brief to Google Drive, ready for NotebookLM consumption.

## What it does

1. Reads the **last 2 rows** from TECHNICALS, INDICATOR, BIBLIO_ALL, METEO_ALL (production sheets)
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
# Dry run -- generate brief, print to stdout, no upload
poetry run compass-brief --dry-run

# Generate and upload to Drive
poetry run compass-brief

# Save locally + upload
poetry run compass-brief --output /tmp/brief.txt

# Verbose logging
poetry run compass-brief --dry-run --verbose
```

## CLI flags

| Flag | Default | Description |
|------|---------|-------------|
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

## Railway cron deployment

| Field | Value |
|-------|-------|
| Service name | `compass-brief` |
| Image | Shared backend Dockerfile |
| Command | `bash /app/scripts/compass_brief/run_brief.sh` |
| Schedule | `15 23 * * 1-5` (11:15 PM UTC, weekdays) |
| Sentry monitor slug | `compass-brief` |

### Pipeline position

```
 9:00 PM UTC  -- Barchart scraper       -> TECHNICALS (CLOSE, HIGH, LOW, VOL, OI, IV)
 9:10 PM UTC  -- ICE stocks + CFTC      -> TECHNICALS (STOCK US, COM NET US)
 9:30 PM UTC  -- Press review agent     -> BIBLIO_ALL
10:30 PM UTC  -- 1DAY METEO (Make.com)  -> METEO_ALL
11:00 PM UTC  -- Daily analysis          -> INDICATOR + TECHNICALS (DECISION, SCORE)
11:15 PM UTC  -- Compass brief           -> Drive (.txt)
```

Runs 15 minutes after daily-analysis to ensure all data is available.

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
├── main.py              # CLI entry point + Sentry monitoring
├── config.py            # Column mappings, env var helpers, spreadsheet ID
├── sheets_reader.py     # Reads TECHNICALS, INDICATOR, BIBLIO_ALL, METEO_ALL
├── brief_generator.py   # Formats data into structured text
├── drive_uploader.py    # Uploads .txt to Shared Drive folder
├── run_brief.sh         # Railway cron entry point
└── README.md
```

## Data sources

| Sheet | Range | Data |
|-------|-------|------|
| TECHNICALS | A:AR (last 2 rows) | OHLCV, technicals, decision, score text |
| INDICATOR | A:T (last 2 rows) | Normalised scores, conclusion, ECO analysis |
| BIBLIO_ALL | A:C (filtered by date) | Press review summaries |
| METEO_ALL | A:E (filtered by date) | Weather conditions + market impact |
