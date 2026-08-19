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
lines). The six Cloud Run **jobs** were deleted too, on 2026-08-19.

They had been kept for a day, frozen on `jobs:b73005c3` — the image built from
PR #99, the commit immediately before the deletion — on the idea that a forensic
replay stayed one click away. That was true for about a month and no longer than
that: the Artifact Registry repo (83 GB) runs `delete-old-versions` at 30 days
with `tagState: ANY`, and `keep-minimum-versions` protects only the 5 most recent
builds. `b73005c3` sat at rank 5 and the next deploy would have pushed it out, so
the image was due to vanish around 2026-09-18 and leave six jobs pointing at
nothing. A one-click path with a silent expiry date is worse than no path.

## How to replay one of them now

Nothing was lost — the click was a convenience, not the capability:

```bash
git checkout b73005c        # the last commit that carries their code
# backend/pyproject.toml at that commit pins the numpy/pandas/sklearn versions
# the C5 artefacts were pickled with; those pins also survive on main.
poetry install && poetry run ensemble-compute --date YYYY-MM-DD
```

`pl_model_artifact` still holds the 38 frozen artefacts, and the input tables are
untouched, so the run is reproducible against prod through the IAP bastion. Build
and push the image from that commit if you need it to run as a Cloud Run job
again.

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
