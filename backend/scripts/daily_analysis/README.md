# Daily Analysis Pipeline

Replaces the `COMPASS - DAILY BOT AI` Make.com scenario (18 modules, 42 variables, 2 OpenAI calls) with version-controlled Python code. Reads market data from Google Sheets, runs two LLM calls, writes trading decisions back to Google Sheets.

Spec: [`US-005-replace-daily-bot-ai-make-scenario.md`](../../../US-005-replace-daily-bot-ai-make-scenario.md)

## Pipeline Flow

```
main.py
  |
  +-- [1] Read data from Google Sheets (production tabs only)
  |     +-- TECHNICALS: last 2 rows -> 21 TOD/YES variable pairs (42 total)
  |     +-- BIBLIO_ALL: filter by target date -> MACRONEWS
  |     +-- METEO_ALL: historical -> METEONEWS, target date -> METEOTODAY
  |
  +-- [2] LLM Call #1 -- Macro/Weather Analysis
  |     Input: MACRONEWS + METEOTODAY + METEONEWS
  |     Output: MACROECO_BONUS (-0.10 to +0.10), ECO (30-word synthesis)
  |     Model: gpt-4-turbo | Temperature: 1.0 | Role: assistant
  |
  +-- [3] Write to INDICATOR sheet + HISTORIQUE row-shift
  |     +-- Freeze older HISTORIQUE row (inline formulas)
  |     +-- Demote newer row (R102 -> R101)
  |     +-- Write MACROECO_BONUS (col P) + ECO (col T) to new row
  |     +-- Write HISTORIQUE R102 refs to new row (col Q + R)
  |     +-- Wait + read back FINAL INDICATOR (Q) + CONCLUSION (R)
  |
  +-- [4] LLM Call #2 -- Trading Decision
  |     Input: 42 TOD/YES variables + FINAL_INDICATOR + FINAL_CONCLUSION
  |     Output: DECISION, CONFIANCE (1-5), DIRECTION, CONCLUSION
  |     Model: gpt-4-turbo | Temperature: 0.7 | Role: assistant
  |
  +-- [5] Write to TECHNICALS sheet
        Update row: AO=DECISION, AP=CONFIANCE, AQ=DIRECTION, AR=CONCLUSION
```

## Module Structure

```
scripts/daily_analysis/
+-- __init__.py
+-- main.py              # CLI entry point, 3 modes: inspect / indicator-only / full pipeline
+-- config.py            # Sheet names, formula templates, variable mappings, credentials
+-- sheets_reader.py     # Read TECHNICALS, BIBLIO_ALL, METEO_ALL (production only)
+-- indicator_writer.py  # INDICATOR sheet writes + HISTORIQUE row-shift + read-back
+-- llm_client.py        # OpenAI API client with retry logic
+-- prompts.py           # Prompt templates (extracted verbatim from Make.com blueprint JSON)
+-- output_parser.py     # Pydantic models for structured JSON LLM output parsing
+-- analysis_engine.py   # Pipeline orchestrator
```

## CLI Usage

```bash
# Full pipeline (dry run -- logs everything, writes nothing)
poetry run daily-analysis --sheet staging --dry-run

# Full pipeline (live against staging)
poetry run daily-analysis --sheet staging

# Full pipeline (production)
poetry run daily-analysis --sheet production

# Backfill a past date
poetry run daily-analysis --sheet staging --date 2026-02-12 --force

# Inspect INDICATOR sheet state (no writes, no LLM calls)
poetry run daily-analysis --sheet staging --inspect

# Indicator-only mode (test formula management without LLM)
poetry run daily-analysis --sheet staging --indicator-only --macroeco-bonus 0.04 --eco "Test"

# Override LLM provider/model
poetry run daily-analysis --sheet staging --llm-provider openai --llm-model gpt-4-turbo

# Verbose logging
poetry run daily-analysis --sheet staging --verbose
```

### CLI Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--sheet` | `staging` | Target sheet mode for writes (`staging` or `production`). Reads always from production. |
| `--date` | today | Target date `YYYY-MM-DD`. Enables backfill for past dates. |
| `--dry-run` | off | Log all steps but write nothing to Sheets. |
| `--force` | off | Overwrite existing data (bypass idempotency checks). |
| `--verbose` | off | Set logging to DEBUG level. |
| `--inspect` | off | Print INDICATOR sheet state and exit. No writes, no LLM calls. |
| `--indicator-only` | off | Run only the INDICATOR formula shift (no LLM calls). |
| `--macroeco-bonus` | `0.02` | MACROECO BONUS value (used with `--indicator-only`). |
| `--eco` | test string | ECO text (used with `--indicator-only`). |
| `--llm-provider` | `openai` | LLM provider. |
| `--llm-model` | `gpt-4-turbo` | LLM model override. |

## INDICATOR Sheet Formula Management (D6)

The INDICATOR sheet uses a **2-slot circular buffer** pattern with the HISTORIQUE sheet. Two "live" rows always point to HISTORIQUE rows R101 and R102. Each daily cycle:

```
BEFORE (row 349 is the last data row):
  Row 348: Q = =HISTORIQUE!R101    R = =HISTORIQUE!T101   (older)
  Row 349: Q = =HISTORIQUE!R102    R = =HISTORIQUE!T102   (newer)

AFTER (adding row 350):
  Row 348: Q = =IF(N348="","",...) R = =IF(Q348="",...)   (frozen, inline formulas)
  Row 349: Q = =HISTORIQUE!R101    R = =HISTORIQUE!T101   (demoted: was R102)
  Row 350: Q = =HISTORIQUE!R102    R = =HISTORIQUE!T102   (new row)
```

