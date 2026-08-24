# Contract Roll Procedure — Operational Runbook

> Rewritten 2026-08-24 for the **canonical roll calendar**. The previous version
> of this file described a model that migration `d5e6f7a8b9c0` (PR #73,
> 2026-07-22) deleted: it told you the chained view auto-switches at the OI
> crossover and that a roll is "just flip `is_active`". Both are now false, and
> following them silently freezes the served track. PR #73 shipped with **no**
> doc changes; the 2026-08-19 sweep (PR #104) only renamed ensemble→regime in
> this file and left the stale model intact.

## When to use this runbook

Run this when the active cocoa contract needs to roll to the next delivery month, typically every ~2 months as Open Interest (OI) migrates to the new front-month.

**Delivery months for ICE Europe Cocoa #7**: `H` (Mar), `K` (May), `N` (Jul), `U` (Sep), `Z` (Dec). Codes are `CA<letter><yy>`; `Z` rolls to `H` of the next year. Example: `CAU26 → CAZ26` (Sep → Dec 2026).

**Trigger**: `cc-roll-watchdog` (cron `45 19 * * 1-5`) fires a Sentry warning + exit 1 when the *liquidity* front-month (leads on **both** OI and volume) has led the *calendar* front-month for ≥ 3 consecutive sessions. That nudge is the signal — liquidity no longer decides anything by itself.

---

## The model (read this first — it changed)

**`ref_contract.active_from` is the roll calendar, and it is the only thing that decides which contract is front-month.**

- Front-month for date `D` = the contract with the greatest `active_from <= D`.
  One rule, three implementations that agree: [`backend/app/utils/front_month.py:30-38`](../../backend/app/utils/front_month.py#L30-L38) (async), [`backend/scripts/front_month.py:22-30`](../../backend/scripts/front_month.py#L22-L30) (sync), and the `v_contract_data_chained` VIEW.
- `v_contract_data_chained` is a **calendar INNER JOIN**, not a liquidity heuristic — [`d5e6f7a8b9c0:97-117`](../../backend/alembic/versions/d5e6f7a8b9c0_contract_roll_calendar_active_from.py). The old OI-AND-volume rule survives only as `_OLD_VIEW` for `downgrade()`.
- ⚠️ **INNER JOIN means: a date whose calendar front-month has no OHLCV row vanishes from the series entirely** — no error, no log, every job exits 0. This is the single most dangerous property of the model and the reason for the timing rule below.
- `is_active` is a **derived cache**, not the source of truth. It still drives the barchart scraper, the intraday monitor, the press-review agent, and the dashboard's no-date fallback — so it must stay in sync, but it does *not* move the front-month.
- [`poetry run roll-contract`](../../backend/scripts/roll_contract.py) is the **only** writer of `active_from` (`:119-135`) and the only path carrying the desync post-condition (`:143-150`).

**Consequence — the view follows the stamp, it never leads it.** There is nothing to "wait for" before rolling. `backend/tests/test_front_month_calendar.py:125-149` (`test_liquidity_domination_does_not_roll_without_calendar`) pins exactly this: total OI+volume domination does **not** roll anything until `active_from` is stamped.

---

## ⚠️ Timing is load-bearing

`roll-contract` flips `is_active` **immediately** but stamps `active_from` to the **next trading session** ([`roll_contract.py:59-63,119`](../../backend/scripts/roll_contract.py#L59-L63)). Those two clocks are deliberately offset by ≥1 session — and that offset is a trap if you roll at the wrong hour.

The barchart scraper resolves its scrape set from `is_active` ([`barchart_scraper/main.py:66-78`](../../backend/scripts/barchart_scraper/main.py#L66-L78)) and captures `{front, next(front)}` only (`BACK_MONTHS_TO_SCRAPE = 1`).

So if you roll **during the trading day, before the 19:00 UTC scrape**:
- tonight's scrape writes `{NEW, next(NEW)}` and **stops writing the OLD contract**;
- but tonight's session date still resolves to the OLD contract on the calendar (`active_from` = tomorrow);
- → the INNER JOIN drops tonight's date. **A permanent, silent hole in the chained series.**

**Roll in one of these two windows only:**

| Window | Why it is safe |
|---|---|
| **On a weekend / non-trading day** (safest) | `active_from` = next Monday. Monday's scrape writes the NEW contract, and Monday's calendar front-month *is* the NEW contract. They agree. Friday and earlier already have OLD-contract rows. |
| **After 19:10 UTC on a trading day** | Today's OLD-contract row is already written by `cc-barchart-scraper` (19:00) — do it before `cc-compute-indicators` (19:15) if you can. `active_from` = tomorrow; tomorrow's scrape writes the NEW contract. They agree. |

Rolling during the London session (09:30–16:55) additionally maximises the `cc-intraday-monitor` noise described in **Expected roll-day noise**.

---

## Pre-requisites

- `gcloud` authenticated (`gcloud auth login` — short-lived token, expect to re-auth). Project `cacaooo`.
- Prod DB via the ephemeral bastion: `./.local/db-prod.sh up` → `exec` → `down`. The roll is an explicit, authorized value-`UPDATE`, permitted by [migrations-prod-via-main-only](../../.claude/rules/migrations-prod-via-main-only.md) (that rule gates DDL, not DML on explicit go).
- The new contract must already exist in `ref_contract` — the scraper auto-registers the back-month via `ensure_contract()`, so it normally does. `roll-contract` fails loud otherwise.

---

## Pre-roll checks

Run all of these. Check 3 is the one that matters most.

```sql
-- 1. Calendar state. Expect the incumbent is_active=t with an active_from,
--    and the target with active_from IS NULL.
--    If the target ALREADY has an active_from → STOP, someone half-rolled.
SELECT code, is_active, active_from, contract_month, expiry_date
FROM ref_contract
WHERE active_from IS NOT NULL OR active_from IS NULL
ORDER BY active_from DESC NULLS LAST LIMIT 8;

-- 2. Exactly one active row (no unique constraint enforces this).
SELECT count(*) FROM ref_contract WHERE is_active;   -- must be 1

-- 3. The chain has NO holes. MUST return 0, before AND after the roll.
SELECT count(*) FROM pl_contract_data_daily d
WHERE d.close IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM v_contract_data_chained v WHERE v.date = d.date);

-- 4. Chain head advances and still names the incumbent.
SELECT v.date, c.code FROM v_contract_data_chained v
JOIN ref_contract c ON c.id = v.contract_id
ORDER BY v.date DESC LIMIT 5;

-- 5. The new contract has been scraped continuously — this is what makes the
--    roll a non-event. Expect its row count to match the incumbent's.
SELECT c.code, count(*), min(d.date), max(d.date)
FROM pl_contract_data_daily d JOIN ref_contract c ON c.id = d.contract_id
WHERE d.date >= CURRENT_DATE - 90 GROUP BY c.code ORDER BY 1;

-- 6. Any stale derived rows on the target from a pre-calendar premature-OI roll.
--    They are inert ONLY while the target's active_from is GREATER than their
--    max date. Never backdate --effective-date below that.
SELECT c.code, count(*), min(d.date), max(d.date)
FROM pl_derived_indicators d JOIN ref_contract c ON c.id = d.contract_id
WHERE c.code = '<TARGET>' GROUP BY c.code;

-- 7. The view really is the calendar version.
SELECT pg_get_viewdef('v_contract_data_chained'::regclass, true);
-- must contain "active_from", must NOT contain "DISTINCT ON" or "max_oi".
```

```bash
# 8. Confirm the watchdog has been nudging.
gcloud logging read \
  'resource.labels.job_name="cc-roll-watchdog" AND textPayload:"Roll due"' \
  --project=cacaooo --limit=5 --freshness=10d
```

---

## The roll

```bash
# 0. Confirm today's scrape landed (check 4 shows today's session). See Timing.

./.local/db-prod.sh up
cd backend
export PROD_URL="postgresql+psycopg2://cc_app:<pwd>@127.0.0.1:5434/commodities_compass"

# 1. Dry run — READ the active_from it prints.
DATABASE_SYNC_URL="$PROD_URL" poetry run roll-contract <TARGET> --dry-run

# 2. Roll.
DATABASE_SYNC_URL="$PROD_URL" poetry run roll-contract <TARGET>
```

Expected log lines: `Deactivated: <OLD>` · `Set active_from=<next session> on <TARGET>` · `Activated: <TARGET>` · `Contract roll complete.`

- **`Contract <TARGET> is already active and holds the calendar leading edge`** → genuine no-op, nothing to do.
- **`has is_active=true but does NOT hold the calendar leading edge … Repairing`** → you were in the half-rolled state (someone flipped `is_active` by raw SQL). The CLI repairs it by stamping the calendar. Re-run the post-roll checks and confirm no session was lost while the calendar was wrong.
- **If it raises `RuntimeError: … would desync the calendar`** → a later contract holds a greater `active_from`. Do not force. Investigate.
- Do not pass `--effective-date` unless you have a specific reason. If you do, it must be **≥ the max date of any stale derived rows** (check 6) and **≤ the first session the target will actually be scraped under the new flag**. The post-condition does **not** bound it against the future — a typo like `2027-08-25` passes silently and freezes everything.

**Nothing else is required for the served decision.** Regime self-computes its features from `v_contract_data_chained` and never reads `pl_derived_indicators` ([`regime_shadow/feature_engine.py`](../../backend/scripts/regime_shadow/feature_engine.py)). A gauges/pivots recompute is optional:

```bash
gcloud run jobs execute cc-compute-indicators --region=europe-west9 --project=cacaooo
```

Then `./.local/db-prod.sh down`.

---

## Post-roll verification

**Immediately (same session):**

```sql
-- A. The target must hold BOTH is_active=true AND the greatest active_from.
SELECT code, is_active, active_from FROM ref_contract
ORDER BY active_from DESC NULLS LAST LIMIT 5;

-- B. No hole introduced. MUST still be 0 (same query as pre-roll check 3).

-- C. The chain still ends on today's session, still on the OLD contract —
--    this is CORRECT. The calendar moves tomorrow.
SELECT v.date, c.code FROM v_contract_data_chained v
JOIN ref_contract c ON c.id = v.contract_id ORDER BY v.date DESC LIMIT 3;
```

**Next morning (T+1), after the evening pipeline — run these three mornings running:**

```sql
-- D. The chain advanced AND switched. Newest row = T+1 on the NEW contract.
SELECT v.date, c.code FROM v_contract_data_chained v
JOIN ref_contract c ON c.id = v.contract_id ORDER BY v.date DESC LIMIT 3;

-- E. The served track is on the NEW session, not re-chewing an old one.
--    (cc-regime-shadow runs with no --session-date and takes the tail of the
--    chain — if the chain froze it silently recomputes yesterday. See Known gaps.)
SELECT max(date) AS regime_max FROM pl_regime_shadow;
SELECT max(date) AS judge_max  FROM pl_judge_shadow;

-- F. Adapter row on the right contract, both languages.
SELECT i.date, c.code, av.name, i.language, i.decision
FROM pl_indicator_daily i
JOIN ref_contract c ON c.id = i.contract_id
JOIN pl_algorithm_version av ON av.id = i.algorithm_version_id
WHERE i.date >= CURRENT_DATE - 3 ORDER BY i.date DESC, i.language;

-- G. Dashboard actually flipped.
SELECT max(session_date) FROM pl_session_release;

-- H. Gauges written for the new session.
SELECT max(date) FROM pl_dashboard_gauge;
```

```bash
# I. The watchdog must go silent (exit 0) once the target has an active_from.
gcloud logging read 'resource.labels.job_name="cc-roll-watchdog"' \
  --project=cacaooo --limit=3 --freshness=2d
# NB: the watchdog is structurally blind to an EARLY roll — silence is not
# proof the roll date was right (roll_watchdog/main.py:156-168).
```

---

## Expected roll-day noise (do not misread as failure)

| What | Why | Duration |
|---|---|---|
| `cc-intraday-monitor` fails every tick with `LevelsMissingError`, ~30 Sentry events, zero S1/R1 alerts | It resolves *today's* contract but reads *yesterday's* `pl_derived_indicators` row, which only ever holds that date's calendar front-month ([`intraday_monitor/main.py:89-94`](../../backend/scripts/intraday_monitor/main.py#L89-L94)) | First post-roll session only; self-heals at T+1. The Sentry cron card stays **green** (exit 1 ≠ exception) |
| Dashboard gauges show an RSI/ATR/return artefact | Roll-boundary neutralization is **off** in the shared compute path — `mark_roll_boundaries` ([`runner.py:200`](../../backend/app/engine/runner.py#L200)) has exactly one caller, regime's feature engine. `pl_derived_indicators.is_roll_boundary` is always `False` | ~14-25 sessions (Wilder recursion). **Regime is immune, the gauges are not — expect them to visibly disagree** |
| Judge prose references a phantom price move | The L3 judge reads the raw spliced chain with no back-adjustment | Up to 3 sessions. Escape hatch: `regime-shadow-compute --no-judge` |
| One contaminated YTD / 5-day hit-rate point | The pre-roll decision is scored against the calendar spread, not a market move | One point |

---

## Rollback / repair

**Do not flip `is_active` back by hand.** That leaves `active_from` stamped on the new contract: the calendar stays rolled while the scrapers revert — the freeze in reverse.

```bash
./.local/db-prod.sh up && cd backend
DATABASE_SYNC_URL="$PROD_URL" \
  poetry run roll-contract <PREVIOUS> --effective-date <date GREATER than the target's active_from>
```

`--effective-date` is **mandatory** on a rollback: without it the CLI keeps the previous contract's old stamp, fails the post-condition at `:143-150`, and exits 1.

**Half-rolled state (`is_active` flipped by raw SQL, calendar unstamped)** — since 2026-08-24 `poetry run roll-contract <TARGET>` **repairs this itself**; it no longer early-returns. Run it and read the `Repairing` log line.

**If the CLI still refuses** (e.g. a stale `active_from` that is neither leading nor re-stampable), the remaining path, on explicit authorization, is bastion DML (a value `UPDATE`, not DDL):

```sql
BEGIN;
UPDATE ref_contract SET active_from = NULL, is_active = false WHERE code = '<TARGET>';
UPDATE ref_contract SET is_active = true WHERE code = '<PREVIOUS>';
SELECT code, is_active, active_from FROM ref_contract
ORDER BY active_from DESC NULLS LAST LIMIT 5;   -- verify BEFORE commit
COMMIT;
```

Then re-run checks B, C, D. **A session lost from the chain is not auto-repaired** — `_filter_new_rows` ([`runner.py:379-387`](../../backend/app/engine/runner.py#L379-L387)) only moves forward. Re-run `compute-indicators --all-contracts --full` and, if needed, `regime-shadow-compute --session-date <D> --force` for the affected dates.

---

## Rehearsal (recommended — a mis-stamped `active_from` has no CLI undo)

Rehearse **only** against a prod-synced local DB. A fresh `alembic upgrade head` leaves `active_from` NULL everywhere: the seed in `d5e6f7a8b9c0:63-95` reads `pl_indicator_daily` rows from the now-deleted `legacy`/`ensemble` algorithms and has no `regime` branch, so on a fresh DB it silently stamps nothing.

```bash
./.local/db-prod.sh up
cd backend && poetry run python scripts/sync_from_gcp.py   # see docs/runbooks/db-sync-from-gcp.md
./../.local/db-prod.sh down

export LOCAL="postgresql+psycopg2://postgres:password@localhost:5433/commodities_compass"
DATABASE_SYNC_URL=$LOCAL poetry run roll-contract <TARGET> --dry-run
DATABASE_SYNC_URL=$LOCAL poetry run roll-contract <TARGET>
# then run pre-roll check 3 against localhost:5433 — must stay 0
```

⚠️ `roll-contract` has **no `--target` guard**. It reads `DATABASE_SYNC_URL` — pass it explicitly on every invocation, never rely on `.env`.

---

## Guards in place (added 2026-08-24, pre-roll)

Three defects found by the pre-roll audit are now closed — all fail-loud, all tested:

1. **Chain-gap guard.** `assert_chain_has_no_gaps()` ([`regime_shadow/feature_engine.py`](../../backend/scripts/regime_shadow/feature_engine.py)) runs on every `cc-regime-shadow` execution: if any scraped session inside the chain's span is absent from `v_contract_data_chained` (the INNER-JOIN hole a mid-session roll creates), it raises `RegimeChainGapError` instead of computing over a holed series.
2. **Stale-tail guard.** `_resolve_target_dates()` ([`regime_shadow/main.py`](../../backend/scripts/regime_shadow/main.py)) now receives the Phase-B `data_date` and raises `RegimeChainStaleError` if the chain's newest session isn't the one the run must publish. Backfills and explicit `--session-date` bypass it. **Side effect worth knowing: a failed barchart scrape now fails `cc-regime-shadow` too (exit 1) instead of silently republishing yesterday.** That is intended — see [pipeline-error-handling](../../.claude/rules/pipeline-error-handling.md).
3. **Half-rolled repair + future-date bound.** `roll-contract` only short-circuits when `is_active` **and** the calendar agree; on an `is_active`-only state it repairs by stamping the calendar. And `--effective-date` is refused beyond `MAX_EFFECTIVE_DATE_LOOKAHEAD_DAYS` (31) — the post-condition alone accepted any future date, so a year typo used to pass silently.

Tests: `tests/test_regime_chain_integrity.py` (new), `tests/test_roll_contract.py::TestRollContractMain` (new — `main()` previously had zero coverage).

## Known gaps (still open)

- **Two "roll-safe" tests build the deleted OI-DESC view** (`test_chart_data_roll.py:27-38`, `test_data_export.py:37-45`). `DISTINCT ON` cannot reproduce the INNER-JOIN date-drop → green CI is not roll evidence for the chart or the CSV export. Verify those two surfaces by hand after a roll.
- **The calendar VIEW DDL is hand-copied into tests** (three places now) instead of being read from one source — it can drift from migration `d5e6f7a8b9c0` without CI noticing.
- **Roll-boundary neutralization is still off in the shared compute path** (see *Expected roll-day noise*). Enabling it requires a full historical recompute of `pl_derived_indicators` — a deliberate post-roll decision, not a roll-day one.
- **`cc-intraday-monitor` keys today's contract against yesterday's levels row** — the correct call is `front_month_for_date(session, levels_date)`. One failed session per roll.

---

## Data-sourcing reality (why forward-only is the only honest option)

Backfilling a new contract's **historical** OHLCV+OI is not possible with the sources we have: Barchart `/overview` is current-day only, `/historical-prices` is login-gated, Yahoo has no OI and no ICE *London* contract. Reading OHLC off a chart is ±15-20 GBP and `pl_contract_data_daily` has no "estimated" flag. **Do not fabricate or estimate data into that table.** Roll forward-only; sessions computed on the old contract while liquidity had already migrated are an honest blemish, not something to rewrite.

This is exactly why the back-month is scraped daily — so there is never a historical gap to fill.

---

## Related files

- Canonical resolver: [`app/utils/front_month.py`](../../backend/app/utils/front_month.py) (async) · [`scripts/front_month.py`](../../backend/scripts/front_month.py) (sync)
- Chained VIEW + calendar seed: Alembic [`d5e6f7a8b9c0`](../../backend/alembic/versions/d5e6f7a8b9c0_contract_roll_calendar_active_from.py)
- Roll CLI (only writer of `active_from`): [`scripts/roll_contract.py`](../../backend/scripts/roll_contract.py)
- Watchdog (liquidity → nudge): [`scripts/roll_watchdog/main.py`](../../backend/scripts/roll_watchdog/main.py)
- Multi-contract scrape: [`scripts/barchart_scraper/main.py`](../../backend/scripts/barchart_scraper/main.py) · `config.py` (`BACK_MONTHS_TO_SCRAPE`)
- Cycle + auto-register: [`scripts/contract_resolver.py`](../../backend/scripts/contract_resolver.py) (`next_contract_code`, `ensure_contract`)
- Design spec: `docs/user-stories/P1-contract-roll-canonical-frontmonth.md` (gitignored, on disk)
- Prod DB access: `.local/db-prod.sh`
