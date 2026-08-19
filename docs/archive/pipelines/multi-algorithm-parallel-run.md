# Multi-Algorithm Parallel Run — Operational Runbook

## How It Works

The indicator engine supports running multiple algorithm versions in parallel. Each version applies a different power formula (different coefficients, thresholds) to the **same** raw indicators (EMA, RSI, MACD, etc.). Results are written to separate rows in `pl_indicator_daily`, keyed on `(date, contract_id, algorithm_version_id)`.

```
pl_contract_data_daily (raw OHLCV — shared)
    │
    └─→ pl_derived_indicators (27 technical indicators — shared, version-agnostic)
         │
         ├─→ pl_indicator_daily  (version=1.0.1) → scores, z-scores, composite, decision
         ├─→ pl_indicator_daily  (version=2.0.0) → scores, z-scores, composite, decision
         │
         ├─→ pl_signal_component (version=1.0.1) → per-indicator weighted contributions
         └─→ pl_signal_component (version=2.0.0) → per-indicator weighted contributions
```

**Key principle**: Raw indicators are computed once (shared). Only the power formula stage (composite score + decision) differs per version. This means adding a version costs ~0 extra compute for the indicator calculation, only the final scoring pass.

## Current State (as of 2026-04-14)

| Name | Version | is_active | compute_enabled | Status |
|------|---------|-----------|-----------------|--------|
| legacy | 1.0.0 | false | false | Retired — original params, no longer computed |
| legacy | 1.0.1 | **true** | true | **Production** — dashboard serves this version |
| power10years | 2.0.0 | false | true | Shadow mode — computes nightly, not shown on dashboard |

- **`is_active`**: Which version the dashboard displays (exactly one must be true)
- **`compute_enabled`**: Whether the nightly pipeline computes this version

## Nightly Pipeline

The Cloud Run Job runs `poetry run compute-indicators --all-contracts --all-versions`:

```
19:15 UTC  cc-compute-indicators
           ├─ Loads market data once (all contracts, ~2500 rows)
           ├─ For each version WHERE compute_enabled = true:
           │   ├─ Loads AlgorithmConfig from pl_algorithm_config
           │   ├─ Runs power formula with version-specific coefficients
           │   ├─ Writes to pl_indicator_daily (keyed by algorithm_version_id)
           │   └─ Writes to pl_signal_component (keyed by algorithm_version_id)
           └─ Done (~2 min total for 2 versions)
```

Market data is loaded once and shared across all versions — no duplication.

## Schema

### pl_algorithm_version

```sql
CREATE TABLE pl_algorithm_version (
    id              UUID PRIMARY KEY,
    name            VARCHAR(50) NOT NULL,        -- e.g., "legacy", "power10years"
    version         VARCHAR(20) NOT NULL,        -- e.g., "1.0.1", "2.0.0"
    horizon         VARCHAR(20),                 -- "short_term"
    is_active       BOOLEAN DEFAULT false,       -- dashboard display (single)
    compute_enabled BOOLEAN DEFAULT false,       -- nightly computation (multiple)
    description     TEXT,
    UNIQUE (name, version)
);
```

### pl_algorithm_config

EAV table storing power formula parameters per version:

```sql
CREATE TABLE pl_algorithm_config (
    id                    UUID PRIMARY KEY,
    algorithm_version_id  UUID REFERENCES pl_algorithm_version(id),
    parameter_name        VARCHAR(50),    -- k, a, b, c, d, ..., open_threshold, hedge_threshold
    value                 FLOAT
);
```

Parameters: `k` (offset), `a/b` (RSI coeff/exponent), `c/d` (MACD), `e/f` (Stochastic), `g/h` (ATR), `i/j` (Close/Pivot), `l/m` (Vol/OI), `n/o` (Momentum), `p/q` (Macroeco), `open_threshold`, `hedge_threshold`, `momentum_threshold`, `smoothing_window`.

## Procedures

### Adding a new algorithm version

1. **Seed the config** — add a function in `backend/scripts/seed_gcp.py`:
   ```python
   def seed_algorithm_v3(session: Session) -> uuid.UUID:
       algo = PlAlgorithmVersion(
           name="new_algo", version="3.0.0",
           horizon="short_term",
           is_active=False,       # NOT the dashboard default
           compute_enabled=True,  # start computing immediately
           description="Description of the new version",
       )
       session.add(algo)
       session.flush()
       for param_name, value in NEW_PARAMS.items():
           session.add(PlAlgorithmConfig(
               algorithm_version_id=algo.id,
               parameter_name=param_name,
               value=value,
           ))
       return algo.id
   ```

2. **Insert in GCP prod** — run the seed script or INSERT directly via bastion:
   ```sql
   INSERT INTO pl_algorithm_version (id, name, version, horizon, is_active, compute_enabled, description)
   VALUES (gen_random_uuid(), 'new_algo', '3.0.0', 'short_term', false, true, 'Description');

   -- Insert config params (21 rows)
   INSERT INTO pl_algorithm_config (id, algorithm_version_id, parameter_name, value)
   SELECT gen_random_uuid(), id, v.param, v.val
   FROM pl_algorithm_version, (VALUES
       ('k', 1.5), ('a', 0.5), ('b', 0.685), ...
   ) AS v(param, val)
   WHERE name = 'new_algo' AND version = '3.0.0';
   ```

3. **Backfill** — compute on full history:
   ```bash
   poetry run compute-indicators --all-contracts --algorithm new_algo --algorithm-version 3.0.0 --full --force
   ```
   Or via Cloud Run Job:
   ```bash
   gcloud run jobs execute cc-compute-indicators \
     --args="compute-indicators,--all-contracts,--algorithm,new_algo,--algorithm-version,3.0.0,--full,--force" \
     --region=europe-west9 --project=cacaooo
   ```

