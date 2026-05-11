# User Story: Pipeline Orchestrator with Completeness Gate

## Epic

As the **CTO/sole operator**, I need the nightly data pipeline to be self-healing and observable, so that a single scraper failure doesn't silently break the dashboard for users the next morning.

---

## Context

**Current state**: 6 independent Railway crons fire at hardcoded times (21:00–22:15 UTC). No orchestration, no retry, no alerting beyond Sentry. If any scraper fails (e.g. Barchart OI=0 on 2026-03-23), downstream jobs run on stale data and the dashboard returns 404. The operator discovers the issue hours later by manually checking.

**Target state**: A single orchestrator cron replaces all individual crons. It runs scrapers, validates data completeness, retries failures, degrades gracefully on soft fields, and sends one summary alert per run.

---

## User Stories

### US-1: Single orchestrator entry point

**As** the pipeline operator,
**I want** a single cron job that runs the entire nightly pipeline in the correct order,
**So that** I don't maintain 6+ independent cron schedules and hope the timing works out.

**Acceptance criteria:**
- One Railway cron at 21:00 UTC replaces all individual scraper/agent crons
- Scrapers (barchart, ICE, CFTC, press review, meteo) run in parallel in Stage 1
- Downstream jobs (daily analysis, compass brief, ETL import) run sequentially in Stage 2, only after Stage 1 passes the completeness gate
- Existing scraper scripts are called as subprocesses — no rewrite of scraper internals
- Exit code 0 = full success, exit code 1 = degraded (soft fields missing), exit code 2 = hard failure

### US-2: Declarative completeness gate

**As** the pipeline operator,
**I want** a data completeness check between scraping and downstream processing,
**So that** downstream jobs never run on missing or incomplete data without an explicit decision.

**Acceptance criteria:**
- Completeness spec defines **hard** fields (block pipeline if missing) and **soft** fields (warn, proceed)
- Gate checks today's row exists in each target table with hard fields non-null
- Hard fields for OHLCV: `close`, `high`, `low`, `volume`
- Soft fields for OHLCV: `oi`, `implied_volatility`
- Soft fields for market_research/weather: all (pipeline proceeds without them)
- Gate runs after Stage 1 scrapers complete
- Gate result is logged: `PASS` / `DEGRADED` (soft missing) / `FAIL` (hard missing)

### US-3: Automatic retry on failure

**As** the pipeline operator,
**I want** failed scrapers to be retried automatically before the pipeline gives up,
**So that** transient failures (network timeouts, delayed OI settlement) don't require manual intervention.

**Acceptance criteria:**
- If completeness gate returns `FAIL`, retry only the failed scrapers (not all)
- Max 2 retries per scraper, 5-minute delay between attempts
- Total retry window fits within 20 minutes (pipeline must finish before 21:30 for downstream at 21:30+)
- Each retry attempt is logged with attempt number and result
- If still `FAIL` after retries: alert, skip downstream, exit code 2

### US-4: Graceful degradation

**As** a dashboard user,
**I want** the dashboard to show the best available data even when some fields are missing,
**So that** I still get trading signals on days when OI or weather data is delayed.

**Acceptance criteria:**
- When soft fields are missing, the pipeline proceeds with downstream jobs
- Dashboard endpoints return data with null soft fields rather than 404
- The completeness gate logs which soft fields are missing
- The summary alert indicates `DEGRADED` status with details on what's missing

### US-5: Pipeline summary alert

**As** the pipeline operator,
**I want** a single summary notification after each pipeline run,
**So that** I know the pipeline status without checking Railway logs manually.

**Acceptance criteria:**
- One alert per pipeline run (not per scraper)
- Alert includes: run status (PASS/DEGRADED/FAIL), per-scraper results, completeness gate result, downstream job results, total duration
- Alert sent via email (Sentry alert rule or direct SMTP — TBD based on simplicity)
- No alert on full PASS (optional — configurable, default: alert only on DEGRADED/FAIL)
- Alert fires within 5 minutes of pipeline completion

### US-6: Pipeline run logging

**As** the pipeline operator,
**I want** structured logs for each pipeline run,
**So that** I can debug failures without SSH-ing into Railway.

