# Flow — Contract Roll

> Architecture flow for rolling the active cocoa contract to the next ICE Europe Cocoa #7 delivery month.
> This is the **how-it-works** companion to the ops runbook ([docs/runbooks/contract-roll-procedure.md](../../runbooks/contract-roll-procedure.md)).
> Read this to understand *why* a roll is (now) a non-event and *where it can still bite you*.

---

## TL;DR

A roll moves the front-month from one delivery code (e.g. `CAN26`) to the next (`CAU26`) as Open Interest (OI) migrates. There are **two layers**:

- **Data layer** — already continuous. The barchart scraper captures front **+ next** delivery month daily, and `v_contract_data_chained` (front-month-by-OI) auto-switches at the true OI crossover. The engine, the ensemble, and the wrapper trailing window all read the chained view, so **no backfill, no recompute, no warmup** is needed at a roll.
- **Label layer** — a single manual flip of `ref_contract.is_active`. This relabels the dashboard headline and repoints the legacy `cc-daily-analysis` track. It is the *only* manual step in the happy-path roll.

The chained view de-couples "which contract is the truth on date D" (OI-driven, automatic) from "which contract does the org call active" (`is_active`, manual). The footguns below all live at the seam between those two.

---

## The cocoa delivery cycle

Codes are `CA<letter><yy>`. Only five months trade:

| Letter | Month | Number |
|--------|-------|--------|
| H | March | 03 |
| K | May | 05 |
| N | July | 07 |
| U | September | 09 |
| Z | December | 12 |

`Z` rolls to `H` of the next year. The cycle and `next_contract_code()` live in [`backend/scripts/contract_resolver.py`](../../../backend/scripts/contract_resolver.py).

---

## The two resolution conventions (know which one applies)

Three different "what's the current contract" answers coexist by design. Mixing them up is the root of most roll bugs.

| Convention | Function | Used by | Roll behavior |
|------------|----------|---------|---------------|
| **`is_active` flag** | `resolve_active` / `resolve_active_code` | barchart (front), ICE stocks, CFTC, barchart-stocks-EU scrapers; live `cc-ensemble-compute`; legacy `cc-daily-analysis`; dashboard headline | Manual — flips only when you run `roll-contract` |
| **Front-month-by-OI** | `v_contract_data_chained` VIEW (`DISTINCT ON (date) ORDER BY oi DESC`) | engine `--all-contracts`, ensemble `market_history`, wrapper trailing window | Automatic — switches at the true OI crossover, per date |
| **Historical front-month-by-OI** | `resolve_active_at_date` / dashboard `resolve_contract_for_date` | ensemble `--historical` backfill; dashboard reads for past dates | Per-date, deterministic; spans rolls seamlessly |

> ⚠️ **FOOTGUN — `is_active` ≠ front-month-by-OI during the crossover window.** For the ~5-10 sessions where OI is migrating, the chained view may already serve the new contract while `is_active` still points at the old one (or vice-versa). This is *intentional* — data follows OI, the label follows a human. Don't "fix" the divergence; it self-resolves when you flip the flag. But do not assume the two agree on any given day around a roll.

---

## Happy path — Mode A (non-event roll)

This is the default now that multi-contract scrape is live.

```
                       ┌──────────────────────────────────────────────┐
  Daily (automatic)    │ cc-barchart-scraper                           │
                       │  resolve_active → front code (CAN26)          │
                       │  next_contract_code → back code (CAU26)       │
                       │  ensure_contract(CAU26)  ← auto-registers      │
                       │   inactive row in ref_contract                │
                       │  scrape front (fail-loud) + back (best-effort)│
                       └───────────────┬──────────────────────────────┘
                                       ▼
                       pl_contract_data_daily  (BOTH contracts, every day)
                                       │
                                       ▼
                       v_contract_data_chained  (DISTINCT ON date, OI desc)
                          → auto-switches to CAU26 at the OI crossover
                                       │
                 ┌─────────────────────┼──────────────────────────────┐
                 ▼                     ▼                              ▼
   cc-compute-indicators      cc-ensemble-compute           wrapper trailing window
   (--all-contracts reads     (market_history reads          (running_acc / dispersion
    chained series)            chained series)                read chained series → no reset)

  ── MANUAL (once, at your chosen crossover point) ──────────────────────
                       poetry run roll-contract CAU26
                          deactivate all is_active → activate CAU26
                                       │
                                       ▼
              dashboard headline relabels + legacy track repoints
```

Steps:

1. **Confirm the chained view already serves the new contract** (OI has crossed):
   ```sql
   SELECT date, contract_id FROM v_contract_data_chained ORDER BY date DESC LIMIT 5;
   ```
2. **Flip the flag** — `poetry run roll-contract CAU26` (or the guarded bastion DML in the runbook).
3. **Verify exactly one active contract**:
   ```sql
   SELECT code, is_active FROM ref_contract WHERE is_active;
   ```
4. **Done.** No backfill. No recompute. No wrapper warmup.

---

## Why it's a non-event (the load-bearing mechanisms)

