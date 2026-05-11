# Seasonal Score Backfill — Operational Runbook

## When to use this runbook

Run this every time a cocoa season ends, to score it in `pl_seasonal_score` and refresh the dashboard's "Campagne X-Y" card. The daily meteo agent does **not** auto-score completed seasons — `--bootstrap-memory` must be triggered manually after each season transition.

Symptom: a season bar in the weather card shows `—` instead of a numeric score, while its end date is in the past.

## Schedule — Recurring task

The cocoa campaign runs **Oct Y → Sep Y+1**. Run this runbook on or after each "Trigger date" below:

| Season | Months | Ends | Trigger date | Notes |
|---|---|---|---|---|
| Petite Saison Pluies | Sep-Nov | Nov 30 | Dec 1 | Start of next campaign's saison_seche |
| Saison Sèche | Dec-Mar | Mar 31 | Apr 1 | Cross-year season |
| Transition Pluies | Apr | Apr 30 | May 1 | Single-month season |
| Grande Saison Pluies | May-Jul | Jul 31 | Aug 1 | |
| Petite Saison Sèche | Aug | Aug 31 | Sep 1 | Last season of campaign |

**Concrete next-up dates (campaign 2025-2026 and beyond):**

| Saison | Trigger date | Status |
|---|---|---|
| Transition Pluies (2026) | 2026-05-01 | Done 2026-05-07 |
| Grande Saison Pluies (2026) | 2026-08-01 | Pending |
| Petite Saison Sèche (2026) | 2026-09-01 | Pending |
| Petite Saison Pluies (campaign 2026-2027) | 2026-12-01 | Pending |
| Saison Sèche (campaign 2026-2027) | 2027-04-01 | Pending |

Set a recurring calendar reminder on the 1st of these months.

## Pre-requisites

- `gcloud` CLI authenticated against project `cacaooo` (`gcloud auth login`)
- IAP bastion access (see [db-sync-from-gcp.md](db-sync-from-gcp.md) for tunnel setup and credentials)
- Open-Meteo Archive API reachable (lag ~5 days behind today — trigger date Day 1 of next month is always safe)

## Procedure

### Step 1 — Trigger the bootstrap on Cloud Run

```bash
gcloud run jobs execute cc-meteo-agent \
  --region=europe-west9 \
  --project=cacaooo \
  --args="meteo-agent,--bootstrap-memory" \
  --wait
```

Expected runtime: ~30 seconds. The job calls `bootstrap_campaign()` which:

- Computes `get_completed_seasons(today)` for the current campaign
- For each season, fetches Open-Meteo Archive data (precip, ET0, Tmax) for all 6 locations
- Computes a deterministic 1.0–5.0 score per location based on deviation from seasonal norms
- UPSERTs into `pl_seasonal_score` (idempotent — re-running produces no extra rows)

Verify completion:

```bash
gcloud run jobs executions list \
  --job=cc-meteo-agent \
  --region=europe-west9 \
  --project=cacaooo \
  --limit=1
```

Status must be `Succeeded`. If `Failed`, see Troubleshooting below.

### Step 2 — Inspect the logs

```bash
EXEC_NAME=$(gcloud run jobs executions list \
  --job=cc-meteo-agent --region=europe-west9 --project=cacaooo \
  --limit=1 --format='value(name)')

gcloud logging read \
  "resource.type=\"cloud_run_job\" labels.\"run.googleapis.com/execution_name\"=\"$EXEC_NAME\"" \
  --project=cacaooo --limit=200 --format='value(textPayload)' --order=asc
```

Confirm each season prints 6 location lines and `Season <name>: 6 scores written`. Check for outlier scores (e.g. `0.0/5` or `5.0/5` everywhere) — flag for follow-up if anomalous vs the season's expected climate.

### Step 3 — Clean up the in-progress season

`bootstrap_campaign()` also writes 6 rows for the **currently in-progress** season with `months_covered` suffixed `(en cours)`. These are based on a tiny window (1–5 days) and would mislead the dashboard. Remove them:

Open the bastion tunnel ([db-sync-from-gcp.md](db-sync-from-gcp.md)):

```bash
gcloud compute ssh cc-bastion --zone europe-west9-a \
  --tunnel-through-iap --project cacaooo \
  -- -N -L 5434:10.119.160.3:5432
```

Then in another terminal (substitute the current campaign string):

```sql
-- psql -h 127.0.0.1 -p 5434 -U cc_app -d commodities_compass

BEGIN;

-- Inspect rows about to be deleted
SELECT season_name, location_name, months_covered, score
FROM pl_seasonal_score
WHERE campaign='2025-2026' AND months_covered LIKE '%en cours%'
ORDER BY season_name, location_name;

-- Delete (expect 6 rows)
DELETE FROM pl_seasonal_score
WHERE campaign='2025-2026' AND months_covered LIKE '%en cours%';

-- Final state — should show only fully completed seasons
SELECT season_name, COUNT(*) AS rows, ROUND(AVG(score)::numeric, 2) AS avg_score
FROM pl_seasonal_score
WHERE campaign='2025-2026'
GROUP BY season_name
ORDER BY MIN(start_date);

COMMIT;
```

If the inspection looks wrong, `ROLLBACK;` instead of `COMMIT;`.

### Step 4 — Verify the dashboard

