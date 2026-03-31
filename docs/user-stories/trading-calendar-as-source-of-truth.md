# User Story: Trading Calendar as Single Source of Truth for Dates

## Epic

As the **CTO/sole operator**, I need the entire application to use `ref_trading_calendar` as the single source of truth for date resolution, so that the system stops guessing dates by walking back through data gaps or falling back to "today minus weekends".

---

## Context

**Current state**: Date resolution is scattered and brittle:
- `get_business_date()` converts weekends to Friday — ignores holidays, early closes, exchange-specific closures
- Dashboard endpoints: "if no data for target_date, try previous day" or "return latest row" — silent data gaps
- Scrapers: barchart scraper runs on weekdays blindly, wastes resources on holidays
- `_date_filter()` does TIMESTAMP range tricks on legacy tables, direct `==` on DATE columns — inconsistent
- No concept of "is today a trading day?" — if ICE Europe is closed (Good Friday, Christmas), scrapers run and fail silently

**Target state**: One function — `get_latest_trading_day(db, exchange, reference_date)` — that returns the most recent trading day from `ref_trading_calendar`. Everything uses it: dashboard API, scrapers, agents, compute engine.

---

## User Stories

### US-1: Trading day resolution from ref_trading_calendar

**As** a dashboard user,
**I want** the API to always return data for the most recent trading day,
**So that** I see valid data instead of 404s on holidays, weekends, or days when no data was scraped.

**Acceptance criteria:**
- `get_latest_trading_day(db, exchange_code, reference_date)` queries `ref_trading_calendar WHERE is_trading_day = true AND date <= reference_date ORDER BY date DESC LIMIT 1`
- Replace all calls to `get_business_date()` in dashboard endpoints with `get_latest_trading_day()`
- Dashboard never returns 404 for "no data" — it returns the most recent trading day's data
- Works for any exchange (ICE Europe, ICE US) — calendar is per-exchange

### US-2: Previous trading day resolution

**As** the pipeline operator,
**I want** a function that returns the previous trading day relative to a given date,
**So that** YTD calculations, day-over-day comparisons, and "walk back" logic use real trading days.

**Acceptance criteria:**
- `get_previous_trading_day(db, exchange_code, reference_date)` returns the trading day strictly before `reference_date`
- `calculate_ytd_performance()` iterates over actual trading days, not calendar days
- No more "walk back through dates until you find data" pattern — the calendar tells you which days have data

### US-3: Scrapers skip non-trading days

**As** the pipeline operator,
**I want** scrapers to check if today is a trading day before running,
**So that** they don't waste resources and produce confusing error logs on holidays.

**Acceptance criteria:**
- `is_trading_day(db, exchange_code, date)` checks `ref_trading_calendar`
- Scrapers call this at startup: if not a trading day, log `"Skipping: {date} is not a trading day for {exchange}"` and exit 0
- Cloud Scheduler still fires daily (simpler than maintaining holiday-aware cron expressions) — the scraper self-skips
- Meteo agent runs regardless (weather doesn't follow exchange calendar) — configurable per job

### US-4: Kill get_business_date() and _date_filter()

**As** a developer,
**I want** to remove the legacy date helpers that guess business days from weekday numbers,
**So that** there's one way to resolve dates and it's always correct.

**Acceptance criteria:**
- `get_business_date()` removed from `app/utils/date_utils.py`
- `_date_filter()` removed from `dashboard_service.py` (pl_* tables use DATE columns, direct `==` works)
- All callers migrated to `get_latest_trading_day()` or `get_previous_trading_day()`
- `log_business_date_conversion()` removed (no more conversions to log)

### US-5: Populate ref_trading_calendar

**As** the pipeline operator,
**I want** ref_trading_calendar to be populated for the current and next year,
**So that** date resolution works without manual intervention.

**Acceptance criteria:**
- `poetry run seed-trading-calendar --year 2026 --exchange ICE_EU` populates the calendar
- Default: all weekdays are trading days, known holidays marked as `is_trading_day = false`
- `session_type` column used for: `regular`, `early_close`, `holiday`
- `reason` column used for: `"Good Friday"`, `"Christmas"`, `"ICE scheduled holiday"`
- Holiday list sourced from ICE exchange holiday calendar (published annually)
- Script is idempotent (re-running updates existing rows)

---

## Technical Design

### New functions in `app/utils/trading_calendar.py`

```python
async def get_latest_trading_day(
    db: AsyncSession,
    exchange_code: str = "ICE_EU",
    reference_date: date | None = None,
) -> date:
    """Most recent trading day <= reference_date."""

async def get_previous_trading_day(
    db: AsyncSession,
    exchange_code: str = "ICE_EU",
    reference_date: date | None = None,
) -> date:
    """Most recent trading day strictly < reference_date."""

async def is_trading_day(
    db: AsyncSession,
    exchange_code: str = "ICE_EU",
    target_date: date | None = None,
) -> bool:
    """True if target_date is a trading day for the exchange."""

# Sync variants for scrapers
def get_latest_trading_day_sync(db: Session, ...) -> date: ...
def is_trading_day_sync(db: Session, ...) -> bool: ...
```

### Migration path

| Current pattern | Replacement |
|----------------|-------------|
| `get_business_date(target_date)` | `await get_latest_trading_day(db, "ICE_EU", target_date)` |
| `_date_filter(col, business_date)` | `col == await get_latest_trading_day(db, ...)` |
| `if target_date is None: target_date = date.today()` | `await get_latest_trading_day(db)` (defaults to today) |
| Scraper runs → fails on holiday → Sentry alert | `if not is_trading_day_sync(db): exit(0)` |
| Walk back through rows until data found | Query directly for `get_latest_trading_day()` then `WHERE date = trading_day` |

### Affected files

| File | Change |
|------|--------|
| `app/utils/trading_calendar.py` | New — all trading day resolution functions |
| `app/utils/date_utils.py` | Remove `get_business_date()`, `log_business_date_conversion()` |
| `app/services/dashboard_service.py` | Replace all `get_business_date()` calls |
| `app/api/api_v1/endpoints/dashboard.py` | Replace `_parse_and_validate_date()` to use trading calendar |
| `scripts/barchart_scraper/main.py` | Add `is_trading_day` check at startup |
| `scripts/ice_stocks_scraper/main.py` | Same |
| `scripts/cftc_scraper/main.py` | Same |
| `scripts/daily_analysis/main.py` | Same |
| `scripts/compass_brief/main.py` | Same |

---

## Out of Scope

- Automatic holiday calendar sync from ICE website — manual annual update is fine
- Intraday session times (market open/close hours) — not needed for daily pipeline
- Multi-exchange orchestration (different holidays per exchange) — single commodity for now, but schema supports it

## Dependencies

- `ref_trading_calendar` table exists with `is_trading_day`, `session_type`, `reason` columns (already deployed)
- `ref_exchange` table has exchange entries (already seeded)
- `seed-trading-calendar` script exists (already registered in pyproject.toml)
