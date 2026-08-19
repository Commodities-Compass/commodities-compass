# Date Semantics — `session date` vs `display_date`, Phase A / Phase B

> ⚠️ **Written 2026-06-18, before the regime+judge flip (2026-08-19).** The
> *paths* traced here — date semantics, roll handling, gating, failure
> propagation — still hold; they are what the audit was about. But the jobs it
> names on the decision leg (`cc-ensemble-compute`, `cc-ensemble-explainer`,
> `cc-daily-analysis`, `cc-compass-brief`, `cc-compass-brief-ensemble`) were
> **deleted**. Read them as "whatever occupies that slot": today it is
> `cc-regime-shadow` (19:50) then `cc-regime-brief` (19:55). This banner is
> deliberate — rewriting a dated audit at the present tense would destroy the
> record of what it actually found. Current state:
> [PIPELINE_REGIME_JUDGE.md](../PIPELINE_REGIME_JUDGE.md) ·
> [JOBS_AND_SCRAPERS.md](../JOBS_AND_SCRAPERS.md).


> Self-contained reference for the two date concepts that flow through the
> Commodities Compass pipeline, why they differ, and how every producer and
> consumer keeps them consistent. Read this before touching any scraper, agent,
> dashboard date-resolution path, or the trading calendar.

Related: [PIPELINE_LEGACY.md](../../archive/pipelines/PIPELINE_LEGACY.md), [PIPELINE_ENSEMBLE.md](../../archive/pipelines/PIPELINE_ENSEMBLE.md), [JOBS_AND_SCRAPERS.md](../JOBS_AND_SCRAPERS.md).

---

## 1. The two dates

The entire pipeline turns on a single distinction. Get this wrong and the
dashboard shows empty sections the morning after.

| Concept | Column / variable | Meaning | Mutability |
|---|---|---|---|
| **session date** (`date`) | `pl_contract_data_daily.date` and the `date` column on **every** other `pl_*` table | The day trading actually happened (market close = session T). The immutable truth. | Immutable. The single key every consumer queries by. |
| **display_date** | `pl_contract_data_daily.display_date` only | `next_trading_day(date)` — the day users first SEE this data on the dashboard. | Derived, lives on one table only. |

**Why they differ.** Market close for session T (e.g. Friday) is scraped and
computed Friday evening UTC, but the data is only surfaced to users on the next
trading morning (Monday). Users navigate the dashboard by the day they are
looking at it, not by the session that produced the numbers — so the calendar
and the frontend speak `display_date`, while the engine, all downstream tables,
and every internal join speak `session date`.

**Key invariant.** Only `pl_contract_data_daily` carries both columns. Every
other table (`pl_indicator_daily`, `pl_derived_indicators`, `pl_signal_component`,
`pl_orchestrator_decision`, `pl_specialist_prediction`, `pl_fundamental_article`,
`pl_article_segment`, `pl_weather_observation`, `pl_seasonal_score`) is keyed on
`date` = **session date** only. There is exactly one `display_date → session_date`
edge in the whole system, resolved once per request.

```
                       display_date = next_trading_day(date)
                      ┌──────────────────────────────────────┐
                      │                                        │
  pl_contract_data_daily.date  ──────────────►  pl_contract_data_daily.display_date
  (= session date T, immutable)                 (= when users see T's data)
        │
        │  every other pl_* table is keyed on THIS value (session date)
        ▼
  pl_indicator_daily.date · pl_orchestrator_decision.date · pl_fundamental_article.date · ...
```

---

## 2. Who computes `display_date`

`display_date` is set by the **barchart scraper** (the OHLCV row creator) and
nobody else. Other scrapers (`ice-stocks`, `cftc`, `barchart-stocks-eu`) only
UPDATE columns on a row the barchart scraper already created — they never touch
the date columns.

- `backend/scripts/barchart_scraper/main.py:83` — `display_date = get_display_date()`
- `backend/scripts/db.py:48` — `get_display_date(target_date=None)` → opens a short-lived sync session and returns `get_next_trading_day_sync(session, today, "IFEU")`.
- `backend/scripts/barchart_scraper/db_writer.py` — writes `date = row_date` (the scrape session date) and `display_date = display_date` (passed in). INSERT path sets both; UPDATE path refreshes `display_date`.

The trading-calendar primitives are the single source of truth and live in
`backend/app/utils/trading_calendar.py` (async for FastAPI, `_sync` for scripts),
all reading `ref_trading_calendar` for exchange `IFEU`:

- `get_next_trading_day[_sync]` — first trading day strictly after a date.
- `get_previous_trading_day[_sync]` — last trading day strictly before a date.
- `get_latest_trading_day[_sync]` — most recent trading day `<= date`.
- `is_trading_day[_sync]` — membership test (not in calendar ⇒ not a trading day).

All raise `TradingCalendarError` (fail-loud) when no day is found — never a
silent fallback.

---

## 3. The pipeline is split into two phases (P2b)

The nightly pipeline runs in two phases. Both write rows keyed to the **same
session date T**, but they fire at different times under different gates.

