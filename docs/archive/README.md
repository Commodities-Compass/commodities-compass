# `docs/archive/` — Snapshot of completed initiatives

This archive holds documentation that **described work that has shipped** (or has
been deferred indefinitely). It's preserved for context and traceability but is
no longer actively maintained.

If you find yourself looking here for "how does X work today", check
[`../runbooks/`](../runbooks/) and [`../architecture/`](../architecture/) first.

## Contents

| Path | What it was | Status |
|---|---|---|
| [`2026-05-rnd-handoff/`](2026-05-rnd-handoff/) | R&D handoff package for the Campaign 5 ensemble migration. Includes Julien data map, weekend recaps, agent snapshots, and the frozen `handoff_v1.0.0/` deliverable (8 numbered docs: architecture, data sources, schema, algorithm, performance, parquet exports). | Shipped (C5 live on dashboard since 2026-05-23). |
| [`onboarding/`](onboarding/) | Initial onboarding artifacts: ENSO/FX CSV data dumps, R&D ingest scripts (`ingest_enso.py`, `ingest_fx.py`, `extract_rd_dataset.py`), C5 prod deployment guide, R&D-to-prod algo integration notes, full data map (HEDI_DATA_MAP.md). | Shipped (data sources now ingested via prod scrapers; map info migrated into `architecture/`). |
| [`backtests/`](backtests/) | Historical backtest reports (e.g., 2024-2025 seasonal v4 worst-season-label exploration). | Reference only. |
| `BRIEF_PROD_OPTIMIZER_BRIDGE_2026-05-17.md` | Proposal for a read-only API bridge between Compass and an external "cockpit" UI (Julien's project). | Deferred. |

## When to add to this archive

When a doc was specific to a sprint or initiative and the work is now done. Move
the file/folder under a dated subdirectory like `YYYY-MM-<initiative>/` and link
it from this README.

## When to delete

If a doc has been here for 2+ years and the work it described is no longer
referenced in any runbook, architecture doc, or git blame, it can be deleted
in a separate housekeeping PR.
