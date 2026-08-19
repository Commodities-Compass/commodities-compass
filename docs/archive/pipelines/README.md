# Archive — the legacy and ensemble tracks

Everything in this folder describes a system that **no longer runs**. It is kept
because the rows those tracks wrote are still in the database and someone will
eventually need to know what produced them.

Retired on **2026-08-19**, when `regime+judge` became the served track
(`pl_algorithm_version.serving_rank`). See
[PIPELINE_REGIME_JUDGE.md](../../architecture/PIPELINE_REGIME_JUDGE.md) for what
runs today.

## What went

| Track | Jobs | Wrote |
|---|---|---|
| **LEGACY** | `cc-daily-analysis`, `cc-compass-brief` | `pl_indicator_daily` (legacy rows), Drive `YYYYMMDD-CompassBrief.txt` |
| **ENSEMBLE (C5)** | `cc-ensemble-compute`, `cc-ensemble-explainer`, `cc-compass-brief-ensemble`, `cc-ensemble-bootstrap-artifacts` | `pl_orchestrator_decision`, 14× `pl_specialist_prediction`, `pl_indicator_daily` (ensemble rows), Drive `…-CompassBrief-Ensemble.txt` |

Their Cloud Scheduler entries were destroyed and their code deleted (−28 617
lines). The Cloud Run **jobs** still exist, pinned to the last image that
contained their code, so a forensic backfill remains possible by triggering them
by hand — but nothing schedules them.

## What did NOT go, and why

- **The tables.** `pl_orchestrator_decision`, `pl_specialist_prediction` and the
  legacy/ensemble rows of `pl_indicator_daily` are untouched. They are the audit
  trail of every decision those tracks published to a client.
- **`pl_model_artifact`.** Still holds the 38 frozen C5 artefacts. Unpickling one
  needs the numpy/pandas/sklearn versions pinned in `backend/pyproject.toml` —
  which is why those pins survived the deletion.
- **`app/engine/`.** `cc-compute-indicators` is alive and load-bearing: it feeds
  `pl_derived_indicators` and `pl_dashboard_gauge`. It was never ensemble-specific.

## Reading these files

They were accurate the day they were archived. Treat every present tense in them
as past tense, and do not use them to reason about current behaviour — in
particular the rollback procedures, which describe a path that no longer exists:
reverting `serving_rank` still executes, but ensemble stopped writing rows on
2026-08-18, so it would serve data frozen at that date.