### Phase A — Market close (weekday-only cron, keyed to session T)

Scrapers + indicator computation. Cron is `* * * * 1-5`-style (weekday only).
Each row's `date` = the session that just closed = T. The barchart scraper also
stamps `display_date = next_trading_day(T)`.

```
18:30  cc-fx-scraper                  → pl_external_indicator (FX, ECB)
19:00  cc-barchart-scraper            → pl_contract_data_daily (OHLCV + IV) — sets date=T AND display_date
19:05  cc-ice-stocks-scraper          → pl_contract_data_daily (STOCK US)   — UPDATE row T
19:05  cc-cftc-scraper                → pl_contract_data_daily (COM NET US)  — UPDATE row T
19:10  cc-barchart-stocks-eu-scraper  → pl_contract_data_daily (stock_eu)    — UPDATE row T
19:15  cc-compute-indicators          → pl_derived_indicators + pl_indicator_daily (date=T)
22:10  cc-ice-cot-eu-scraper          → pl_cot_eu_weekly
```

### Phase B — Next-session refresh (daily cron, eve-of-trading gated, keyed to T)

LLM agents + ensemble. The cron is `M H * * *` (**every day**), and each agent
self-gates at startup on `is_eve_of_trading_day()`. This eliminates the old
Sun→Mon ~60h freshness gap that Phase B had when it ran weekday-only.

```
19:00  cc-meteo-agent             → pl_weather_observation (date = T)
19:05  cc-press-review-agent      → pl_fundamental_article + pl_article_segment (date = T)
19:18  cc-ensemble-compute        → pl_orchestrator_decision + 14 specialist_prediction + ensemble row (date = T)
19:20  cc-daily-analysis          → UPDATE pl_indicator_daily LEGACY row (date = T)
19:25  cc-ensemble-explainer      → UPDATE pl_indicator_daily ENSEMBLE row (date = T)
19:30  cc-compass-brief           → Drive: YYYYMMDD-CompassBrief.txt (legacy)
19:35  cc-compass-brief-ensemble  → Drive: YYYYMMDD-CompassBrief-Ensemble.txt
```

---

## 4. The Phase-B date dance (`target_date` vs `data_date`)

This is the part that bites. A Phase-B agent has two distinct dates and must
never confuse them.

- **`target_date`** = the **upcoming** trading session the work informs. Defaults to `get_next_session_date()` (= `get_next_trading_day_sync(today)`). Drives prompt framing, output filenames, and Sentry context.
- **`data_date`** = `get_previous_session_date(target_date)` = the **last completed** session = **session date T**. This is the value every DB write is keyed to.

Because `data_date = previous_session(next_session(today))`:

- **Mid-week** (Mon eve): `next_session(Mon)=Tue`, `previous_session(Tue)=Mon` → `data_date = today`.
- **Sunday eve**: `next_session(Sun)=Mon`, `previous_session(Mon)=Fri` → `data_date = Friday`. The agents fire Sunday evening (eve of Monday=trading) and tag their rows to **Friday's** session.

Helpers (all in `backend/scripts/db.py`) — the pair is resolved **once, never re-derived inline**:

- **`resolve_phase_b_dates(session_date=None) → PhaseBDates(target_date, data_date)`** — the single source of truth. Cron path (`session_date=None`): `target_date = next_session(today)`, `data_date = previous_session(target_date)`. Backfill path (explicit): `data_date = session_date` (what the operator types), `target_date = next_session(session_date)`. Both paths yield the same pair for the same session.
- **`phase_b_should_skip(session_date, force) → bool`** — the eve-of-trading-day gate. Skips only in the pure cron path (no explicit date, no `--force`) when tomorrow is not a trading day.
- Low-level primitives (called by the helper, rarely directly): `get_next_session_date`, `get_previous_session_date`, `is_eve_of_trading_day` (= `is_trading_day(today + 1 day)`, pure-local so every holiday self-corrects: Friday→Saturday-eve = false, Sunday→Monday-eve = true).

**CLI convention (uniform across all 7 Phase-B jobs):** the operator flag is **`--session-date T`** = the row date to (re)generate (= `data_date`). What you type is what lands; `target_date` (T+1) is derived and never operator-facing. A bare cron invocation (no flag) resolves the pair from `today()`.

Every Phase-B main is now the same three lines:

```python
if phase_b_should_skip(args.session_date, args.force):
    return 0
dates = resolve_phase_b_dates(args.session_date)
target_date, data_date = dates.target_date, dates.data_date  # ensemble_compute uses data_date only
```

Reference: `backend/scripts/db.py` (`PhaseBDates`, `resolve_phase_b_dates`, `phase_b_should_skip`) + any of the 7 mains (meteo_agent, press_review_agent, ensemble_compute, daily_analysis, ensemble_explainer, compass_brief, compass_brief_ensemble). Every `pl_*` row (`article_date`, `observation_date`, `pl_orchestrator_decision.date`, …) and brief filename is keyed to `data_date = T`; prompts are framed "for trading session {target_date}".

### Why the weekend matters (the load-bearing reason for daily Phase B)