### 1. Multi-contract scrape pre-populates the back-month

`cc-barchart-scraper` resolves the active front-month, then loops `BACK_MONTHS_TO_SCRAPE` (currently `1`) calling `next_contract_code()` + `ensure_contract()` to auto-register and scrape the next delivery month every day. So both contracts have daily rows *before* the crossover — there is never a historical gap to backfill. See [`backend/scripts/barchart_scraper/main.py`](../../../backend/scripts/barchart_scraper/main.py) (Step 1-3).

> ⚠️ **FOOTGUN — back-month is best-effort, front-month is fail-loud.** An illiquid back-month can fail validation (e.g. zero volume) and gets skipped with a Sentry warning — *no row that run*. The front-month failure re-raises. If you roll *before* the back-month has accumulated enough liquid sessions in the chained view, you reintroduce the gap that Mode A was designed to eliminate. Check the chained view actually spans the crossover before flipping.

### 2. The chained view is the single source of market truth

`v_contract_data_chained` is `SELECT DISTINCT ON (date) ... ORDER BY date ASC, COALESCE(oi,0) DESC, COALESCE(volume,0) DESC, contract_id ASC` over `pl_contract_data_daily WHERE close IS NOT NULL`. One row per date = the most-liquid contract that day. Defined in Alembic `n8i9j0k1l2m3`, recreated in `r2m3n4o5p6q7`.

Consequences:
- Engine `--all-contracts`, ensemble `market_history`, and GARCH lookbacks all read a **continuous** front-month series across the roll boundary.
- A transient duplicate (old + new contract both have a row for the same date during the crossover) is **de-duped** by the view — the stale non-front-month row is dropped.

### 3. The wrapper trailing window chains across rolls (PR #46)

The Compass wrapper's `running_acc` / cluster-dispersion detectors read trailing `pl_orchestrator_decision` rows via `_RECENT_DECISIONS_SELECT` / `_RECENT_VOTES_WINDOWED_SELECT`, which **join `v_contract_data_chained`** (`db_loader.py:184`). This gives exactly one row per date → a continuous trailing window across the roll.

