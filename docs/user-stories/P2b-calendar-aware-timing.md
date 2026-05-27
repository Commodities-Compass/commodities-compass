# User Story: Calendar-Aware Pipeline Timing (Two-Phase Split)

**Statut :** Shippé
**Date :** 2026-05-13 (spec) / 2026-05-26 (livraison)
**Owner :** Hedi
**Cible repo :** `docs/user-stories/P2b-calendar-aware-timing.md`

> **2026-05-26 — Livraison** :
> - Helpers ajoutés : `get_previous_trading_day_sync` ([backend/app/utils/trading_calendar.py](../../backend/app/utils/trading_calendar.py)), `get_next_session_date`, `is_eve_of_trading_day`, `get_previous_session_date` ([backend/scripts/db.py](../../backend/scripts/db.py)).
> - 4 agents Phase B refactorés : `press_review_agent`, `meteo_agent`, `daily_analysis`, `compass_brief` — tous acceptent `--target-date YYYY-MM-DD` (default = next_session_date(today)) et gate sur `is_eve_of_trading_day()`.
> - Bug fix : `press_review_agent` `theme_sentiments` écrivait `date.today()` au lieu de la date de l'article (main.py:195). Fix dans le même commit que le refactor.
> - Cron Terraform : 4 agents passés de `M 19 * * 1-5` à `M 19 * * *` (daily). Sentry monitor accepte « skip exit 0 » comme succès.
> - Docs : [CLAUDE.md](../../CLAUDE.md) « Nightly Pipeline Schedule » mis à jour avec split Phase A / Phase B. [docs/runbooks/pipeline-failure-recovery.md](../../docs/runbooks/pipeline-failure-recovery.md) cascade mise à jour.

## Epic

As the **CTO/sole operator**, I need the soft-data side of the nightly pipeline (press review, weather, LLM decision, brief) to run on the eve of the **next trading session** instead of the evening of the previous close, so that users open the dashboard to news and weather under 12h old — even on Monday opens after a weekend or after a holiday bridge.

Companion story to [P2-pipeline-orchestrator.md](./P2-pipeline-orchestrator.md). P2 is about reliability (orchestration, retries, completeness gate, summary alert). **P2b is about freshness**. The two ship independently and compose cleanly.

---

## Context

**Current state**: All 8 jobs fire weekdays 19:00–19:30 UTC on trading day T. Market-data scrapers (Barchart, ICE, CFTC) need T's close, so their timing is correct. But press review, meteo agent, daily analysis, and compass brief all write to `date = date.today()` = T's session date — which means the data the user sees Tuesday morning is from Monday 19:00, and on Monday morning after a weekend it is from **Friday 19:00, ~60h old**.

