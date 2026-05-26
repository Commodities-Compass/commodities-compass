# Pipeline Failure Recovery — Operational Runbook

## When to use this runbook

Use when one or more nightly pipeline jobs fail. Pipeline jobs are configured **fail-loud, no auto-retry** (see `.claude/rules/pipeline-error-handling.md`) — a failure means the job exited with a non-zero code and will NOT retry on its own. Manual intervention is the recovery path.

**Trigger signals**:
- Sentry alert from a Cloud Run Job
- Dashboard missing today's data (decision, indicators, press review, weather)
- `gcloud run jobs executions list` shows `Failed` status
- Compass brief audio missing for the day

## Pipeline schedule and dependencies

Reference for sequencing recovery actions. **P2b split**: Phase A is market-data driven and runs on weekday close (T); Phase B is calendar-aware and runs every evening, agent-gated on `is_eve_of_trading_day()` — writes tagged to the upcoming session (T+next).

```
Phase A — weekday-only, writes tagged to session T:
19:00 UTC  cc-barchart-scraper      → pl_contract_data_daily T (OHLCV+IV)
19:05 UTC  cc-ice-stocks-scraper    → pl_contract_data_daily T (STOCK US)
19:05 UTC  cc-cftc-scraper          → pl_contract_data_daily T (COM NET US)
19:10 UTC  cc-barchart-stocks-eu-scraper → pl_contract_data_daily T (stock_eu_bags60kg)
19:15 UTC  cc-compute-indicators    → pl_derived_indicators + pl_indicator_daily T

Phase B — daily cron, agent-gated on eve-of-trading-day, writes tagged to T+next:
19:00 UTC  cc-meteo-agent           → pl_weather_observation T+next   [INDEPENDENT]
19:05 UTC  cc-press-review-agent    → pl_fundamental_article T+next
19:20 UTC  cc-daily-analysis        → pl_indicator_daily T+next (LLM, reads T from pl_contract_data_daily)
19:30 UTC  cc-compass-brief         → Drive YYYYMMDD-CompassBrief.txt (YYYYMMDD = T+next)
```

**Phase B skip behaviour** (Sentry interprets as success, no alert):
- Friday eve: tomorrow=Saturday → skip
- Saturday eve: tomorrow=Sunday → skip
- Sunday eve: tomorrow=Monday → FIRE, target = Monday
- Mon eve when Tue is a holiday: tomorrow=Tue-holiday → skip; runs again on holiday eve for Wed

To force-rerun Phase B for a specific session date:
```bash
gcloud run jobs execute cc-press-review-agent --region=europe-west9 --project=cacaooo \
  --args="press-review,--target-date,2026-05-26,--force"
```

### Dependency graph

```
barchart ──┬─► ice_stocks (UPDATE same row)
           ├─► cftc (UPDATE same row)
           ├─► press_review (needs CLOSE)
           └─► compute_indicators ─► daily_analysis ─► compass_brief
                                          ▲                ▲
meteo ────────────────────────────────────┘                │
press_review ──────────────────────────────────────────────┘
```

**Key rule**: if an upstream job fails, all downstream jobs that ran will have **degraded or wrong** input. They must be re-executed in order after the upstream is fixed.

## Procedure

### Step 1 — Identify the failure

```bash
# List recent executions across all jobs
gcloud run jobs executions list \
  --region=europe-west9 \
  --project=cacaooo \
  --limit=20 \
  --format='table(metadata.name, metadata.creationTimestamp, status.conditions[0].type)'
```

Or check a specific job:

```bash
gcloud run jobs executions list \
  --job=<job_name> \
  --region=europe-west9 \
  --project=cacaooo \
  --limit=5
```

Then read the logs:

```bash
gcloud logging read \
  'resource.type="cloud_run_job" AND resource.labels.job_name="<job_name>" AND severity>=ERROR' \
  --project=cacaooo \
  --limit=50 \
  --format='value(timestamp,textPayload)'
```

Also check **Sentry** for the structured error context.

### Step 2 — Diagnose root cause

Common categories:

| Error type | Likely cause | Action |
|---|---|---|
| HTTP 4xx/5xx from external source | Upstream API down or schema changed | Patch the scraper / fetcher, redeploy |
| `JSONDecodeError` from LLM | Provider returned malformed output | Patch parser or prompt, redeploy |
| `IntegrityError` on insert | Unique constraint violation, contract mismatch | Investigate data; do NOT add `ON CONFLICT IGNORE` to mask it |
| Timeout > 5 min | LLM hang, slow source | Profile and split into smaller calls |
| `ImportError` / `AttributeError` | Bad deploy, missing dependency | Roll back the deploy or fix and redeploy |

**Do NOT** add silent retry logic. Per `.claude/rules/pipeline-error-handling.md`, fix the root cause and relaunch manually.

### Step 3 — Deploy fix (if code change required)

```bash
# Standard CI/CD deploy
git push origin main
# Wait for the deploy.yml workflow to finish (Actions tab on GitHub) — ~5 min for jobs
```

