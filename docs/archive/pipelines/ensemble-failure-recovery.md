# Ensemble Failure Recovery

> Diagnostic + relaunch procedure for `cc-ensemble-compute` (C5 ensemble, shadow mode v1.0.0).
> Sister doc: [pipeline-failure-recovery.md](pipeline-failure-recovery.md) (legacy jobs).

## TL;DR

The ensemble job is **fail-loud, no auto-retry** (rule `pipeline-error-handling.md`). If it crashes, the dashboard is **not impacted** (`ensemble_v1.is_active=FALSE`, legacy serves all reads). Fix the root cause, then re-run manually.

## Where to look

| Signal | Where |
|--------|-------|
| Job exit code | `gcloud run jobs executions list --service=cc-ensemble-compute --region=europe-west9 --project=cacaooo --limit=5` |
| Per-run logs | `gcloud run jobs executions logs read <execution-id> --region=europe-west9 --project=cacaooo` |
| Sentry capture | Sentry project, monitor slug `ensemble-compute` |
| DB state | `./.local/db-prod.sh exec "<SQL>"` (read-only safe) |

## Common failures + remediation

### 1. `Can't locate revision identified by 'X'` at startup
**Cause**: DB schema is ahead of the code (or behind). Almost certainly someone ran `alembic upgrade head` against prod from a feature branch (cf rule `migrations-prod-via-main-only.md`).
**Fix**: Port the missing migration files onto main via a hotfix PR. Cf [PR #8](https://github.com/Commodities-Compass/commodities-compass/pull/8) for the precedent.

### 2. `EnsembleLoaderError: pl_article_segment empty for [...]`
**Cause**: `cc-press-review-agent` (cron 19:05 UTC) failed or wrote zero high-confidence segments for the 90-day macro window.
**Fix**:
1. Check press review run: `gcloud run jobs executions list --service=cc-press-review-agent ...`
2. If press review failed: rerun manually `gcloud run jobs execute cc-press-review-agent --region=europe-west9 --project=cacaooo` → wait for completion.
3. Then rerun ensemble: `gcloud run jobs execute cc-ensemble-compute --region=europe-west9 --project=cacaooo`.

### 3. `EnsembleLoaderError: market_history missing the target end_date X`
**Cause**: Barchart scraper failed → no OHLCV row for today. `v_contract_data_chained` excludes NULL-close rows.
**Fix**:
1. Rerun barchart: `gcloud run jobs execute cc-barchart-scraper --region=europe-west9`. Verify success.
2. Rerun compute-indicators (depends on OHLCV): `gcloud run jobs execute cc-compute-indicators`.
3. Rerun ensemble.

### 4. `RuntimeError: pl_algorithm_version row missing for name='ensemble_v1_softgate_wrapper'`
**Cause**: Migration `l6g7h8i9j0k1` was not applied or was downgraded.
**Fix**: `./.local/db-prod.sh exec "SELECT version_num FROM alembic_version;"` → if not at least `l6g7h8i9j0k1`, the DB is in an inconsistent state. Investigate before re-running.

### 5. `CompassWrapperConfigNotFoundError: missing 'compass_wrapper_dispersion_with_acc_threshold' row`
**Cause**: Migration `o9j0k1l2m3n4` was not applied or someone deleted the row.
**Fix**: Re-apply migration (idempotent) by triggering a Cloud Run revision restart, OR insert manually:
```bash
./.local/db-prod.sh exec "INSERT INTO pl_algorithm_config (id, algorithm_version_id, parameter_name, value, description) SELECT gen_random_uuid(), id, 'compass_wrapper_dispersion_with_acc_threshold', '0.60', 'Compass override' FROM pl_algorithm_version WHERE name='ensemble_v1_softgate_wrapper' AND version='1.0.0' AND NOT EXISTS (SELECT 1 FROM pl_algorithm_config WHERE parameter_name='compass_wrapper_dispersion_with_acc_threshold');"
```

### 6. `No specialist_model rows in pl_model_artifact — run cc-ensemble-bootstrap-artifacts first`
**Cause**: Bootstrap was wiped or never ran. Should not happen normally.
**Fix**: `gcloud run jobs execute cc-ensemble-bootstrap-artifacts --region=europe-west9 --project=cacaooo`. Verify post-run: `SELECT artifact_kind, COUNT(*) FROM pl_model_artifact GROUP BY 1;` → must show 38 rows (14 specialist_model + 14 specialist_hp + 1 each of long_run_anomaly/priors/regime + 1 each soft_gate_config/wrapper_config + 5 canonical_snapshot).

### 7. Unexpected sklearn unpickle warnings
**Cause**: Frozen artifacts were created with sklearn 1.6.1 but prod runs 1.5.2. Known tech debt — warning only, not an error. Ignore unless predictions diverge wildly.

## Re-run cascade

If the ensemble fails mid-pipeline (e.g., 19:18 today), the cascade impact is **zero** (downstream `cc-daily-analysis` reads legacy, `cc-compass-brief` reads legacy). Just rerun ensemble alone when ready:
```bash
gcloud run jobs execute cc-ensemble-compute --region=europe-west9 --project=cacaooo --args='--session-date,YYYY-MM-DD'
```

## What NOT to do

- ❌ **Never tunnel + `alembic upgrade head` on prod from a feature branch**. See [.claude/rules/migrations-prod-via-main-only.md](../../.claude/rules/migrations-prod-via-main-only.md). Origin of the 2026-05-21 prod outage.
- ❌ **Never patch vendored code in `backend/vendor/campaign5_ensemble_v1.0.0/`** — read-only by R&D contract. Override via subclass (see `compass_wrapper.py`).
- ❌ **Never disable `--max-retries=0`** — silent retries mask root causes (rule `pipeline-error-handling.md`).
- ❌ **Never flip `ensemble_v1.is_active=TRUE`** without explicit shadow→live cutover procedure (separate runbook, P2). The dashboard relies on legacy.

## Rollback plan (if shadow mode itself becomes problematic)

1. Pause scheduler: `gcloud scheduler jobs pause cc-ensemble-compute --location=europe-west1 --project=cacaooo`. Daily writes stop, dashboard unaffected.
2. If a recent run produced corrupted rows: `./.local/db-prod.sh exec "DELETE FROM pl_orchestrator_decision WHERE algorithm_version_id = (SELECT id FROM pl_algorithm_version WHERE name='ensemble_v1_softgate_wrapper') AND date >= 'YYYY-MM-DD';"` (and same for `pl_specialist_prediction`, `pl_indicator_daily`).
3. Investigate, fix, re-run.
