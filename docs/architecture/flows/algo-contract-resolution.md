# Algo + Contract Resolution Flow

> **Why this doc exists.** The path "user picks a date → which (contract, algorithm_version) rows do we read?" has caused **five** distinct contract-roll bugs (PRs #46, #47, #48, #51, #52). Every one shared the same root cause: **resolving by the *active* contract instead of the *front-month contract for the requested date*.** This doc makes the correct per-date resolution explicit and names the active-contract trap precisely so it stops recurring.
>
> Scope: read-path (dashboard API) + producer-path (pipeline jobs). Code lives in `backend/app/utils/contract_resolver.py` (async, dashboard), `backend/scripts/contract_resolver.py` (sync, jobs), `backend/app/api/api_v1/endpoints/dashboard.py` (orchestration), `backend/app/services/dashboard_service.py` (queries).

> **🔄 2026-07 UPDATE — the mechanisms below were CONSOLIDATED (principles unchanged):**
>
> 1. **Contract dimension (PR #73)**: the front-month is now resolved from the **canonical roll calendar** — `ref_contract.active_from`, single resolver `front_month_for_date` (`app/utils/front_month.py` async / `scripts/front_month.py` sync). This replaced the 5 divergent resolvers AND the liquidity(OI/volume)-based selection in `v_contract_data_chained` (the VIEW now JOINs the calendar). A 7th split-brain incident (2026-07-17: compute rolled to CAZ26 on liquidity while decisions stayed CAU26) motivated it. Roll = `poetry run roll-contract <NEW> --effective-date` which stamps `active_from`; `cc-roll-watchdog` (19:45 UTC) nudges via Sentry when a roll looks due.
> 2. **Algorithm-version dimension (PRs #75/#77)**: still resolved by **row existence per date**, and now explicitly: the resolver picks the newest ensemble version *that has a `pl_indicator_daily` row for the date* (`get_algorithm_version_for_date`). In practice there is **ONE continuous ensemble version (v1.0.0)** — shipping a config change as a new `pl_algorithm_version` splits the history and breaks YTD / trailing windows / explainer / brief (the collapsed v1.1.0 attempt). Config changes are versioned via **temporal config** (`pl_algorithm_config.effective_from` + `v_algorithm_config_current`) instead — see [PIPELINE_ENSEMBLE.md §4.1](../PIPELINE_ENSEMBLE.md).
>
> Sections below describing OI-based front-month selection or multi-resolver paths are historical context for the bug class; the calendar + row-existence rules above are the current truth.

---

## 0. The two keys every `pl_*` read needs

Every row in `pl_indicator_daily`, `pl_derived_indicators`, `pl_signal_component` is keyed on **three** dimensions:

```
(date, contract_id, algorithm_version_id)
```

- **`date`** = session date (immutable trading-truth). The dashboard receives a `display_date` from the frontend and must resolve it to `date` first (see §1).
- **`contract_id`** = which delivery month (CAN26, CAU26, …). **This is the dimension that the roll bugs all got wrong.**
- **`algorithm_version_id`** = `legacy` vs `ensemble_v1_softgate_wrapper`. Resolved by **row existence**, not by an `is_active` flag (see §3).

A correct read resolves all three **for the requested date** — never by grabbing "the current active contract" and pinning it across history.

---

## 1. Step 1 — display_date → session_date

`_parse_and_validate_date()` (`dashboard.py:131`). The frontend calendar shows `display_date = next_trading_day(session)`. Every `pl_*` table except `pl_contract_data_daily` is keyed on `date` (session). So before anything else:

```
parsed = parse(date_str)                       # user-facing display_date
session = SELECT date FROM pl_contract_data_daily
          WHERE display_date = :parsed
          ORDER BY date DESC LIMIT 1            # display_date → session_date
fallback: get_latest_trading_day(parsed)       # pre-migration rows w/o display_date
```

Output: a `session_date` used as `date` for all subsequent reads. The frontend stopped applying its own `-1 day` offset; the backend owns the full resolution.

---

## 2. Step 2 — session_date → contract_id (THE TRAP)

### 2.1 The trap

```
# WRONG — the bug that recurred 4 times
contract_id = await get_active_contract_id(db)   # ref_contract.is_active = TRUE
```

`is_active` reflects **today's** front-month. The moment a roll flips `is_active` from CAN26 to CAU26, **CAU26 has zero rows for any pre-roll session**. So if you key a historical read by the active contract:

- `pl_indicator_daily` lookup for the ensemble version → **miss** → silently falls back to legacy (§3).
- Position lookup → **null** → frontend renders MONITOR.
- Chart query filtered to active contract → **drops all pre-roll history** the instant the roll happens.

The dashboard looked broken the morning after every roll, even though the data was intact under the *old* contract_id.

### 2.2 The correct resolution (read-path)

`_resolve_contract_for_request()` (`dashboard.py:87`) → `resolve_contract_for_date()` (`contract_resolver.py`):

- **Specific date requested** → resolve the contract that was front-month **that day**, with a graded fallback:
  1. Active contract **if** it has a complete row (`conclusion IS NOT NULL`) for that date.
  2. **Any** contract with a complete row for that date (cross-contract fallback).
  3. Active contract with any row.
  4. **Any contract with market data, highest OI** = front-month heuristic.
- **No date (latest request)** → `get_active_contract_id()` is correct here (we genuinely want today's front-month).

`get_active_contract_id()` is **only** legitimate when there is no date, i.e. the "latest" request. Any path with a `target_date` must use the per-date resolver.

### 2.3 The durable fix — `v_contract_data_chained`

The per-date fallback is the safety net; the structural fix is the **chained view** (`n8i9j0k1l2m3`):

```sql
CREATE VIEW v_contract_data_chained AS
SELECT DISTINCT ON (date) date, display_date, contract_id, open, high, low,
       close, volume, oi, implied_volatility, stock_us, stock_eu_bags60kg, com_net_us
FROM pl_contract_data_daily
WHERE close IS NOT NULL
ORDER BY date ASC, COALESCE(oi,0) DESC, COALESCE(volume,0) DESC, contract_id ASC;
```

One row per date = whatever contract had the highest OI that day = front-month-by-OI. This is the **single source of front-month truth** shared by:
- `cc-ensemble-compute` (`market_history`, 600d GARCH lookback)
- `cc-compute-indicators` (front-month picker)
- the dashboard chart query (`get_chart_data`, PR #51)
- the YTD cross-contract query (`calculate_ytd_performance`)
- the ensemble wrapper trailing window (PR #46)

Because the view auto-switches at the true OI crossover, **past front-month decisions are roll-stable** — a roll needs no ensemble recompute. (Legacy still needs `--full` recompute because its rows are keyed per-contract, not via the view.)

---

## 3. Step 3 — algorithm_version: row-existence, not a flag

`_resolve_algo_for_date()` (`dashboard.py:107`) → `get_algorithm_version_for_date()` (`contract_resolver.py`):

```
preferred = ensemble_v1_softgate_wrapper
fallback  = legacy

if EXISTS (pl_indicator_daily WHERE date=:d AND version=preferred AND contract_id=:c):
    return (preferred_id, "ensemble")
else:
    return (fallback_id, "legacy")
```

Resolution is **by row existence for the (date, contract_id) pair**, not by `pl_algorithm_version.is_active`. Rationale:
- Ensemble only has rows from 2025-12-15 onward (frozen specialists, cutoff 2026-04-30 — backfilling earlier dates = look-ahead bias). So recent dates serve ensemble, older dates serve legacy, transparently — without a historical backfill.
- **This is why §2 matters so much**: the existence check is `contract_id`-scoped. Pass the *active* contract for a pre-roll date and the ensemble row check misses → you silently degrade a date that *does* have an ensemble decision down to legacy. PR #52 fixed exactly this: pre-roll sessions served legacy instead of ensemble because the algo check was keyed to the post-roll active contract.

The published ensemble `decision` mirrors `pl_orchestrator_decision.decision_wrapped` (post-Compass override) — the YTD scorer reads the same decision that shipped live.

---

## 4. End-to-end read flow (dashboard endpoint)

```
GET /v1/dashboard/{position-status|indicators-grid|recommendations|...}?target_date=YYYY-MM-DD
    │
    ├─ 1. _parse_and_validate_date(target_date)        display_date → session_date
    │
    ├─ 2. _resolve_contract_for_request(session_date)  → front-month contract FOR THAT DATE
    │        (resolve_contract_for_date; NOT get_active_contract_id when a date is given)
    │
    ├─ 3. _resolve_algo_for_date(session_date, contract_id)
    │        → get_algorithm_version_for_date: row-existence ensemble→legacy, contract-scoped
    │
    └─ 4. service query on (date=session_date, contract_id, algorithm_version_id)
             position / indicators / recommendations / macro-panel / positioning
```

Cross-roll aggregate reads (chart, YTD) **bypass single-contract resolution entirely** and read the chained view / `DISTINCT ON (date) ORDER BY oi DESC` so they span rolls with no gap.

---

## 5. Producer-path resolution (pipeline jobs)

Sync resolvers in `backend/scripts/contract_resolver.py`:

| Function | Used by | Semantics |
|---|---|---|
| `resolve_active(session)` / `resolve_active_code(session)` | ICE/CFTC/barchart scrapers, daily-analysis, ensemble-explainer, **live** ensemble-compute | `is_active=TRUE` from `ref_contract`. Correct because these run for *today*. |
| `resolve_by_code(session, code)` | Barchart scraper (`ACTIVE_CONTRACT` fallback) | Explicit code lookup. |
| `resolve_active_at_date(session, date)` | ensemble-compute **`--historical` backfill** | Front-month-by-OI on that date `(oi DESC, volume DESC, contract_id ASC)`. Matches R&D's training-set convention and the chained view's tiebreak. |

**Key asymmetry**: live jobs use `is_active` (they write *today's* row, where active == front-month by construction). Historical backfill must use `resolve_active_at_date` (the per-date front-month), exactly mirroring the read-path's per-date rule. Using `is_active` for a historical backfill would write the new contract's id onto a date where the old contract was front-month — the producer-side version of the same trap.

Daily-analysis has a transition fallback: `_read_technicals()` filters by active contract, and if `< 2` rows are found in the first days after a roll, falls back to a cross-contract read for continuity.

---

## 6. The four roll bugs — what broke and what fixed it

| # | PR / commit | Symptom | Root cause | Fix |
|---|---|---|---|---|
| 1 | **#46** `71be87d` | Wrapper reset to permissive NaN-bootstrap for ~1-2 weeks post-roll; blindly committed directional bets with no accuracy signal. | Wrapper trailing window (`running_acc`, cluster dispersion) keyed to the active contract → empty across the roll boundary. | `db_loader` recent-decisions/votes windows join **`v_contract_data_chained`** → wrapper continuity at the roll, **no warmup**. |
| 2 | **#47** `f4af2aa` | Each roll required a manual OHLCV+OI backfill (and that data is unobtainable — Barchart `/historical` is login-gated, Yahoo has no OI). | Scraper captured only the active (front) month, so the chained view had a gap until the new contract started getting scraped. | Scrape **front + next delivery month** daily (`BACK_MONTHS_TO_SCRAPE`) → the chained view auto-switches at the true crossover. Roll becomes a data-layer non-event. |
| 3 | **#48** `f7041ea` | Legacy `cc-compass-brief` crashed / produced empty briefs across the CAN26→CAU26 roll. | Brief read pinned to a single contract that had no rows spanning the roll boundary. | Brief survives rolls via cross-contract continuity. |
| 4 | **#51** `71fef9e` | Price chart showed only post-roll sessions (all pre-roll history vanished the moment the new contract went active). The old row-count fallback never fired for short windows (5-day ticker) and double-counted dates once the back-month scrape added a 2nd contract/date. | Chart query filtered by active contract; fragile row-count fallback. | Chart reads **`v_contract_data_chained`** (one front-month row per date), derived indicators join on the front-month contract per date. |
| 5 | **#52** `1e1f356` | Pre-roll sessions served **legacy** instead of **ensemble** decisions (all June sessions showed MONITOR / "Powered by Legacy"). | Date-aware algo lookup (§3) keyed to the post-roll active contract → ensemble row-existence check missed → silent legacy fallback. | `_resolve_contract_for_request` resolves the per-date front-month **before** the algo check (all 7 dashboard endpoints), so the ensemble existence test runs against the correct contract. |

**The common thread**: all five = "active contract" used where "front-month contract for the requested date" was needed.

---

## 7. Checklist — before touching any `pl_*` read or roll-adjacent code

1. **Is a `target_date` involved?** If yes, you MUST resolve contract per-date (`resolve_contract_for_date` / `resolve_active_at_date`). `get_active_contract_id` / `resolve_active` is for "latest"/"today" only.
2. **Is this an aggregate spanning multiple dates** (chart, YTD, GARCH lookback, wrapper window)? Read **`v_contract_data_chained`** (or `DISTINCT ON (date) ORDER BY oi DESC`), never a single-contract filter.
3. **Algo version**: resolve by **row existence** for the resolved `(date, contract_id)`, never by `is_active`. Verify the contract is resolved *before* the algo existence check.
4. **Producer backfill** over historical dates: per-date front-month (`resolve_active_at_date`), not `is_active`.
5. **After a roll** (Mode A, forward-only): no ensemble recompute needed (chained view is roll-stable); legacy needs `--full` recompute; never re-run past briefs/podcasts (frozen editions).
