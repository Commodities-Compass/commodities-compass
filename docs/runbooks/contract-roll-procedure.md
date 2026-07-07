# Contract Roll Procedure — Operational Runbook

> Updated 2026-06-17 (post-ensemble, post multi-contract scrape). The legacy
> sections below still hold; the **Ensemble** and **Multi-contract** sections
> are the parts the original runbook was blind to.

## When to use this runbook

Run this when the active cocoa contract needs to roll to the next delivery month, typically every ~2 months as Open Interest (OI) shifts to the new front-month.

**Trigger signals**:
- OI of the next contract exceeds the active one for several days
- Active contract approaches its First Notice Day / Last Trading Day
- Manual decision based on the OI crossover chart on Barchart

**Delivery months for ICE Europe Cocoa #7**: `H` (Mar), `K` (May), `N` (Jul), `U` (Sep), `Z` (Dec). Codes are `CA<letter><yy>`. Example roll: `CAN26 → CAU26` (Jul → Sep 2026).

---

## TL;DR — two modes

- **Mode A — non-event roll (default once multi-contract scrape is live).** The barchart scraper now captures the **front + next delivery month** every day (`BACK_MONTHS_TO_SCRAPE`), so `v_contract_data_chained` (front-month-by-OI) **auto-switches at the true crossover**. The ensemble/engine already read the chained view, so a roll needs **no backfill and no rewrite** — you only flip `is_active` to relabel the dashboard headline and point the legacy track at the new contract. See **Mode A** below.
- **Mode B — manual backfill roll (legacy / fallback).** Used before multi-contract scrape existed, or if the back-month wasn't being captured (data gap). Requires manually inserting the new contract's OHLCV+OI. See **Mode B**. ⚠️ Sourcing that data is hard — see **Data-sourcing reality**.

---

## Pre-requisites

