# Meteo Agent

Replaces the Make.com "COMPASS - 1DAY METEO" automation. Fetches weather data from Open-Meteo API for 6 cocoa-growing locations, calls OpenAI for French-language analysis, and writes the result to METEO_ALL in Google Sheets.

## What it does

1. **Fetches** daily + hourly weather data from Open-Meteo API (6 locations, no API key needed)
2. **Calls** OpenAI GPT-4.1 to generate a structured French weather analysis for cocoa traders
3. **Validates** output field lengths (texte, resume, mots_cle, impact_synthetiques)
4. **Writes** a single row to METEO_ALL sheet (columns A-E)

## Locations

| Location | Country | Lat | Lon |
|----------|---------|-----|-----|
| Daloa | Côte d'Ivoire | 6.877 | -6.45 |
| San-Pédro | Côte d'Ivoire | 4.748 | -6.636 |
| Soubré | Côte d'Ivoire | 5.785 | -6.606 |
| Kumasi | Ghana | 6.688 | -1.624 |
| Takoradi | Ghana | 4.885 | -1.745 |
| Goaso | Ghana | 6.8 | -2.52 |

## Weather Parameters

- **Daily**: precipitation_sum, et0_fao_evapotranspiration, sunshine_duration, temperature_2m_max, temperature_2m_min
- **Hourly**: soil_moisture_9_to_27cm, soil_moisture_3_to_9cm, vapour_pressure_deficit, relative_humidity_2m, rain
- **Window**: past_days=1, forecast_days=1

## Output (METEO_ALL sheet)

| Column | Header | Content |
|--------|--------|---------|
| A | DATE | `MM/DD/YYYY` |
| B | TEXTE | Full weather analysis (~2000 chars) |
| C | RESUME | 2-3 sentence summary with key finding + most affected zone |
| D | MOTS-CLE | Comma-separated keywords (geographic zone, stress type, phenological stage) |
| E | IMPACT SYNTHETIQUES | `X/10; justification sentence` |

## Usage

```bash
# Dry run — fetch weather + call LLM, print output, no Sheets write
poetry run meteo-agent --dry-run --verbose

# Write to production METEO_ALL
poetry run meteo-agent --sheet production

# Verbose logging
poetry run meteo-agent --sheet production --verbose
```

## CLI flags

| Flag | Default | Description |
|------|---------|-------------|
| `--sheet` | staging | Target sheet mode (writes to METEO_ALL in both modes) |
| `--dry-run` | off | Run pipeline but skip Sheets write |
| `--verbose` | off | DEBUG logging |

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | yes | OpenAI API key for GPT-4.1 |
| `GOOGLE_SHEETS_SCRAPER_CREDENTIALS_JSON` | yes | Service account JSON (read+write) |
| `SENTRY_DSN` | no | Sentry monitoring DSN |

## Pipeline Schedule (Railway Cron)

```
 9:00 PM UTC  -- Barchart scraper       -> TECHNICALS (CLOSE, HIGH, LOW, VOL, OI, IV)
 9:10 PM UTC  -- ICE stocks + CFTC      -> TECHNICALS (STOCK US, COM NET US)
 9:10 PM UTC  -- Press review agent     -> BIBLIO_ALL
 9:10 PM UTC  -- Meteo agent            -> METEO_ALL  ← this
 9:20 PM UTC  -- Daily analysis          -> INDICATOR + TECHNICALS (DECISION, SCORE)
 9:30 PM UTC  -- Compass brief          -> Drive (.txt)
```

Cron: `10 21 * * 1-5` (9:10 PM UTC weekdays). No upstream dependencies except Open-Meteo API availability.

## Railway deployment

| Field | Value |
|-------|-------|
| Service name | `meteo-agent` |
| Image | Shared backend Dockerfile |
| Command | `bash /app/scripts/meteo_agent/run_meteo.sh` |
| Schedule | `10 21 * * 1-5` (9:10 PM UTC, weekdays) |
| Sentry monitor slug | `meteo-agent` |

## Module structure

```
backend/scripts/meteo_agent/
├── __init__.py
├── main.py              # CLI entry point + Sentry monitoring
├── config.py            # Locations, API params, prompts, validation, sheet config
├── weather_fetcher.py   # httpx call to Open-Meteo API
├── llm_client.py        # OpenAI GPT-4.1 call + JSON extraction
├── validator.py         # Output field length validation
├── sheets_writer.py     # Write to METEO_ALL (explicit row detection + update)
└── run_meteo.sh         # Railway cron entry point
```

## Downstream consumers

| Consumer | Columns read | Purpose |
|----------|-------------|---------|
| Daily analysis | A (DATE), C (RESUME) | METEOTODAY + METEONEWS context for LLM |
| Compass brief | A (DATE), C (RESUME), E (IMPACT) | Daily brief narrative |
| Data import ETL | A-E (all) | PostgreSQL `weather_data` table |

## Cost estimate

| Component | Monthly Cost |
|-----------|-------------|
| Open-Meteo API | Free (no key needed) |
| OpenAI GPT-4.1 (~15K in / ~800 out tokens/day) | ~$2-3/month |
