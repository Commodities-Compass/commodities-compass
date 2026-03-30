# User Story: Active Contract Resolution from Database

## Epic

As the **CTO/sole operator**, I need scrapers to resolve the active contract from the database instead of an environment variable, so that contract rolls don't require manual env var updates across Railway, GCP Cloud Run Jobs, and GitHub vars.

---

## Context

**Current state**: The barchart scraper reads `ACTIVE_CONTRACT` from an env var (e.g., `CAK26`). On contract roll (~5x/year), the operator must update the env var in Railway, Cloud Run Jobs (`gcloud run jobs update`), and GitHub vars. Forgetting any one of these silently breaks the scraper with a wrong-contract or missing-var error.

**Target state**: All scrapers and agents that need the active contract call `get_active_contract_code(db)` which reads `ref_contract WHERE is_active = true`. Contract rolls become a single DB update — no infra changes needed.

---

## User Stories

### US-1: Contract resolver reads from ref_contract

**As** the pipeline operator,
**I want** a shared function that returns the active contract code from the database,
**So that** I don't maintain the same value in 3+ env var locations.

**Acceptance criteria:**
- `get_active_contract_code(db)` returns the `code` (e.g., `CAK26`) from `ref_contract WHERE is_active = true`
- Raises a clear error if zero or multiple active contracts found
- Works with both sync (scrapers) and async (API) database sessions
- `app/utils/contract_resolver.py` already has `get_active_contract_id()` (returns UUID) — extend with `get_active_contract_code()` (returns string code)

### US-2: Barchart scraper uses DB resolver

**As** the pipeline operator,
**I want** the barchart scraper to read the active contract from the database,
**So that** I never need to set `ACTIVE_CONTRACT` env var again.

**Acceptance criteria:**
- Scraper calls `get_active_contract_code()` at startup instead of `os.environ["ACTIVE_CONTRACT"]`
- Falls back to `ACTIVE_CONTRACT` env var if DB is unavailable (graceful degradation)
- Log line at startup: `Active contract: CAK26 (source: database)` or `Active contract: CAK26 (source: env var fallback)`
- `ACTIVE_CONTRACT` env var removed from deploy.yml, GitHub vars, and Cloud Run Job config after migration

### US-3: Contract roll is a single DB operation

**As** the pipeline operator,
**I want** to roll to a new contract with one SQL statement,
**So that** contract rolls take 30 seconds instead of updating 3+ systems.

**Acceptance criteria:**
- Roll procedure: `UPDATE ref_contract SET is_active = false WHERE is_active = true; UPDATE ref_contract SET is_active = true WHERE code = 'CAN26';`
- No env var changes, no redeploy, no CI/CD trigger needed
- All scrapers and the dashboard API pick up the new contract on next run
- Add a CLI command or script: `poetry run roll-contract CAN26`

---

## Technical Design

### Changes

| File | Change |
|------|--------|
| `app/utils/contract_resolver.py` | Add `get_active_contract_code()` (sync + async) |
| `scripts/barchart_scraper/config.py` | Replace `os.environ["ACTIVE_CONTRACT"]` with DB lookup + env fallback |
| `scripts/roll_contract.py` | New CLI script for safe contract roll with validation |
| `.github/workflows/deploy.yml` | Remove `ACTIVE_CONTRACT` from barchart job env vars (after migration) |

### Resolver API

```python
# Async (API, dashboard)
async def get_active_contract_id(db: AsyncSession) -> uuid.UUID: ...
async def get_active_contract_code(db: AsyncSession) -> str: ...

# Sync (scrapers, cron jobs)
def get_active_contract_code_sync(db: Session) -> str: ...
```

---

## Out of Scope

- Automatic contract roll based on OI crossover or calendar rules — manual trigger is fine at current scale
- Multi-contract support (tracking 2+ contracts simultaneously) — North Star Phase 6+
- Backfill historical contract rolls in ref_contract — not needed for forward operation

## Dependencies

- `ref_contract` table exists with `is_active` column (already deployed)
- Sync DB session available in scraper context (`scripts/db.py`)
- `contract_resolver.py` already exists with async UUID resolver (Phase 4.2)

## Migration Plan

1. Add `get_active_contract_code_sync()` to resolver
2. Update barchart scraper config.py with DB lookup + env fallback
3. Test on GCP: remove env var, verify scraper reads from DB
4. Remove `ACTIVE_CONTRACT` from deploy.yml and GitHub vars
5. Document roll procedure in runbook
