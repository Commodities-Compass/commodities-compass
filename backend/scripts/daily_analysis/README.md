# Daily Analysis Pipeline

Core AI analysis engine: reads market data from PostgreSQL, runs two LLM calls (macro/weather analysis + trading decision), writes trading signals. DB-first only (Google Sheets dependency eliminated).

```
[1] Read from DB
    +-- pl_contract_data_daily + pl_derived_indicators → 21 TOD/YES variable pairs
    +-- pl_fundamental_article → MACRONEWS
    +-- pl_weather_observation → METEOTODAY + METEONEWS
    +-- pl_orchestrator_decision (if ensemble exists) → 25 ensemble diagnostics fields

[2] LLM Call #1 — Macro/Weather Analysis → MACROECO_BONUS + ECO

[3] Compute FINAL_INDICATOR using app.engine.composite
    +-- Read z-scores + momentum from pl_derived_indicators
    +-- Apply power formula with fresh macroeco
    +-- Determine CONCLUSION (OPEN/MONITOR/HEDGE)

[4] LLM Call #2 — Trading Decision → DECISION / CONFIANCE / DIRECTION / CONCLUSION
    (Auto-aligns on ensemble row if present; otherwise legacy path)

[5] Write to DB (LLM-owned columns ONLY)
    +-- Update pl_indicator_daily (macroeco, final_indicator, decision, confidence, direction, conclusion)
    +-- Update pl_signal_component macroeco row
    +-- Insert 2 rows to aud_llm_call (audit trail)
```

## Quick Start

```bash
# Dry run (logs everything, writes nothing)
poetry run daily-analysis --dry-run

# Cron run — resolves to the last completed session (P2b semantics)
poetry run daily-analysis

# Specific session date (backfill) — the row date to regenerate
poetry run daily-analysis --session-date 2026-03-20

# Specific contract override
poetry run daily-analysis --contract CAK26

# Pin to legacy algorithm (for A/B testing or ensemble co-existence)
poetry run daily-analysis --algorithm-version legacy

# Verbose logging
poetry run daily-analysis --verbose

# Force overwrite existing data
poetry run daily-analysis --force
```

## CLI Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--contract` | active from DB | Contract code (e.g., `CAH26`). If omitted, resolves from `ref_contract.is_active`. |
| `--session-date` | last completed session | Session date to regenerate `YYYY-MM-DD` = the row date the analysis updates (= `data_date`). Defaults (cron) to the last completed trading session. Explicit `--session-date` bypasses the eve-of-trading-day gate (backfills). |
| `--dry-run` | off | Log all steps but write nothing to database. |
| `--force` | off | Overwrite existing data (bypass idempotency checks). |
| `--verbose` | off | Set logging to DEBUG level. |
| `--llm-provider` | `openai` | LLM provider (currently only `openai` supported). |
| `--llm-model` | model default | LLM model override (e.g., `gpt-4-turbo`). |
| `--algorithm-version` | `is_active=TRUE` | Pin to a specific algorithm name (e.g., `legacy`). If omitted, resolves to the active version. Required for C5 launch to prevent overwriting ensemble rows. |

## Module Structure

```
scripts/daily_analysis/
+-- __init__.py
+-- main.py                  # CLI entry point, P2b gate, arg parsing
+-- db_reader.py             # Read technicals + context from pl_* tables
+-- db_analysis_engine.py    # Orchestrates DB-first pipeline, ensemble auto-align
+-- llm_client.py            # OpenAI API client with retry
+-- prompts.py               # Prompt templates (Macro Call #1 + Trading Call #2)
+-- output_parser.py         # Pydantic models for LLM output parsing
```

## Data Flow

### Step 1: Read from Database

**Technicals** (last 2 rows from `pl_contract_data_daily` + `pl_derived_indicators`):
- Produces 21 variable pairs (TOD/YES suffixes): CLOSE, HIGH, LOW, VOL, OI, VOLIMP, STOCKUS, COMNET, R1, PIVOT, S1, EMA9, EMA21, MACD, SIGN, RSI14, %K, %D, ATR, BSUP, BBINF
- Formatted as strings for LLM prompt injection