- `gcloud` authenticated (`gcloud auth login` — the token is **short-lived**, expect to re-auth; there's no non-interactive refresh). Project `cacaooo`.
- Prod DB access via the bastion: `./.local/db-prod.sh up` → `./.local/db-prod.sh exec "<SQL>"` → `./.local/db-prod.sh down`. (Read-only by default; the roll flip is an explicit, authorized DML — see [migrations-prod-via-main-only](../../.claude/rules/migrations-prod-via-main-only.md): the rule gates DDL, a value UPDATE in bastion is fine on explicit go.)
- New contract code identified (e.g. `CAU26`). It must exist in `ref_contract` (multi-contract scrape auto-registers it; otherwise `roll-contract` fails loud).

---

## Mode A — non-event roll (preferred)

1. **Confirm the chained view already serves the new contract.** With multi-contract scrape live, the new contract has rows in `pl_contract_data_daily` and once its OI exceeds the old one, the chained view picks it automatically — already correct *before* you flip the flag. Verify:
   ```sql
   SELECT date, contract_id FROM v_contract_data_chained ORDER BY date DESC LIMIT 5;
   ```
2. **Flip the active flag** (relabels the dashboard headline + repoints the legacy `cc-daily-analysis` track). Either:
   ```bash
   poetry run roll-contract CAU26      # validates + logs; needs prod DB URL
   ```
   or directly via bastion (guarded so you never land on zero active):
   ```sql
   DO $$ DECLARE n int; BEGIN
     SELECT count(*) INTO n FROM ref_contract WHERE code='CAU26';
     IF n<>1 THEN RAISE EXCEPTION 'CAU26 missing - abort'; END IF;
     UPDATE ref_contract SET is_active=false WHERE is_active=true;
     UPDATE ref_contract SET is_active=true  WHERE code='CAU26';
   END $$;
   ```
3. **Verify** exactly one active contract = the new code:
   ```sql
   SELECT code, is_active FROM ref_contract WHERE is_active;
   ```
4. **Done.** The next pipeline run computes on the new front-month via the chained view. No backfill, no recompute, no rewrite. The ensemble wrapper stays continuous (see **Ensemble** below).

---

## Mode B — manual backfill roll (legacy / fallback)

Use only if the back-month was NOT being scraped (so the chained view has a gap).

### B1 — Backfill the new contract
Insert ~5-10 sessions of the new contract's OHLCV+OI into `pl_contract_data_daily` so the chained view spans the crossover (smooths the contract-spread jump). ⚠️ See **Data-sourcing reality** — getting this data is the hard part.

### B2 — Flip the active flag
Same as Mode A step 2.

### B3 — Recompute (legacy/derived)
```bash
gcloud run jobs execute cc-compute-indicators \
  --args="compute-indicators,--all-contracts,--all-versions,--full" \
  --region=europe-west9 --project=cacaooo
```
`--full` re-upserts (front-month resolution may select a different contract for boundary dates). This covers legacy + shadow legacy algos. **It does NOT touch the ensemble** (separate job).

### B4 — (Optional) ensemble historical rewrite
Only if you want the crossover days' *ensemble* decisions recomputed on the true front-month, **and** the window is small (we cap at ~7 sessions), **and** you have real OHLCV+OI for them:
```bash
# chronological, one date at a time; --historical resolves front-month-by-OI per date
poetry run ensemble-compute --session-date <D> --historical   # for each crossover day, oldest first
poetry run ensemble-explainer --session-date <D>       # DB narrative only (~$0.13/day)
```
- This **overwrites** `pl_orchestrator_decision` for those days; the old (rolled-off contract) rows linger as duplicates per date — inert, because the chained-window join (PR #46) and the dashboard resolver both pick the front-month one. We don't delete produced signals (immutability).
- **Do NOT** re-run `cc-compass-brief-ensemble` / regenerate NotebookLM podcasts for past days — those are frozen "published editions". The explainer rewrite is DB-only and does not touch Drive briefs or podcasts.
- If the crossover is **> the cap** or you lack real data → **don't rewrite**; roll forward-only. The historical days stay on the old contract (covered by the dashboard's cross-contract fallback) — an honest blemish, not fabricated data.

---

## Ensemble specifics (what the old runbook missed)

- **`v_contract_data_chained`** (`DISTINCT ON (date) ORDER BY oi DESC`) is the front-month-by-OI series. `cc-ensemble-compute` reads it for `market_history` (600d GARCH lookback) and `cc-compute-indicators` uses the same front-month picker. So **past ensemble decisions are roll-stable** — they don't need recompute on a roll (unlike legacy's `--full`).
- **Wrapper trailing window (PR #46, merged `71be87d`)**: the Compass wrapper's `running_acc` / cluster-dispersion inputs now chain across rolls via the view (`db_loader._RECENT_DECISIONS_SELECT` / `_RECENT_VOTES_WINDOWED_SELECT` join the chained view). **Without this**, a roll reset the wrapper to a permissive NaN-bootstrap for ~1-2 weeks (it blindly committed directional bets with no accuracy signal). With it, the wrapper has continuity at the roll — **no warmup**. This is the durable fix that makes forward-only rolls safe.
- **Model artifacts** (`pl_model_artifact`) are commodity-agnostic — **no re-bootstrap** on a roll.
- **`cc-ensemble-explainer` / `cc-compass-brief-ensemble`** resolve the active contract at runtime and are fail-loud if the ensemble row is missing.

---

## Data-sourcing reality (read before Mode B)

Sourcing the new contract's **historical OHLCV + OI** for a backfill is the real blocker:
- **Barchart `/overview`** = public, **current-day only**. The prod scraper reads OI from the page's server-rendered inline JSON (max-volume block) — reliable, but one day.
- **Barchart `/historical-prices` table** = **login-gated** (renders empty anonymously).
- **Yahoo Finance** = **no open interest at all**, and no reliable ICE *London* contract (`CC=F` is ICE *US*). Cannot backfill our London (`CA`) contract.
- **Prod DB** only ever had the *active* contract (pre-multi-contract scrape).
- Reading OHLC off a candle **chart** is ±15-20 GBP + error-prone — too fuzzy to write to `pl_contract_data_daily` (which has no "estimated" flag). Don't.

→ This is exactly why **Mode A (multi-contract scrape) is the answer**: capture the back-month *daily, in real time*, so there's never a historical gap to fill.

---

## Worked example — CAN26 → CAU26 (2026-06-17, forward-only)

- CAU26 OI overtook CAN26 ≈ **Jun 3** (CAU26 rising 43k→53.6k; CAN26 declining 44.8k→30.2k). Crossover was **~10 sessions** — over the ~7-session rewrite cap.
- Historical CAU26 OHLCV+OI was **not obtainable** (no Barchart account, Yahoo has no OI).
- Decision: **rolled forward-only** (Mode A flag flip), **no historical rewrite**. PR #46 (chained wrapper window, deployed before the roll) made the warmup a non-issue; the dashboard's cross-contract fallback covers the ~10 historical CAN26 days.
- Follow-up: multi-contract scrape (this PR) so the *next* roll is a true non-event.

---

## Rollback

Revert the flag and (Mode B only) re-run the recompute:
```sql
UPDATE ref_contract SET is_active=false WHERE is_active=true;
UPDATE ref_contract SET is_active=true  WHERE code='<previous_code>';
```

---

## Background — dashboard cross-contract fallback

After a roll, historical (pre-roll) dates would show empty gauges if dashboard queries filtered strictly by the active contract. `resolve_contract_for_date()` in `app/utils/contract_resolver.py` resolves the best contract per date with priority: (1) active w/ complete data → (2) any contract w/ complete data → (3) active w/ any row → (4) any contract w/ market data (highest OI). YTD performance uses a cross-contract `DISTINCT ON (date) ORDER BY oi DESC` to span rolls seamlessly. Transparent to the user — no gaps across roll boundaries.

---

## Past incidents (CAK26 → CAN26, 2026-04-14)

Fixed but verify after each roll: daily-analysis hardcoded contract default (now DB-resolved); daily-analysis SQL had no contract filter (now filters + cross-contract fallback for transition days); compass-brief had no contract filter; compute engine interleaved overlapping contracts (now `DISTINCT ON (date) ORDER BY oi DESC`); press-review prompt missed contract context (now injects `contract_code` + `contract_month`).

---

## Related files

- Multi-contract scrape: `backend/scripts/barchart_scraper/main.py` (front + `BACK_MONTHS_TO_SCRAPE` loop), `config.py` (`BACK_MONTHS_TO_SCRAPE`, parameterized URLs)
- Cycle + auto-register: `backend/scripts/contract_resolver.py` (`next_contract_code`, `contract_month_for`, `ensure_contract`)
- Roll CLI: `backend/scripts/roll_contract.py` (`poetry run roll-contract`)
- Prod DB access: `.local/db-prod.sh`
- Ensemble chained window: `backend/scripts/ensemble_compute/db_loader.py`; VIEW in Alembic `n8i9j0k1l2m3` / `r2m3n4o5p6q7`
- Dashboard fallback: `backend/app/utils/contract_resolver.py` (`resolve_contract_for_date`)