### Formula Templates

**Freeze formulas** (applied when a row stops being "live"):
- Column Q: `=IF(N{row}="", "", N{row} + (O{row}*0.5))`
- Column R: `=IF(Q{row}="", "", IF(Q{row} > 2, "OPEN", IF(Q{row} < -2, "HEDGE", "MONITOR")))`

**HISTORIQUE reference formulas** (live rows):
- Column Q: `=HISTORIQUE!R{ref}` (where ref is 101 or 102)
- Column R: `=HISTORIQUE!T{ref}`

### State Detection

`IndicatorWriter.get_state()` scans the last 10 rows of column Q for HISTORIQUE references, identifies the 2 live rows, sorts by ref number (lower=older, higher=newer), and determines the next operation.

### Read-Back

After writing, the pipeline waits for Google Sheets recalculation then reads back:
- **Column Q** = FINAL INDICATOR (float, computed by HISTORIQUE formulas)
- **Column R** = CONCLUSION (`OPEN`, `MONITOR`, or `HEDGE`)

Retries up to 3 times with exponential backoff (2s, 4s, 8s). Aborts with `IndicatorWriterError` if stale/empty after retries.

## Idempotency

Both write targets are protected:

**INDICATOR sheet**: Before writing, checks if column P (MACROECO BONUS) is already filled for the target date. If yes, raises `IndicatorWriterError` unless `--force`.

**TECHNICALS sheet**: Before writing, checks if column AO (DECISION) is already filled for the target row. If yes, raises `RuntimeError` unless `--force`.

## Data Sources (Read-Only, Production)

### TECHNICALS (last 2 rows)
21 variable pairs extracted from columns A-AM. Each variable produces a TOD (today) and YES (yesterday) suffix:

| Column | Variable | Description |
|--------|----------|-------------|
| B | CLOSE | Closing price |
| C | HIGH | Daily high |
| D | LOW | Daily low |
| E | VOL | Volume |
| F | OI | Open Interest |
| G | VOLIMP | Implied Volatility |
| H | STOCK | Stock US (ICE certified stocks) |
| I | COMNET | COM NET US (CFTC commercial net position) |
| L | R1 | Resistance 1 |
| M | PIVOT | Pivot point |
| N | S1 | Support 1 |
| Q | EMA9 | EMA 9-day |
| R | EMA21 | EMA 21-day |
| S | MACD | MACD |
| T | SIGN | Signal line |
| U | RSI14 | RSI 14-day |
| AE | %K | Stochastic %K |
| AF | %D | Stochastic %D |
| AJ | ATR | Average True Range |
| AL | BSUP | Bollinger upper band |
| AM | BBINF | Bollinger lower band |

### BIBLIO_ALL
Filtered by target date (column A). Column C (RESUME) aggregated into MACRONEWS.

### METEO_ALL
- **METEONEWS**: Last 100 rows, formatted as `MM/YYYY-{RESUME}` (historical context)
- **METEOTODAY**: Single row matching target date, column C (RESUME)

## LLM Output Parsing

Replaces Make.com's fragile regex parsers with Pydantic models and JSON parsing.

**Call #1 output** (`MacroAnalysisOutput`):
```json
{"date": "19/12/2024", "macroeco_bonus": -0.06, "eco": "...30-word synthesis..."}
```

**Call #2 output** (`TradingDecisionOutput`):
```json
{"decision": "OPEN", "confiance": 3, "direction": "HAUSSIERE", "conclusion": "...full text..."}
```

The parser handles markdown fences, surrounding text, and unescaped newlines in JSON string values.

## Observability

- **Sentry cron monitoring**: `@monitor(monitor_slug="daily-analysis")`
- **Sentry context**: target date, LLM model, token counts per call, sheet row numbers, all output values
- **Structured logging**: data read counts, LLM token usage, write confirmations, timing
- **`--dry-run`**: logs everything, writes nothing

## Environment Variables

```bash
# Required
OPENAI_API_KEY=sk-...                            # OpenAI API key
GOOGLE_SHEETS_SCRAPER_CREDENTIALS_JSON=...       # Service account JSON (read+write scope)
SENTRY_DSN=...                                   # Sentry monitoring

# Optional
LLM_PROVIDER=openai                              # LLM provider (only openai supported currently)
LLM_MODEL=gpt-4-turbo                            # Model override
```

## Railway Deployment

```
Service:  Railway cron "daily-analysis" (shared Dockerfile)
Schedule: 00 23 * * 1-5  (11:00 PM UTC, weekdays)
Command:  poetry run daily-analysis --sheet production
Monitor:  Sentry cron slug "daily-analysis"
```

### Pipeline Timing

```
 9:00 PM UTC  -- Barchart scraper       -> TECHNICALS (CLOSE, HIGH, LOW, VOL, OI, IV)
 9:10 PM UTC  -- ICE stocks scraper     -> TECHNICALS (STOCK US)
 9:10 PM UTC  -- CFTC scraper           -> TECHNICALS (COM NET US)
 9:30 PM UTC  -- Press review agent     -> BIBLIO_ALL
10:30 PM UTC  -- 1DAY METEO (Make.com)  -> METEO_ALL
11:00 PM UTC  -- daily-analysis (this)  -> INDICATOR + TECHNICALS
```

## Not Yet Implemented

- **Email sender** (`email_sender.py`): Daily analysis email via Gmail API. Pipeline runs without email for now.
- **Contract utils** (`contract_utils.py`): NOMCONTRAT calculation (month -> contract code). Needed for email subject line only.