**Context** (from `pl_fundamental_article` + `pl_weather_observation`):
- MACRONEWS: concatenated summaries for target date
- METEOTODAY: weather summary for target date
- METEONEWS: last 100 weather observations formatted as historical context

**Ensemble Diagnostics** (from `pl_orchestrator_decision`, if present):
- 25 fields including `decision_wrapped`, `soft_gate_decision`, `net_score`, `running_acc_5d`, specialized voter flags
- Used by LLM Call #2 to justify ensemble decision (auto-alignment)
- Absent for historical dates before ensemble existed (legacy path remains unchanged)

### Step 2: LLM Call #1 — Macro & Weather Analysis

**Input**: MACRONEWS, METEOTODAY, METEONEWS, target date
**Output**: `MacroAnalysisOutput` (JSON-parsed)
```json
{
  "date": "19/12/2024",
  "macroeco_bonus": -0.06,
  "eco": "...30-word synthesis..."
}
```
**Model**: `gpt-4-turbo` | **Temperature**: 1.0

### Step 3: Compute Final Indicator

Reads z-scores and momentum from `pl_derived_indicators`, applies the power formula from `app.engine.composite.compute_score()` with fresh macroeco_bonus, returns a float score.

### Step 4: LLM Call #2 — Trading Decision

**Input**: All 42 technicals (today + yesterday), FINAL_INDICATOR, CONCLUSION, ensemble diagnostics (if present)
**Output**: `TradingDecisionOutput` (JSON-parsed)
```json
{
  "decision": "OPEN",
  "confiance": 3,
  "direction": "HAUSSIERE",
  "conclusion": "...full justification text..."
}
```
**Model**: `gpt-4-turbo` | **Temperature**: 0.7