4. **Verify** — check rows exist:
   ```sql
   SELECT COUNT(*), MIN(date), MAX(date)
   FROM pl_indicator_daily i
   JOIN pl_algorithm_version av ON i.algorithm_version_id = av.id
   WHERE av.name = 'new_algo' AND av.version = '3.0.0';
   ```

5. **Nightly auto-compute** — `--all-versions` picks it up automatically (no deploy needed). The job queries `WHERE compute_enabled = true`.

### Comparing versions

#### Decision agreement rate
```sql
SELECT
  COUNT(*) as total_days,
  SUM(CASE WHEN v1.decision = v2.decision THEN 1 ELSE 0 END) as agree,
  ROUND(100.0 * SUM(CASE WHEN v1.decision = v2.decision THEN 1 ELSE 0 END)
        / COUNT(*), 1) as agreement_pct
FROM pl_indicator_daily v1
JOIN pl_indicator_daily v2
  ON v1.date = v2.date AND v1.contract_id = v2.contract_id
JOIN pl_algorithm_version av1 ON v1.algorithm_version_id = av1.id
JOIN pl_algorithm_version av2 ON v2.algorithm_version_id = av2.id
WHERE av1.version = '1.0.1' AND av2.version = '2.0.0';
```

#### Side-by-side last N days
```sql
SELECT
  v1.date,
  v1.decision as v1_decision, v2.decision as v2_decision,
  ROUND(v1.final_indicator::numeric, 3) as v1_score,
  ROUND(v2.final_indicator::numeric, 3) as v2_score,
  CASE WHEN v1.decision = v2.decision THEN '=' ELSE 'DIFFER' END as match
FROM pl_indicator_daily v1
JOIN pl_indicator_daily v2
  ON v1.date = v2.date AND v1.contract_id = v2.contract_id
JOIN pl_algorithm_version av1 ON v1.algorithm_version_id = av1.id
JOIN pl_algorithm_version av2 ON v2.algorithm_version_id = av2.id
WHERE av1.version = '1.0.1' AND av2.version = '2.0.0'
ORDER BY v1.date DESC LIMIT 30;
```

#### YTD accuracy vs price moves
```sql
WITH decisions AS (
  SELECT
    i.date, av.version, i.decision,
    d.close,
    LEAD(d.close) OVER (PARTITION BY av.version ORDER BY i.date) as next_close
  FROM pl_indicator_daily i
  JOIN pl_contract_data_daily d ON i.date = d.date AND i.contract_id = d.contract_id
  JOIN pl_algorithm_version av ON i.algorithm_version_id = av.id
  WHERE av.compute_enabled = true
    AND i.decision IN ('OPEN', 'HEDGE')
    AND i.date >= '2026-01-01'
)
SELECT
  version, decision, COUNT(*) as signals,
  SUM(CASE
    WHEN decision = 'OPEN'  AND next_close > close THEN 1
    WHEN decision = 'HEDGE' AND next_close < close THEN 1
    ELSE 0
  END) as correct,
  ROUND(100.0 * SUM(CASE
    WHEN decision = 'OPEN'  AND next_close > close THEN 1
    WHEN decision = 'HEDGE' AND next_close < close THEN 1
    ELSE 0
  END) / NULLIF(COUNT(*), 0), 1) as accuracy_pct
FROM decisions
WHERE next_close IS NOT NULL
GROUP BY version, decision
ORDER BY version, decision;
```

### Promoting a version to production

Single SQL transaction — no code deploy needed:

```sql
BEGIN;
UPDATE pl_algorithm_version SET is_active = false WHERE is_active = true;
UPDATE pl_algorithm_version SET is_active = true WHERE name = 'power10years' AND version = '2.0.0';
COMMIT;
```

The dashboard API uses `get_active_algorithm_version_id()` with a 5-min TTL cache. After promotion, the dashboard serves the new version within 5 minutes.

**Rollback** is the same SQL with versions swapped.

### Retiring a version

Stop computing but keep historical data:

```sql
UPDATE pl_algorithm_version SET compute_enabled = false WHERE name = 'legacy' AND version = '1.0.0';
```

Historical rows in `pl_indicator_daily` and `pl_signal_component` are preserved for comparison. The nightly job stops computing new rows for this version.

## Guardrails

- **Exactly one `is_active = true`** at all times — the dashboard resolver throws if 0 or >1
- **`compute_enabled` is independent of `is_active`** — a version can compute in shadow mode without being shown
- **`pl_derived_indicators` is version-agnostic** — raw technicals are computed once, shared by all versions. Never delete or recompute these when adding/removing a version
- **No code changes needed** to add/remove/promote versions — it's all DB config. The `--all-versions` flag queries `WHERE compute_enabled = true` dynamically
- **Daily analysis** writes LLM fields (macroeco_bonus, decision, direction, conclusion) only to the `is_active` version's row. Shadow versions get pure-technical scores without LLM enrichment

## Relationship to Contract Rolls

Algorithm versions and contract rolls are independent:
- `ref_contract.is_active` controls which contract the pipeline scrapes and the dashboard shows
- `pl_algorithm_version.is_active` controls which algorithm the dashboard shows
- Both can change independently (roll contract without changing algo, or promote algo without rolling contract)
- `pl_indicator_daily` is keyed on `(date, contract_id, algorithm_version_id)` — all combinations are stored
