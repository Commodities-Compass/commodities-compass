# `backend/scripts/archive/` — One-shot utilities and analysis scripts

This directory holds scripts that were used **once or rarely** during development,
backfills, R&D handoffs, or post-mortem analyses. They are kept in the repo for
traceability but are NOT part of the daily production pipeline (Cloud Run Jobs).

None of these should be added to `[tool.poetry.scripts]` in `backend/pyproject.toml`.
Run them ad-hoc via `poetry run python backend/scripts/archive/<name>.py`.

## Contents

| Script | Purpose | Last used |
|---|---|---|
| `_analyze_backfill_coverage.py` | Audit ensemble v1 coverage/accuracy vs R&D baseline after backfill runs. Hardcoded baseline (R&D screenshot Feb 2026) — update inline `RND` dict when new baselines arrive. | 2026-05 (C5 rollout) |
| `_analyze_press_review_gaps.py` | Detect days where press review data is missing (outages, parsing failures). Manual run after press outages to audit coverage; complements `publication_calendar_watchdog`. | 2026-05 |
| `_backfill_ensemble_local.sh` | Local-only re-backfill loop for ensemble_v1 over a date range. Uses `DATABASE_SYNC_URL`. Not for prod. | 2026-05 (C5 rollout) |
| `julien_handoff/` | Data export bundle generator (CSVs + metadata JSON + README) for R&D handoff to Julien's ML team. ~950 LoC, no scheduled trigger. | 2026-05-28 |

## When to use these

- After a prod data anomaly, run `_analyze_press_review_gaps.py` to spot gaps.
- After a C5 model bump, run `_analyze_backfill_coverage.py` against the new R&D baseline.
- When R&D needs a fresh data slice, run `julien_handoff/`.
- For local backfill iteration on ensemble: `_backfill_ensemble_local.sh`.

## When to delete

If a script has not been touched for 12+ months and the related workflow has been
replaced by a scheduled job or a proper module, delete it from this archive.
