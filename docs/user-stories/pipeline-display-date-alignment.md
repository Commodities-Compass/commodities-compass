# User Story: Pipeline Display-Date Alignment

**Date:** 2026-04-06
**Priority:** P1 — Completed
**Source:** Easter 2026 UX confusion — calendar showed non-trading days as selectable, data offset logic scattered in frontend

---

## Context

The pipeline scrapes market data on the evening of trading day N and stores it with `date=N` (the session date). Previously, the frontend applied a `-1 day` offset (`getYesterdayISO()`) so that when a user opened the dashboard on day N+1, they saw data from day N. This broke on long weekends and holidays (Easter: user saw "April 6" which was Easter Monday, a non-trading day).

## Solution Implemented

### Two-column approach on `pl_contract_data_daily`

```
date         = 2026-04-02  (session date — immutable truth, used by indicator engine)
display_date = 2026-04-07  (next trading day — when users see this data)
```

- **`date`** is the real trading session date. Never changed. Used by the indicator engine for rolling z-scores, momentum, backtesting.
- **`display_date`** = `next_trading_day(date)` from `ref_trading_calendar`. Set by the barchart scraper via `get_display_date()`. Used by the frontend calendar and dashboard date resolution.

All other tables (`pl_indicator_daily`, `pl_derived_indicators`, `pl_signal_component`, `pl_fundamental_article`, `pl_weather_observation`) keep `date` = session date only.

### Frontend changes

- Calendar defaults to `MAX(display_date)` from the `/non-trading-days` endpoint
- Non-trading days (weekends + exchange holidays) are greyed out in the calendar picker
- Arrow navigation skips non-trading days
- **Removed `getYesterdayISO()` hack** — `currentDate` is passed directly as `targetDate` to all components

### Backend resolution

`_parse_and_validate_date()` in the dashboard endpoint:
1. Frontend sends `target_date=2026-04-07` (display date)
2. Backend: `SELECT date FROM pl_contract_data_daily WHERE display_date = '2026-04-07'` → `2026-04-02`
3. All downstream queries use `session_date = 2026-04-02`
4. Fallback to `get_latest_trading_day()` for pre-migration data

### Pipeline changes

Only the barchart scraper was changed — it writes `display_date = get_display_date()` alongside the session `date`. ICE/CFTC scrapers, AI agents, and the indicator engine are unchanged.

### Migration

Alembic migration `40aad93928c4`:
- `ALTER TABLE pl_contract_data_daily ADD COLUMN display_date DATE`
- Populated from `ref_trading_calendar` for all dates within calendar range (>= 2024-01-02)
- Historical data before 2024 has `display_date = NULL` (not displayed on dashboard)
- Added index `ix_contract_data_daily_display_date`

---

## Key Files

| File | Change |
|------|--------|
| `backend/app/utils/trading_calendar.py` | `get_next_trading_day()` + `_sync` |
| `backend/scripts/db.py` | `get_display_date()` central utility |
| `backend/app/models/pipeline.py` | `display_date` column on `PlContractDataDaily` |
| `backend/scripts/barchart_scraper/db_writer.py` | Writes `display_date` on insert/update |
| `backend/app/api/api_v1/endpoints/dashboard.py` | `_parse_and_validate_date()` resolves display→session, `/non-trading-days` returns `MAX(display_date)` |
| `frontend/src/pages/dashboard-page.tsx` | Removed `getYesterdayISO`, passes `currentDate` directly |
| `frontend/src/components/date-selector.tsx` | Disables non-trading days + skip in navigation |

## Easter 2026 Example

| User opens dashboard | Calendar shows | Data from session |
|---------------------|----------------|-------------------|
| April 2 (Thu) | "Thursday, April 2" | April 1 session |
| April 3-6 (Good Friday → Easter Mon) | **Greyed out** | — |
| April 7 (Tue) morning | "Tuesday, April 7" | April 2 session |
| April 7 (Tue) after pipeline | — | April 7 session stored with display_date=April 8 |
| April 8 (Wed) | "Wednesday, April 8" | April 7 session |
