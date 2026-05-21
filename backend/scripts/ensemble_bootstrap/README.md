# `cc-ensemble-bootstrap-artifacts`

One-shot Cloud Run Job that loads the **Campaign 5 ensemble frozen
artefacts** from `backend/vendor/campaign5_ensemble_v1.0.0/frozen/`
into the `pl_model_artifact` table.

## What it loads

Per delivery v1.0.0 (TRAINING_CUTOFF 2026-04-30), ~38 rows:

| Kind | Count |
|---|---|
| `specialist_model` | 14 |
| `specialist_hp` | 14 |
| `long_run_anomaly` | 1 |
| `long_run_priors` | 1 |
| `long_run_regime_clusters` | 1 |
| `soft_gate_config` | 1 |
| `wrapper_config` | 1 |
| `canonical_snapshot` | 5 |

Each row stores the binary payload + SHA-256 + provenance (git_sha,
python_version, lib_versions, fit train range, class balance).

## How it works

This module is a thin wrapper around the **R&D-provided loader**
`vendor/campaign5_ensemble_v1.0.0/tools/load_artifacts_to_pg.py`. The
R&D tool already does everything we need:

1. Reads `manifest.json` and verifies each file's SHA-256 (fail-loud).
2. UPSERTs each artefact in one transaction.
3. Re-reads every row and verifies SHA-256 end-to-end.

The wrapper exists only to:

- Translate `DATABASE_SYNC_URL` (SQLAlchemy URL with `+psycopg2` dialect)
  into the plain `postgres://` string `psycopg2.connect()` expects.
- Pin `FROZEN_DIR` to the vendored path (operator never has to remember).
- Register Sentry monitor (`ensemble-bootstrap-artifacts` slug) and route
  exceptions through `sentry_sdk.capture_exception`.

## Usage

```bash
# Live load against the DB pointed at by .env DATABASE_SYNC_URL
poetry run ensemble-bootstrap-artifacts

# Parse + verify SHA-256 on disk, no DB writes
poetry run ensemble-bootstrap-artifacts --dry-run

# Custom version name (rare — used when R&D ships ensemble_v2 etc.)
poetry run ensemble-bootstrap-artifacts \
    --algorithm-version-name ensemble_v2_softgate_wrapper \
    --algorithm-version 2.0.0
```

## Run cadence

- **First time**: once after the Alembic migrations have created
  `pl_model_artifact` + seeded `pl_algorithm_version`.
- **Monthly retrains** (R&D ships new tarball): re-extract vendor, bump
  version path in `pyproject.toml`, re-run this job. The UPSERT replaces
  old rows for the same (artifact_kind, artifact_name, training_month).

No cron — fully manual, triggered when R&D releases a new tarball.

## Fail-loud guarantees

- SHA-256 mismatch on any payload → R&D tool exits non-zero → our wrapper
  surfaces it to Sentry.
- Missing `DATABASE_SYNC_URL` → wrapper returns 1.
- Missing vendor dir or frozen dir → wrapper returns 1.

Per `.claude/rules/pipeline-error-handling.md`: no retry, no fallback.
Investigate, fix, manually relaunch.
