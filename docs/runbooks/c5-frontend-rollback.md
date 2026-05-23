# C5 Frontend Rollback — `feat/c5-frontend-integration`

> Branch shipped to prod on 2026-05-23. Merge SHA: `<TO_BE_STAMPED_POST_MERGE>`.
> If something breaks in prod, this is the page that gets you back to the previous UI.

## TL;DR

```bash
# From a clean main checkout
git revert -m 1 <MERGE_SHA>
git push origin main
# CI/CD redeploys frontend + backend with the old configuration.
```

No DB cleanup needed. No migrations to undo.

## What this revert restores

- Old `SignalHero` (no Conviction Breakdown, no source_algorithm badge, no Pourquoi décision)
- Old `MarketAnalysis` (5 technical gauges only, no Macro/FX + Positioning sub-blocks)
- Old `LiveSignalStrip` (no FX DXY / Stock EU / COT MM cells)
- Old `dashboard-page.tsx` (no MastheadPulse strip, no DecisionExplainerCard)
- `cc-daily-analysis` falls back to the legacy code path (writes to the legacy
  `pl_indicator_daily` row, drives decision from composite `final_indicator`).
- The temporary debug-string filter in `get_latest_recommendations` goes away.

## What stays in place (additive, no harm)

- The 4 new dashboard endpoints (`/macro-panel`, `/positioning`,
  `/ensemble-diagnostics`, `/specialist-votes`) — they keep responding 200 but
  nothing on the frontend consumes them.
- `get_algorithm_version_for_date()` resolver in `contract_resolver.py` — pure
  utility, no caller depends on it post-revert.
- The Pydantic schemas with `source_algorithm` field — older clients ignore it.

No further cleanup needed.

## DB & migrations

This branch did NOT add any Alembic migrations, tables, or columns. The
ensemble row (`pl_orchestrator_decision`, `pl_specialist_prediction`,
`pl_indicator_daily` with `algorithm_version_id = ensemble_v1_softgate_wrapper`)
was already in production before this branch — pre-existing infrastructure.

## Cron jobs

- `cc-ensemble-compute` 19:18 UTC → unchanged.
- `cc-daily-analysis` 19:20 UTC → reverts to legacy alignment (no change to
  schedule, no flag change needed).
- `cc-compass-brief` 19:30 UTC → reads `pl_indicator_daily.conclusion`, will
  pick the legacy row's conclusion again (the ensemble row's conclusion
  remains the debug string until the next ensemble narrative refactor).

## Post-revert smoke check

```bash
# Backend
curl https://api.com-compass.com/health
# → 200

curl -sf -H "Authorization: Bearer <token>" \
  "https://api.com-compass.com/v1/dashboard/position-status?target_date=2026-05-22"
# → 200, JSON has position + ytd_performance (source_algorithm key may exist
# but is ignored by the old frontend)

# Frontend
open https://app.com-compass.com/dashboard
# → SignalHero renders with old layout (no breakdown, no audit card, no pulse strip)
```

If `cc-daily-analysis` has already run with the new code path tonight, the
ensemble row carries the new narrative. After revert, on the next run it will
write to the legacy row instead. There is no data loss either way — the two
rows coexist.

## If revert itself fails

The revert can fail if there are subsequent commits on main that touch the
same files. In that case, prefer a targeted revert of the merge with conflict
resolution rather than a force-push. Worst case: branch off main, manually
revert the file state, open a "revert PR".

## Forward-fix vs revert

Prefer forward-fix when the issue is localized (e.g., one component crashing
on a specific date). Reserve revert for systemic breakage (login broken,
dashboard unreachable, brief job failing nightly).

## Owners

- Frontend: Hedi
- Backend daily-analysis refactor: Hedi
- DevOps deploy: GitHub Actions (deploy.yml)