> ⚠️ **FOOTGUN — without the chained join, a roll resets the wrapper to NaN-bootstrap for ~1-2 weeks.** In that state the wrapper blindly commits directional bets with no accuracy signal (it can't veto on dispersion because `running_acc_5d` is undefined). PR #46 is the durable fix that makes **forward-only rolls safe**. If you ever revert to a single-`contract_id` filter on these windows, you re-open this hole.

> ⚠️ **FOOTGUN — `contract_id` is still in the signature but ignored.** `load_recent_orchestrator_decisions` keeps `contract_id` for ABI/parity but does **not** filter on it (the VIEW already picks one contract per date). Don't "restore" the filter thinking it's a missing guard — that breaks roll continuity.

### 4. Model artifacts are commodity-agnostic

`pl_model_artifact` (38 BYTEA rows) is keyed to the algorithm version, not the contract. **No re-bootstrap** on a roll.

---

## Fallback path — Mode B (manual backfill roll)

Only needed if the back-month was **not** being scraped (pre-multi-contract era, or a data gap). Then the chained view has a hole across the crossover and you must manually insert ~5-10 sessions of the new contract's OHLCV+OI into `pl_contract_data_daily`, flip the flag, then `cc-compute-indicators --all-contracts --all-versions --full`.

> ⚠️ **FOOTGUN — sourcing historical OHLCV+OI is the real blocker, and there is no honest source.** Barchart `/overview` is current-day only; `/historical-prices` is login-gated; Yahoo has **no OI** and no ICE *London* contract (`CC=F` is ICE US). Reading OHLC off a candle chart is ±15-20 GBP and `pl_contract_data_daily` has no "estimated" flag. **Do not fabricate or estimate data into that table.** If you can't get real data, roll forward-only and let the dashboard cross-contract fallback cover the historical days. This is exactly why Mode A exists.

> ⚠️ **FOOTGUN — `--full` recompute touches legacy/derived, NOT the ensemble.** `cc-compute-indicators --full` re-upserts legacy + shadow-legacy rows (front-month resolution may pick a different contract for boundary dates). The ensemble is a separate job. If you want past *ensemble* decisions recomputed on the true front-month, that's the optional B4 `ensemble-compute --historical` step — and it has its own footguns below.

---

## Optional — historical ensemble rewrite (Mode B4)

Only if you want crossover-day *ensemble* decisions recomputed on the true front-month, **and** the window is ≤ ~7 sessions, **and** you have real OHLCV+OI:

```bash
# chronological, oldest first; --historical resolves front-month-by-OI per date
poetry run ensemble-compute --date <D> --historical
poetry run ensemble-explainer --target-date <D>   # DB narrative only (~$0.13/day)
```

> ⚠️ **FOOTGUN — `--historical` uses `resolve_active_at_date` (OI), live runs use `resolve_active` (flag).** The live `cc-ensemble-compute` resolves the active contract from `ref_contract.is_active`; the backfill resolves front-month-by-OI per date. These can disagree on roll-boundary dates. That's correct (backfill wants per-date truth) but it means a backfill can write a *different* contract's decision than the live run would have.

> ⚠️ **FOOTGUN — never regenerate past briefs / NotebookLM podcasts.** `cc-compass-brief-ensemble` outputs and the NotebookLM audio for past days are **frozen published editions**. The explainer rewrite is DB-only and must not touch Drive. Re-running brief jobs for historical dates rewrites history users already consumed.

> ⚠️ **FOOTGUN — if the crossover exceeds the ~7-session cap or you lack real data, do NOT rewrite.** Roll forward-only. The historical days stay on the old contract (covered by the dashboard fallback) — an honest blemish, not fabricated data. Per the never-hide-bugs / immutability rules: don't delete produced signals, don't invent inputs.

---

## Dashboard cross-contract fallback (why past dates never gap)

After a roll, historical (pre-roll) dates would show empty gauges if dashboard queries filtered strictly on the active contract. `resolve_contract_for_date()` in [`backend/app/utils/contract_resolver.py`](../../../backend/app/utils/contract_resolver.py) resolves the best contract per date with priority:

1. Active contract with a **complete** `pl_indicator_daily` row (`conclusion IS NOT NULL`)
2. **Any** contract with a complete row for that date
3. Active contract with **any** row
4. Any contract with market data (**highest OI** = front-month heuristic)

YTD performance uses a cross-contract `DISTINCT ON (date) ORDER BY oi DESC` to span rolls. Transparent to the user — no gaps across roll boundaries.

---

## Cross-cutting footguns

- ⚠️ **`roll-contract` requires the new code to already exist in `ref_contract`.** Multi-contract scrape auto-registers it (`ensure_contract`, inactive). If the back-month was never scraped, `roll-contract CAU26` fails loud ("Contract CAU26 not found … Add it first").
- ⚠️ **`is_active` must always have exactly one row.** `roll-contract` deactivates *all* active rows then activates the target in one transaction. If you do it by hand in bastion, use the guarded `DO $$ … RAISE EXCEPTION … END $$;` block from the runbook so you never land on zero (or two) active contracts.
- ⚠️ **The bastion flip is an authorized DML, not a DDL.** Per [migrations-prod-via-main-only](../../../.claude/rules/migrations-prod-via-main-only.md), a value `UPDATE` in bastion on explicit go is allowed — but never run `alembic upgrade head` or any DDL against prod from a feature branch. The roll touches data, not schema.
- ⚠️ **`expiry_date` on auto-registered contracts is NULL by design.** The chained view and all front-month logic key on **OI, not expiry**. Don't fabricate an expiry to "complete" the row.
- ⚠️ **Scrapers that filter by `is_active` (ICE stocks, CFTC) lag the data layer until you flip.** They write `STOCK US` / `COM NET US` onto the *flagged* active contract's row. If the chained view has already moved to the new contract but you haven't flipped, these fundamentals attach to the old contract's rows for a few sessions. Flip promptly once the crossover is confirmed.

---

## Post-roll verification checklist

```sql
-- 1. Exactly one active contract = the new code
SELECT code, is_active FROM ref_contract WHERE is_active;

-- 2. Chained view serves the new contract for recent dates
SELECT date, contract_id FROM v_contract_data_chained ORDER BY date DESC LIMIT 5;

-- 3. No date gap in the chained series across the crossover
SELECT date FROM v_contract_data_chained ORDER BY date DESC LIMIT 20;
```

Then watch the next nightly pipeline: front-month scrape, `cc-compute-indicators`, `cc-ensemble-compute` should all produce rows on the new contract with no warmup. Confirm the wrapper's `running_acc_5d` is non-NaN in `pl_orchestrator_decision` (continuity held).

---

## Related code & docs

- Ops runbook (step-by-step, Mode A/B, rollback, worked example): [docs/runbooks/contract-roll-procedure.md](../../runbooks/contract-roll-procedure.md)
- Cycle + auto-register: [`backend/scripts/contract_resolver.py`](../../../backend/scripts/contract_resolver.py) (`next_contract_code`, `contract_month_for`, `ensure_contract`, `resolve_active_at_date`)
- Roll CLI: [`backend/scripts/roll_contract.py`](../../../backend/scripts/roll_contract.py)
- Multi-contract scrape: [`backend/scripts/barchart_scraper/main.py`](../../../backend/scripts/barchart_scraper/main.py), `config.py` (`BACK_MONTHS_TO_SCRAPE`)
- Chained view: Alembic `n8i9j0k1l2m3` (create), `r2m3n4o5p6q7` (recreate without legacy weekly columns)
- Wrapper chained window: [`backend/scripts/ensemble_compute/db_loader.py`](../../../backend/scripts/ensemble_compute/db_loader.py) (`_RECENT_DECISIONS_SELECT`, `_RECENT_VOTES_WINDOWED_SELECT`)
- Dashboard fallback: [`backend/app/utils/contract_resolver.py`](../../../backend/app/utils/contract_resolver.py) (`resolve_contract_for_date`)
