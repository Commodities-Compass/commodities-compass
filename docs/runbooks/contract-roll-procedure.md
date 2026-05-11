# Contract Roll Procedure — Operational Runbook

## When to use this runbook

Run this when the active cocoa contract needs to roll to the next delivery month, typically every 2 months as Open Interest (OI) shifts to the front-month contract.

**Trigger signals**:
- OI of the next contract exceeds the active one for several days
- Active contract approaches its First Notice Day or Last Trading Day
- Manual decision based on the OI crossover chart on Barchart

**Delivery months for ICE Europe Cocoa #7**: `H` (Mar), `K` (May), `N` (Jul), `U` (Sep), `Z` (Dec). Example roll: `CAK26 → CAN26` (May → July 2026).

## Pre-requisites

- Local `.env` configured with GCP DATABASE_URL (bastion-tunneled — see [db-sync-from-gcp.md](./db-sync-from-gcp.md) for the tunnel)
- `gcloud` CLI authenticated, project `cacaooo`, region `europe-west9`
- The new contract code identified (e.g. `CAN26`)

## Procedure

### Step 1 — Backfill the new contract (optional but recommended)

Insert 5-10 days of the new contract's OHLCV+OI into `pl_contract_data_daily` from Barchart charts. Copy `stock_us` / `com_net_us` from the old contract's rows (these are commodity-level and identical).

**Why**: smooths the price transition. The compute engine's `DISTINCT ON (date) ORDER BY oi DESC` picks the front-month automatically at the OI crossover, but only if both contracts have rows.

```sql
-- Example pattern (adapt date range and codes)
INSERT INTO pl_contract_data_daily (date, contract_id, close, high, low, volume, oi, iv, stock_us, com_net_us)
SELECT
  d.date,
  (SELECT id FROM ref_contract WHERE code = 'CAN26'),
  <new_close>, <new_high>, <new_low>, <new_volume>, <new_oi>, <new_iv>,
  d.stock_us, d.com_net_us
FROM pl_contract_data_daily d
WHERE d.contract_id = (SELECT id FROM ref_contract WHERE code = 'CAK26')
  AND d.date BETWEEN '2026-04-01' AND '2026-04-13';
```

### Step 2 — Roll the active flag

```bash
# Run via bastion tunnel, against GCP prod
poetry run roll-contract CAN26
```

Or direct SQL:

```sql
UPDATE ref_contract SET is_active = false WHERE is_active = true;
UPDATE ref_contract SET is_active = true  WHERE code = 'CAN26';
```

All scrapers and agents auto-detect the new active contract on next run via `resolve_active_code()`. No env var change required.

### Step 3 — Deploy any code fixes

If the roll surfaced any bug (see "Past incidents" below), deploy first via the standard CI/CD (push to `main`) before recomputing.

### Step 4 — Recompute all indicators (full backfill)

```bash
gcloud run jobs execute cc-compute-indicators \
  --args="compute-indicators,--all-contracts,--all-versions,--full" \
  --region=europe-west9 \
  --project=cacaooo
```

`--full` re-upserts all rows (needed because front-month resolution may now select a different contract for boundary dates). `--all-versions` covers shadow algos (e.g. `power10years`).

### Step 5 — Verify

1. **DB**: `SELECT date, contract_id FROM pl_indicator_daily ORDER BY date DESC LIMIT 10;` — confirm rows exist for the new contract
2. **Dashboard**: open `https://app.com-compass.com/dashboard`, check current day shows new contract data, then navigate back across the roll boundary — historical dates must still resolve correctly (cross-contract fallback in `dashboard_service._resolve_contract_for_date()`)
3. **Press review**: confirm next day's article references the new contract month (the prompt injects `contract_code` and `contract_month` — was a bug previously, now fixed)

## Rollback

If the new contract data is wrong (e.g. backfill from the wrong source), revert the active flag and re-run the original recompute:

```sql
UPDATE ref_contract SET is_active = false WHERE is_active = true;
UPDATE ref_contract SET is_active = true  WHERE code = 'CAK26';
```

Then re-run Step 4 with `--full`.

## Past incidents (read before doing the next roll)

These bugs were caught during the `CAK26 → CAN26` roll on 2026-04-14. They are fixed but worth verifying after each roll:

- **Daily analysis hardcoded contract default** — `--contract CAK26` was the default in the CLI. Now resolves from DB via `resolve_active_code()`. Verify: `poetry run daily-analysis --help` shows no contract default
- **Daily analysis SQL had no contract filter** — `_read_technicals()` returned data for all contracts mixed. Now filters by active contract with cross-contract fallback for transition days (< 2 rows for the active contract → falls back)
- **Compass brief had no contract filter** — queries returned data for all contracts. Now filter by `ref_contract.is_active = true`
- **Compute engine interleaved overlapping contract data** — `load_all_market_data()` could mix contracts on transition days. Now uses `DISTINCT ON (date) ORDER BY oi DESC` to pick the front-month per date
- **Press review prompt missed contract context** — LLM guessed contract month from news instead of from active contract. Now injects `contract_code` and `contract_month` into the prompt template

## Background — dashboard cross-contract fallback

After a roll, navigating to historical dates (pre-roll) used to show empty gauges because dashboard queries filtered by `contract_id = active_contract` (e.g. `CAN26`), but pre-roll data lives on the previous contract (`CAK26`).

`_resolve_contract_for_date()` in `backend/app/services/dashboard_service.py` resolves the best contract for any historical date with priority:

1. Active contract with complete data (`conclusion IS NOT NULL`)
2. Any contract with complete data for that date (cross-contract fallback)
3. Active contract with any row (indicators without conclusion)
4. Any contract with market data (highest OI = front-month heuristic)

YTD performance uses a separate cross-contract query (`DISTINCT ON (date) ORDER BY oi DESC`) to span contract rolls seamlessly over the full year. This ensures the dashboard always shows the best available data regardless of which contract was active at that historical date — transparent to the user, no gaps across roll boundaries.

## Related files

- CLI: `backend/scripts/roll_contract.py` (entry point: `poetry run roll-contract`)
- Resolver: `backend/app/utils/contract_resolver.py` (`resolve_active_code()`)
- Compute engine front-month picker: `backend/app/engine/runner.py` (`load_all_market_data()`)
- Dashboard fallback: `backend/app/services/dashboard_service.py` (`_resolve_contract_for_date()`)
- Press review contract injection: `backend/scripts/press_review_agent/config.py`