1. Open `https://app.com-compass.com/dashboard`
2. Scroll to the "Campagne YYYY-YYYY" card
3. The newly-completed season's bar must now show a numeric score (no longer `—`)
4. The "Santé X.X/5" badge is the average over all rows in `pl_seasonal_score` for the campaign — verify it matches the SQL `AVG(score)` from Step 3
5. Per-location diagnostics (Daloa/Kumasi/...) should reflect the new season's contribution

If the dashboard still shows `—`, hard-refresh (Cmd+Shift+R) — React Query has a 24h stale time on weather data ([useDashboard.ts](../../frontend/src/hooks/useDashboard.ts)).

## Troubleshooting

### Job fails with `httpx.HTTPStatusError` on Open-Meteo

Open-Meteo Archive is occasionally rate-limited or temporarily down. Wait 10 min and re-run Step 1. Per [pipeline-error-handling.md](../../.claude/rules/pipeline-error-handling.md), no auto-retry — manual relaunch is the recovery path.

### Score looks aberrant for one location

Compare `total_precip_mm` against the season's norm in `_PRECIP_30D_NORMS` ([backend/scripts/meteo_agent/seasonal_memory.py](../../backend/scripts/meteo_agent/seasonal_memory.py)). If the score is mathematically correct but the underlying climate norm is stale, that's a separate code change (not a backfill issue) — open a ticket to refine norms.

### Step 3 SQL deletes 0 rows

That means the bootstrap didn't write an "en cours" snapshot for the current season. Check the Step 2 logs — the in-progress season may have been skipped if `target_date - 1 day < season.start_date` (e.g., bootstrap run on the very 1st of the month before any data exists). In that case nothing to clean up — proceed to Step 4.

### `saison_seche` score changed slightly after re-bootstrap

UPSERT recomputes from Open-Meteo Archive each time. Tiny deltas (±0.1) are normal — the underlying weather data is stable historical, but `compute_score()` rounds to 0.5 increments and small drifts at threshold boundaries can flip a tier. Acceptable. If the delta is >0.5, investigate norm changes.

### `harmattan_days` reset on saison_seche after re-bootstrap

Bootstrap re-fetches Harmattan data and overwrites `harmattan_days` ([seasonal_memory.py](../../backend/scripts/meteo_agent/seasonal_memory.py) `compute_and_store_season` → `write_seasonal_scores`). The recomputed value should match the daily-incremented value (both count the same NE-wind + low-RH days from Open-Meteo). If they diverge significantly, check the daily Harmattan check ([main.py](../../backend/scripts/meteo_agent/main.py) Step 6) for missed days.

## Rollback

Bootstrap is non-destructive (UPSERT, no schema change). Rollback is rarely needed.

If a bad bootstrap wrote nonsensical scores (e.g., norm change deployed by mistake before the run), restore the affected season from a logical backup of `pl_seasonal_score` or re-run the previous good code revision's bootstrap.

To remove the most recent bootstrap entirely (e.g., scored too early, before season's actual end):

```sql
DELETE FROM pl_seasonal_score
WHERE campaign='<campaign>' AND season_name='<season>';
```

Then re-run on the correct date.

## Background

### Why isn't this automated?

The daily meteo agent's primary job is the LLM-generated weather observation written to `pl_weather_observation`. Seasonal scoring is a side-channel concern that runs on a different cadence (~5 times per year). Adding it to the daily run would:

- Spend Open-Meteo API calls daily for no benefit in steady state
- Couple two unrelated pipelines (observation freshness vs. season completeness)

A dedicated trigger (e.g., a Cloud Scheduler entry on the 1st of each month invoking `cc-meteo-agent --bootstrap-memory`) is the correct long-term solution but has not been prioritized. Until then: this runbook + calendar reminders.

### Why delete the "en cours" rows?

`get_completed_seasons()` ([seasonal_memory.py](../../backend/scripts/meteo_agent/seasonal_memory.py)) returns both fully-complete seasons AND the current in-progress one (suffixed `(en cours)`). The in-progress score is computed on a 1–5 day window (Open-Meteo Archive lags ~5 days), making it statistically meaningless and visually misleading on the dashboard. The product decision is to show `—` until a season is fully complete.

### What if I want a live score for the current season?

Out of scope for this runbook. Would require:

- Extending `compute_and_store_season` to flag rows as "preliminary"
- Frontend distinguishing preliminary from final scores (different bar style)
- Daily refresh of the in-progress row (~6 extra Open-Meteo calls/day)

Open a feature request if the trader asks for it.

## Related files

- CLI entry: `backend/scripts/meteo_agent/main.py` (`_run_bootstrap()`)
- Computation: `backend/scripts/meteo_agent/seasonal_memory.py` (`bootstrap_campaign()`, `compute_and_store_season()`, `compute_score()`)
- Season profiles: `backend/scripts/meteo_agent/config.py` (`SEASONAL_PROFILES`)
- DB schema: `backend/app/models/pipeline.py` (`PlSeasonalScore`)
- Dashboard service: `backend/app/services/weather_service.py` (`compute_campaign_health()`, `build_season_statuses()`)
- Frontend card: `frontend/src/components/weather-update-card.tsx` (`CampaignSection()`)
- Bastion tunnel setup: [db-sync-from-gcp.md](db-sync-from-gcp.md)

## Changelog

- **2026-05-07** — Initial run for Transition Pluies (April 2026). Score 4.6/5 average, Santé global stable at 4.5/5.