### Step 4 — Relaunch the failed job + downstream

Use the dependency graph to determine the cascade. Examples:

#### Scenario A — barchart_scraper failed

Cascade: everything downstream needs re-run.

```bash
# Sequential — wait for each to finish
gcloud run jobs execute cc-barchart-scraper       --region=europe-west9 --project=cacaooo --wait
gcloud run jobs execute cc-ice-stocks-scraper     --region=europe-west9 --project=cacaooo --wait
gcloud run jobs execute cc-cftc-scraper           --region=europe-west9 --project=cacaooo --wait
gcloud run jobs execute cc-press-review-agent     --region=europe-west9 --project=cacaooo --wait
gcloud run jobs execute cc-compute-indicators     --region=europe-west9 --project=cacaooo --wait
gcloud run jobs execute cc-daily-analysis         --region=europe-west9 --project=cacaooo --wait
gcloud run jobs execute cc-compass-brief          --region=europe-west9 --project=cacaooo --wait
```

#### Scenario B — meteo_agent failed

Cascade: only `daily_analysis` and `compass_brief` see meteo. Re-run them after fixing meteo.

```bash
gcloud run jobs execute cc-meteo-agent      --region=europe-west9 --project=cacaooo --wait
gcloud run jobs execute cc-daily-analysis   --region=europe-west9 --project=cacaooo --wait
gcloud run jobs execute cc-compass-brief    --region=europe-west9 --project=cacaooo --wait
```

#### Scenario C — press_review_agent failed

```bash
gcloud run jobs execute cc-press-review-agent  --region=europe-west9 --project=cacaooo --wait
gcloud run jobs execute cc-daily-analysis      --region=europe-west9 --project=cacaooo --wait
gcloud run jobs execute cc-compass-brief       --region=europe-west9 --project=cacaooo --wait
```

#### Scenario D — compute_indicators failed

```bash
gcloud run jobs execute cc-compute-indicators  --region=europe-west9 --project=cacaooo --wait
gcloud run jobs execute cc-daily-analysis      --region=europe-west9 --project=cacaooo --wait
gcloud run jobs execute cc-compass-brief       --region=europe-west9 --project=cacaooo --wait
```

#### Scenario E — daily_analysis failed

```bash
gcloud run jobs execute cc-daily-analysis  --region=europe-west9 --project=cacaooo --wait
gcloud run jobs execute cc-compass-brief   --region=europe-west9 --project=cacaooo --wait
```

#### Scenario F — compass_brief failed

```bash
gcloud run jobs execute cc-compass-brief  --region=europe-west9 --project=cacaooo --wait
```

### Step 5 — Verify recovery

1. **Dashboard**: open `https://app.com-compass.com/dashboard`, confirm today's data is present (signal, gauges, press review, weather, audio)
2. **DB spot-check** (via bastion tunnel — see [db-sync-from-gcp.md](./db-sync-from-gcp.md)):

```sql
SELECT
  (SELECT MAX(date) FROM pl_contract_data_daily)  AS market_max,
  (SELECT MAX(date) FROM pl_indicator_daily)      AS indicator_max,
  (SELECT MAX(date) FROM pl_fundamental_article)  AS press_max,
  (SELECT MAX(date) FROM pl_weather_observation)  AS weather_max;
```

All four should show today's session date.

3. **Sentry**: confirm no new errors after relaunch
4. **Audio**: confirm `<YYYYMMDD>-CompassAudio.<ext>` exists in the Drive folder (uploaded by the NotebookLM workflow downstream of compass_brief)

## What NOT to do

Per `.claude/rules/pipeline-error-handling.md`:

- **Do not add silent retry/fallback** to mask the issue. The fix is the root cause + manual relaunch
- **Do not run `--no-verify` / `--no-gpg-sign`** when committing the fix
- **Do not skip the cascade**. If an upstream job ran with bad input, downstream jobs are wrong even if they "succeeded"
- **Do not roll back blindly**. Diagnose first; the previous deploy may have fixed something else load-bearing

## Background

- Cloud Run Jobs are configured `--max-retries=0` — failure surfaces immediately
- Cloud Scheduler invocations also have `retryCount=0` — no automatic re-trigger on cron failures
- Each agent's failure mode differs — see the agent's `README.md` (when present) or its `main.py` for specific recovery hints
- Consumers (downstream jobs) MAY degrade gracefully on missing input (e.g. daily_analysis runs without weather), but producers must NEVER produce partial output silently

## Related files

- Fail-loud philosophy: `.claude/rules/pipeline-error-handling.md`
- Pipeline continuity: `.claude/rules/pipeline-continuity.md`
- Cloud Run Jobs Terraform: `infra/terraform/cloud_run_jobs.tf`
- Cloud Scheduler Terraform: `infra/terraform/cloud_scheduler.tf`
- Job entrypoints: `backend/scripts/<agent>/main.py`