**Auto-alignment (P4 upgrade)**:
- If ensemble row exists for (data_date, contract), LLM Call #2 receives ensemble diagnostics + special prompt injection (`CALL_2_PROMPT_ENSEMBLE`)
- LLM justifies `decision_wrapped` (the ensemble's pinned decision) instead of deriving its own
- Result written to ensemble row (preserving immutability of ensemble decision)
- If no ensemble row: legacy path (LLM derives decision from final_indicator)

### Step 5: Write Results

**Target table**: `pl_indicator_daily` at `(date, contract_id, algorithm_version_id)`
- Columns updated: `macroeco_bonus`, `final_indicator`, `decision`, `confidence`, `direction`, `conclusion`
- Idempotency check: fails if row already has a decision (unless `--force`)

**Signal component**: `pl_signal_component` macroeco row
- `raw_value` = `macroeco_bonus`
- `normalized_value` = `macroeco_bonus` (no normalization for this contributor)

**Audit trail**: 2 rows inserted to `aud_llm_call`
- Call #1: macro analysis request + response + token counts
- Call #2: trading decision request + response + token counts

## Date Semantics (P2b Pipeline)

Two distinct dates flow through this engine:

Both are resolved once from `resolve_phase_b_dates(args.session_date)` (`scripts/db.py`):

- **`data_date`** (last completed session = the row date):
  - Set directly by `--session-date` (backfill), or the cron default = last completed session
  - Used as the WHERE/UPDATE key for all writes (pl_indicator_daily, pl_signal_component, aud_llm_call)
  - Ensures writes target the same row that `cc-compute-indicators` wrote at 19:15 UTC

- **`target_date`** (upcoming session = `next_session(data_date)`):
  - Derived, never operator-facing
  - Used for human-facing labels and Sentry context, and to frame the P2b-keyed reads

**Example**: Tuesday 19:20 UTC cron (eve of Wednesday trading)
- `data_date = 2026-03-17` (Tue, last completed session) — the row every write targets
- `target_date = 2026-03-18` (Wed, upcoming session) — framing only
- Writes `pl_indicator_daily` where `date = 2026-03-17` (same as `cc-compute-indicators` wrote)
- To backfill this same row manually: `--session-date 2026-03-17`

## P2b Gate (Eve-of-Trading-Day)

The job skips cleanly when tomorrow is not a trading session (weekends, exchange holidays):

```python
if not is_eve_of_trading_day():
    logger.info("tomorrow is not a trading day — skipping cleanly")
    return 0  # Exit 0 so Sentry cron monitor doesn't alert
```

Flags that bypass the gate:
- `--session-date YYYY-MM-DD`: explicit backfill (forces run for the given session)
- `--force`: operator override

## Algorithm Version Resolution

**Default behavior** (backward compatible):
- If no `--algorithm-version` flag: resolves to row where `is_active=TRUE`
- Multiple versions can coexist; only one is `is_active`

**Pinned behavior** (C5 launch + historical backfills):
- `--algorithm-version legacy`: targets the row with `name='legacy'` regardless of `is_active` status
- Allows LLM decisions for legacy to coexist with ensemble without overwriting
- Raises `AlgorithmVersionNotFoundError` (fail-loud) if named version doesn't exist

Cached after first lookup to ensure read and write target the same row even if `is_active` rotates mid-run.

## LLM Output Parsing

Replaces fragile regex parsers with Pydantic models and JSON parsing.

**`MacroAnalysisOutput`**:
- `date`: date string in DD/MM/YYYY format
- `macroeco_bonus`: float between -0.10 and +0.10
- `eco`: string (30-word synthesis)

**`TradingDecisionOutput`**:
- `decision`: one of `OPEN`, `MONITOR`, `HEDGE`
- `confiance`: int 1-5 (confidence)
- `direction`: one of `HAUSSIERE`, `NEUTRE`, `BAISSIERE`
- `conclusion`: full justification text

Parser handles markdown fences, surrounding prose, and unescaped newlines in JSON string values (robust to LLM formatting variations).

## Observability

- **Sentry cron monitoring**: `@monitor(monitor_slug="daily-analysis")` on main()
- **Sentry context**: target date, contract, macroeco_bonus, final_indicator, decision, confiance, direction, token counts, dry_run flag
- **Structured logging**: data read counts, LLM token usage, write confirmations, timing
- **`--dry-run`**: logs every step, writes nothing

## Environment Variables

```bash
# Required
OPENAI_API_KEY=sk-...                    # OpenAI API key
SENTRY_DSN=...                           # Sentry monitoring

# Optional
LLM_MODEL=gpt-4-turbo                    # Model override
DATABASE_SYNC_URL=postgresql+psycopg2://...  # DB connection (auto from app config)
```

## Deployment (GCP Cloud Run)

| Field | Value |
|-------|-------|
| **Cloud Run Job** | `cc-daily-analysis` |
| **Image** | `backend/Dockerfile.jobs` |
| **Cloud Scheduler** | `0 19 * * 1-5` (7:00 PM UTC, weekdays) — runs Phase B only when `is_eve_of_trading_day()` |
| **Command** | `poetry run daily-analysis --algorithm-version legacy` |
| **Sentry monitor slug** | `daily-analysis` |

## Pipeline Context

Part of the nightly pipeline (Phase B):

```
19:00 UTC  -- cc-meteo-agent              → pl_weather_observation
19:05 UTC  -- cc-press-review-agent       → pl_fundamental_article
19:18 UTC  -- cc-ensemble-compute         → pl_orchestrator_decision + ensemble row
19:20 UTC  -- cc-daily-analysis           → UPDATE pl_indicator_daily (legacy row)
19:25 UTC  -- cc-ensemble-explainer       → UPDATE pl_indicator_daily (ensemble row)
19:30 UTC  -- cc-compass-brief            → Google Drive .txt
19:35 UTC  -- cc-compass-brief-ensemble   → Google Drive .txt
```

Full schedule and Phase A (scrapers + indicators): see `CLAUDE.md` § Nightly Pipeline Schedule.

## Error Handling

Follows fail-loud protocol (no silent recovery):

- **Missing data**: exits 1 if upstream scrapers haven't populated `pl_contract_data_daily` for the previous session (unless `--force`)
- **Algorithm version not found**: exits 1 if `--algorithm-version` targets a name with no matching row
- **Write failure**: exits 1 if LLM calls succeed but database UPDATE matched 0 rows (indicates missing compute-indicators output)
- **LLM call failure**: exits 1, logged to Sentry with full context

All errors are explicitly logged at ERROR level with structured context. No retries or fallbacks — the operator diagnoses and reruns manually.

## Not Yet Implemented

- **Email sender**: Daily analysis email via Gmail API (P3 future)