**Acceptance criteria:**
- Each run gets a unique `run_id` (UUID)
- All log lines include `run_id`, stage, job name, status, duration
- Logs are written to stdout (Railway captures them)
- Final summary log line with all job statuses and total duration

---

## Technical Design

### Architecture

```
pipeline_orchestrator.py (single Railway cron, 21:00 UTC)
│
├── Stage 1: Scrapers (parallel)
│   ├── barchart_scraper    → TECHNICALS (C,H,L,V,OI,IV) + pl_contract_data_daily
│   ├── ice_stocks_scraper  → TECHNICALS (STOCK US)
│   ├── cftc_scraper        → TECHNICALS (COM NET US)
│   ├── press_review_agent  → BIBLIO_ALL + pl_fundamental_article
│   └── meteo_agent         → METEO_ALL + pl_weather_observation
│
├── Completeness Gate
│   ├── Check hard fields in Google Sheets / pl_contract_data_daily
│   ├── PASS → Stage 2
│   ├── DEGRADED → log warning, Stage 2
│   └── FAIL → retry failed scrapers (max 2x, 5min delay)
│        └── Still FAIL → alert, skip Stage 2, exit 2
│
├── Stage 2: Downstream (sequential)
│   ├── daily_analysis      → INDICATOR + TECHNICALS (decision/score)
│   ├── compass_brief       → Google Drive (.txt)
│   └── data_import (ETL)   → PostgreSQL (full refresh)
│
└── Summary: log + alert
```

### Completeness spec (config, not code)

```python
COMPLETENESS_SPEC = {
    "technicals": {
        "date_column": "timestamp",
        "hard": ["close", "high", "low", "volume"],
        "soft": ["open_interest", "implied_volatility"],
    },
    "market_research": {
        "date_column": "date",
        "hard": [],
        "soft": ["summary"],
    },
    "weather_data": {
        "date_column": "date",
        "hard": [],
        "soft": ["observation"],
    },
}
```

### Job definitions

```python
SCRAPER_JOBS = {
    "barchart": {
        "command": ["poetry", "run", "python", "-m", "scripts.barchart_scraper.main", "--sheet", "production"],
        "timeout": 120,
        "feeds": "technicals",
    },
    "ice_stocks": {
        "command": ["poetry", "run", "python", "-m", "scripts.ice_stocks_scraper.main", "--sheet", "production"],
        "timeout": 60,
        "feeds": "technicals",
    },
    "cftc": {
        "command": ["poetry", "run", "python", "-m", "scripts.cftc_scraper.main", "--sheet", "production"],
        "timeout": 60,
        "feeds": "technicals",
    },
    "press_review": {
        "command": ["poetry", "run", "press-review", "--sheet", "production"],
        "timeout": 180,
        "feeds": "market_research",
    },
    "meteo": {
        "command": ["poetry", "run", "meteo-agent", "--sheet", "production"],
        "timeout": 120,
        "feeds": "weather_data",
    },
}

DOWNSTREAM_JOBS = [
    {"name": "daily_analysis", "command": ["poetry", "run", "daily-analysis", "--sheet", "production"], "timeout": 180},
    {"name": "compass_brief", "command": ["poetry", "run", "compass-brief"], "timeout": 120},
    {"name": "etl_import", "command": ["poetry", "run", "import"], "timeout": 300},
]
```

---

## Out of Scope

- Airflow/Prefect/Dagster — overkill at current scale (1 commodity, 5 scrapers)
- Multi-source fallback (Yahoo Finance backup) — different data formats, more complexity than value
- Moving scrapers to Cloud Run Jobs — Phase 4+, this orchestrator pattern carries over
- Moving completeness spec to database — do it when we add a second commodity

## Dependencies

- Existing scraper scripts work as standalone CLI commands (already true)
- Sentry configured with cron monitors (already true for barchart)
- Railway supports a single cron with longer runtime (~30 min max vs current ~2 min per scraper)

## Migration Plan

1. Build orchestrator, test locally with `--dry-run`
2. Deploy orchestrator as new Railway cron at 21:00 UTC
3. Disable individual scraper crons one by one, verify orchestrator handles them
4. Remove individual cron services from Railway once stable (keep code, just remove cron triggers)