Cocoa is the worst case for this: West Africa weather updates and weekend production headlines (Ghana/Côte d'Ivoire) often move the open, and our Sunday-evening trader narratives never make it into Monday's brief.

**Target state**: Pipeline is split into two phases.
- **Phase A — Market close** (T 19:00 UTC, Mon–Fri): scrapers + indicator computation. Unchanged.
- **Phase B — Next-session refresh** (J-1 of next trading day, 19:20–19:35 UTC, daily with calendar gate): meteo, press review, daily analysis, compass brief. Writes are keyed to the **next trading day's session date**, not the run day.

Bridges weekend and holiday gaps automatically. On a normal Mon→Tue cycle, Phase A and Phase B both fire Monday evening, ~20 minutes apart. On the Fri→Mon cycle, Phase A fires Friday and Phase B fires Sunday.

---

## User Stories

### US-1: Phase split with stable Phase A

**As** the pipeline operator,
**I want** the market-data scrapers and indicator computation to keep firing exactly when they do today,
**So that** the freshness change is additive — nothing about how market data is captured, written, or computed shifts.

**Acceptance criteria:**
- `cc-barchart-scraper`, `cc-ice-stocks-scraper`, `cc-cftc-scraper`, `cc-compute-indicators` schedules unchanged (`0/5/15 19 * * 1-5`).
- Their writes still key on `date = session date T` (the day the market closed).
- `pl_contract_data_daily.display_date` semantics unchanged (Barchart's `get_display_date()` still computes next trading day for dashboard rendering).
- No change to the indicator engine, contract resolution, or `pl_signal_component` decomposition.

### US-2: Phase B writes to next trading day

**As** a dashboard user,
**I want** the press review, weather report, LLM decision, and audio brief I see at session open to be tagged with **that session's date**,
**So that** the data is correctly attributed to the session it informs, and the dashboard read path remains a single direct lookup by session date.

**Acceptance criteria:**
- `pl_fundamental_article.date` = next trading day at write time (not run day).
- `pl_weather_observation.date` = next trading day.
- `pl_indicator_daily` LLM fields (decision, confidence, direction, conclusion, macroeco_bonus, eco) populated for next trading day.
- Compass brief file in Google Drive named `YYYYMMDD-CompassBrief.txt` where `YYYYMMDD` = **session_date** (= the trading day the brief covers, NOT the publication day / next trading day). Session-date naming is required so the dashboard audio lookup (`audio_service.py`, which resolves display_date → session_date) finds the matching NotebookLM-produced audio file.
- The agents accept an explicit `--target-date YYYY-MM-DD` CLI flag for backfills and tests. Default = `get_next_session_date(today())`.
- Dashboard `GET /dashboard?date=<session_date>` query path is unchanged — finds the rows directly, no walk-back logic, no asymmetric joins.

### US-3: Calendar-aware gate

**As** the pipeline operator,
**I want** Phase B to fire only on evenings where the next calendar day is a trading day,
**So that** I don't run expensive LLM jobs for sessions that don't exist (weekends, holidays) and I don't have to maintain a custom cron pattern that bakes in the ICE Europe calendar.

**Acceptance criteria:**
- Phase B Cloud Scheduler jobs cron pattern is daily (`20 19 * * *`, `30 19 * * *`, `35 19 * * *`) — Cloud Scheduler does not know about trading days.
- Each Phase B agent runs a gate at startup: *if `is_trading_day_sync(today() + 1d, "IFEU")` is `False`, log skip reason and exit 0*.
- The gate uses `ref_trading_calendar` as the single source of truth (handles weekends, ICE holidays, half-day Fridays, DST uniformly).
- On Sat, Sun-pre-holiday, day-before-back-to-back-holiday: agents log "next day not a trading day" and exit cleanly.
- On Sun (with Mon trading), Thu (with Fri holiday but Mon trading following weekend): no special-casing needed — the gate is purely local.

### US-4: Press review and meteo content framing

**As** a dashboard reader,
**I want** the press review digest and weather summary to be **framed for the upcoming session**, not "today",
**So that** the LLM output reads naturally and doesn't refer to "today's market" when "today" is Sunday and there's no market.

**Acceptance criteria:**
- Press review prompt injects the explicit "for trading session [TARGET_DATE]" instruction; the LLM stops saying "aujourd'hui" / "today" when produced on a non-trading day.
- Weather summary prompt similarly framed for the upcoming session.
- Daily analysis prompt: "decision for session [TARGET_DATE], based on close of [TARGET_DATE - 1 business day]".
- Regression test: prompt must contain the explicit target date string.

### US-5: Daily analysis reads correct upstream session

**As** the LLM decision engine,
**I want** to read market data and technical indicators from the **last completed market session**, not from the future,
**So that** the `has_contract_data_for_date()` precondition correctly validates the input data rather than checking for a session that hasn't happened yet.

**Acceptance criteria:**
- `has_contract_data_for_date` (or its replacement) checks for `pl_contract_data_daily` rows on `previous_trading_day(target_date)` — the last completed session before the upcoming one.
- LLM Call #1 (macro/weather) and Call #2 (decision) both read from the previous trading day's technicals + Phase B's just-written press review + meteo for the upcoming session.
- Output is written under `date = target_date` (next trading day), not the previous session.
- `--date YYYY-MM-DD` flag still works for manual backfills; default changes from `datetime.now(utc).date()` to `get_next_session_date(today())`.

### US-6: Compass brief targets next session

**As** the operator generating the NotebookLM audio podcast,
**I want** the brief file uploaded Sunday evening to be named for Monday's session,
**So that** when I generate audio from it and upload `20260518-CompassAudio.m4a`, the existing dashboard fetch path picks it up on Monday open with no frontend changes.

**Acceptance criteria:**
- Brief filename uses `target_date` formatted as `YYYYMMDD`.
- Brief content header references the upcoming session.
- The "last 2 distinct dates from `pl_contract_data_daily`" technical context block remains as-is — those are completed market sessions and provide the close-over-close narrative the brief needs.
- Existing dashboard audio fetch path (which already maps weekend/holiday lookups to next session) requires no change.

---

## Technical Design

### Phase A vs Phase B (visual)

```
Trading day T (Mon–Fri)                Eve of next trading day (J-1 of T+next)
                                       — runs daily, gated on tomorrow being a trading day
─────────────────────────              ─────────────────────────
19:00  cc-barchart-scraper             19:20  cc-meteo-agent
19:05  cc-ice-stocks-scraper           19:20  cc-press-review-agent
19:05  cc-cftc-scraper                 19:30  cc-daily-analysis
19:15  cc-compute-indicators           19:35  cc-compass-brief
       → date = T                             → date = T+next (next trading day)
```

### Firing pattern (representative two-week sample)

| Day                          | Phase A | Phase B (gate result)              | Phase B `target_date` |
|------------------------------|---------|------------------------------------|-----------------------|
| Mon 2026-05-11               | yes     | yes (Tue is trading)               | Tue 2026-05-12        |
| Tue 2026-05-12               | yes     | yes (Wed)                          | Wed 2026-05-13        |
| Wed 2026-05-13               | yes     | yes (Thu)                          | Thu 2026-05-14        |
| Thu 2026-05-14               | yes     | yes (Fri)                          | Fri 2026-05-15        |
| Fri 2026-05-15               | yes     | **skip** (Sat non-trading)         | —                     |
| Sat 2026-05-16               | no      | **skip** (Sun non-trading)         | —                     |
| **Sun 2026-05-17**           | no      | **yes** (Mon is trading)           | Mon 2026-05-18        |
| Mon (with Tue holiday)       | yes     | **skip** (Tue non-trading)         | —                     |
| Tue (the holiday itself)     | no      | **yes** (Wed trading)              | Wed                   |
| Fri (with Mon holiday)       | yes     | **skip** (Sat)                     | —                     |
| Sat (Mon is holiday)         | no      | **skip** (Sun)                     | —                     |
| Sun (Mon is holiday)         | no      | **skip** (Mon is holiday)          | —                     |
| Mon (the holiday itself)     | no      | **yes** (Tue trading)              | Tue                   |

**Gate logic** (one boolean, used by all four Phase B agents):

```python
def is_eve_of_trading_day(today: date | None = None, exchange_code: str = "IFEU") -> bool:
    """True iff tomorrow (today + 1 calendar day) is a trading day."""
    today = today or date.today()
    return is_trading_day_sync(today + timedelta(days=1), exchange_code)
```

The question is purely local ("is tomorrow a trading day?") — never refers to upstream history. This is why every holiday pattern self-corrects with no freshness loss.

### Default target date computation

```python
def get_next_session_date(target_date: date | None = None, exchange_code: str = "IFEU") -> date:
    """Next trading session strictly after target_date (default: today)."""
    target_date = target_date or date.today()
    return get_next_trading_day_sync(session, target_date, exchange_code)
```

Mirrors the existing `get_display_date` in `backend/scripts/db.py` (same session pattern, same fail-closed behavior).

### Writers — date plumbing

| Agent              | Default `target_date`                | Writes to                                  |
|--------------------|--------------------------------------|--------------------------------------------|
| press_review_agent | `get_next_session_date()`            | `pl_fundamental_article.date`              |
| meteo_agent        | `get_next_session_date()`            | `pl_weather_observation.date`              |
| daily_analysis     | `get_next_session_date()`            | `pl_indicator_daily.date` (LLM fields)     |
| compass_brief      | `get_next_session_date()`            | Drive filename + content header            |

For daily analysis the precondition check reads from `previous_trading_day(target_date)` in `pl_contract_data_daily` and `pl_indicator_daily` (technical scores).

### Cloud Scheduler restructure

```hcl
# infra/terraform/scheduler.tf
locals {
  phase_a_jobs = {
    barchart           = "0 19 * * 1-5"
    ice_stocks         = "5 19 * * 1-5"
    cftc               = "5 19 * * 1-5"
    compute_indicators = "15 19 * * 1-5"
  }
  phase_b_jobs = {
    meteo          = "20 19 * * *"   # daily; agent-internal gate handles non-trading-eve
    press_review   = "20 19 * * *"
    daily_analysis = "30 19 * * *"
    compass_brief  = "35 19 * * *"
  }
}
```

### Sentry cron monitor updates

Phase A monitors keep their cron strings. Phase B monitors switch to daily cron + the agents' early-exit-0 on skip days registers as success, so no false positive "missed" alerts on Sat/Sun-pre-holiday.

---

## Out of Scope

- The P2 orchestrator (single entrypoint, retry, completeness gate, summary alert). Composes cleanly with this story but ships independently.
- Backfilling historical `pl_fundamental_article` / `pl_weather_observation` rows from "close day" to "next session day". Old rows stay where they are.
- Multi-tenant or multi-exchange — gate hardcoded to `IFEU` (consistent with `get_display_date`).
- Pre-market intraday refreshes or reducing Phase A latency.

## Dependencies

- `ref_trading_calendar` is the single source of truth for IFEU trading days (already true).
- `get_next_trading_day_sync`, `is_trading_day_sync` already exist in `backend/app/utils/trading_calendar.py`. A `get_previous_trading_day_sync` may need to be added (trivial sibling of the async version at line 90).
- All four Phase B agents accept a `--target-date` flag (new); their DB writers accept an explicit date parameter (new).

## Migration Plan

1. Add shared helpers (`get_next_session_date`, `is_eve_of_trading_day`, possibly `get_previous_trading_day_sync`). Unit-test against `ref_trading_calendar` covering: weekday, Fri, Sat, Sun-before-Mon, Sun-before-holiday, Tue-when-Tue-is-holiday, back-to-back holidays.
2. Plumb `--target-date` and writer parameter through each Phase B agent. Rewrite prompts to inject the explicit target date string.
3. Adjust `daily_analysis` precondition to read from `previous_trading_day(target_date)`.
4. Update Compass brief filename + content header date.
5. Local dry-run validation: simulate Fri, Sat, Sun, Mon-with-Tue-holiday with `freezegun` or `--simulate-date`. Verify gate decisions and target_date in dry-run logs.
6. Deploy to GCP on a Friday morning. Phase A unchanged path runs Fri 19:00.
7. Sun 19:20 UTC: monitor first calendar-aware run. Verify in Cloud SQL: `SELECT date FROM pl_fundamental_article WHERE date = '<next Mon>';` returns the new row.
8. Mon 07:00 UTC: open dashboard, verify fresh Sunday-evening content surfaces under Monday's session date.
9. Switch Sentry monitors to the new daily cron pattern.
10. Update `CLAUDE.md` schedule diagram and `docs/runbooks/pipeline-failure-recovery.md` cascade.