The Sunday-eve fire is exactly how a weekend's news reaches the ensemble:

1. Sunday 19:05 — `cc-press-review-agent` writes `pl_article_segment` rows with `article_date = Friday` (= `data_date`).
2. Sunday 19:18 — `cc-ensemble-compute` reads those just-written segments (confidence ≥ 0.70, 90d window) via `MacroEventLayer`, before deciding **Friday's** row.

If Phase B were weekday-only, Friday's published decision would never see news
that broke over the weekend. The daily cron + in-agent gate is what closes that
gap, and the `target_date`/`data_date` split is what keeps every Sunday-eve write
landing on the correct Friday row.

---

## 5. How consumers resolve back to session date

The frontend calendar and `LiveSignalStrip` operate in `display_date` space.
Non-trading weekdays (exchange holidays) come from
`GET /v1/dashboard/non-trading-days?year=YYYY`, which also returns
`latest_trading_day` = the newest **released** session's `display_date`:
`MAX(display_date)` joined to `pl_session_release`
(`backend/app/api/api_v1/endpoints/dashboard.py`). A session is released by the
`cc-publish-session` job once its data is complete and its NotebookLM audio is
present — so the dashboard flips **atomically the same evening T** rather than
when the calendar reaches `display_date`. While `pl_session_release` is empty the
endpoint falls back to the legacy `MAX(display_date) WHERE display_date <= today`
(non-breaking). See [session-publish-gate.md](../../runbooks/session-publish-gate.md).
The `-1 day` offset the frontend used to apply (`getYesterdayISO`) has been
removed — the backend owns the full resolution.

Every dashboard endpoint runs the inbound `target_date` (a `display_date`)
through one resolver: **`_parse_and_validate_date`**
(`backend/app/api/api_v1/endpoints/dashboard.py:131`):

1. Parse `YYYY-MM-DD`.
2. **Primary path** — look up `pl_contract_data_daily.date WHERE display_date = parsed_date` (latest by `date`). If found, that `date` is the session date used for every other table query. This is the single `display_date → session_date` edge.
3. **Fallback** — `get_latest_trading_day(db, parsed_date)` for pre-migration rows where `display_date` was never populated (direct date query, calendar-based).
4. Errors: invalid format → 400; calendar lookup failure → 503. No silent default.

After resolving the session date, endpoints resolve the contract
(`_resolve_contract_for_request` → `resolve_contract_for_date`, which handles
cross-contract roll boundaries) and the algorithm version
(`_resolve_algo_for_date` → `get_algorithm_version_for_date`, row-existence based
so ensemble is served when its row exists for that session date). All of these
read tables keyed on **session date** — never `display_date`.

```
Frontend (display_date space)
   │  GET /dashboard/... ?target_date=<display_date>
   ▼
_parse_and_validate_date
   │  SELECT date FROM pl_contract_data_daily WHERE display_date = :d   (primary)
   │  └ fallback: get_latest_trading_day(:d)                            (pre-migration)
   ▼
session_date (= T)
   ├─► resolve_contract_for_date(session_date)   → contract_id  (roll-aware)
   ├─► get_algorithm_version_for_date(session_date) → legacy | ensemble
   └─► all pl_* queries keyed on date = session_date
```

---

## 6. Failure mode this prevents

Past P2b drift on this convention manifests as **empty dashboard sections the
morning after**: a Phase-B producer writes its row at `target_date` (the upcoming
session) instead of `data_date` (= T). The dashboard resolves `display_date → T`,
queries the other tables at `date = T`, finds nothing, and renders empty.

History: PR #15 (consumers), PR #16 (press/meteo producers), PR #17
(`ensemble_explainer` = thin wrapper), PR #35 (`ensemble_compute` migration).

**Rule of thumb when adding or editing a Phase-B agent:** derive the pair from
`resolve_phase_b_dates(args.session_date)` and write every `pl_*` row at
`data_date`. `target_date` is only for prompt text, filenames, and Sentry context.
If you find yourself re-deriving dates inline (calling `get_next_session_date` /
`get_previous_session_date` directly in a main) or writing a `pl_*` row at
`target_date`, stop — that is the bug.

---

## 7. Quick checklist

- New scraper that INSERTs into `pl_contract_data_daily`? It must stamp `display_date = get_next_trading_day(date)`. New scraper that only UPDATEs columns? Never touch `date`/`display_date`.
- New `pl_*` table? Key it on `date` = **session date** only. Do not add a second `display_date` column — there is exactly one in the system.
- New Phase-B agent? Expose `--session-date`, call `phase_b_should_skip(args.session_date, args.force)` then `resolve_phase_b_dates(args.session_date)`, write rows at `data_date`, frame prompts/filenames with `target_date`. Never re-derive the pair inline.
- New dashboard consumer? Route the inbound date through `_parse_and_validate_date`, then query everything by the resolved session date.
- All date math goes through `app/utils/trading_calendar.py` (`IFEU`) — never compute "next business day" by hand with `timedelta`. Weekends AND exchange holidays both matter.
