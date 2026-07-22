# Pipeline Failure Recovery — Operational Runbook

## When to use this runbook

Use when one or more nightly pipeline jobs fail. Pipeline jobs are configured **fail-loud, no auto-retry** (see `.claude/rules/pipeline-error-handling.md`) — a failure means the job exited with a non-zero code and will NOT retry on its own. Manual intervention is the recovery path.

**Trigger signals**:
- Sentry alert from a Cloud Run Job
- Dashboard missing today's data (decision, indicators, press review, weather)
- `gcloud run jobs executions list` shows `Failed` status
- Compass brief audio missing for the day

## Pipeline schedule and dependencies

Reference for sequencing recovery actions. **P2b split**: Phase A is market-data driven and runs on weekday close (session T). Phase B is calendar-aware and runs every evening, agent-gated on `is_eve_of_trading_day()`; a backfill passes `--session-date T` (the session to recover) and **every DB write is keyed to that `data_date = T`** — the SAME row date as Phase A. The pair `(target_date = next_session(T), data_date = T)` is resolved once in `scripts/db.py:resolve_phase_b_dates`; `target_date` frames prompts/filenames only. (Sunday eve fires for Monday's session and therefore writes the **Friday** rows; Sat/Sun eves themselves skip.)

```
Phase A — weekday close, writes keyed to session T (the day that just traded):
18:30 UTC  cc-fx-scraper                 → pl_external_indicator T (FX, ECB)
19:00 UTC  cc-barchart-scraper           → pl_contract_data_daily T (OHLCV+IV)
19:05 UTC  cc-ice-stocks-scraper         → pl_contract_data_daily T (STOCK US)
19:05 UTC  cc-cftc-scraper               → pl_contract_data_daily T (COM NET US)
19:10 UTC  cc-barchart-stocks-eu-scraper → pl_contract_data_daily T (stock_eu_bags60kg)
19:15 UTC  cc-compute-indicators         → pl_derived_indicators + pl_indicator_daily T
22:10 UTC  cc-ice-cot-eu-scraper         → pl_cot_eu_weekly (own report_date)

Phase B — eve of T+next, agent-gated; ALL writes keyed to data_date = T:
19:00 UTC  cc-meteo-agent            → pl_weather_observation T                [INDEPENDENT]
19:05 UTC  cc-press-review-agent     → pl_fundamental_article + pl_article_segment T
19:18 UTC  cc-ensemble-compute       → pl_orchestrator_decision + 14× pl_specialist_prediction + ensemble row in pl_indicator_daily T
19:20 UTC  cc-daily-analysis         → UPDATE legacy row in pl_indicator_daily T   (--algorithm-version legacy)
19:25 UTC  cc-ensemble-explainer     → UPDATE ensemble-row narrative in pl_indicator_daily T
19:30 UTC  cc-compass-brief          → Drive <T>-CompassBrief.txt              (filename keyed on data_date T)
19:35 UTC  cc-compass-brief-ensemble → Drive <T>-CompassBrief-Ensemble.txt
```

**Phase B skip behaviour** (Sentry interprets as success, no alert):
- Friday eve: tomorrow=Saturday → skip
- Saturday eve: tomorrow=Sunday → skip
- Sunday eve: tomorrow=Monday → FIRE, target = Monday
- Mon eve when Tue is a holiday: tomorrow=Tue-holiday → skip; runs again on holiday eve for Wed

To force-rerun Phase B for a specific session date:
```bash
gcloud run jobs execute cc-press-review-agent --region=europe-west9 --project=cacaooo \
  --args="press-review,--language,both,--session-date,2026-05-26,--force"
```

### Dependency graph

```
Phase A (market close, session T):
barchart ──┬─► ice_stocks / cftc / barchart_stocks_eu   (UPDATE the same OHLCV row)
           └─► compute_indicators ─► pl_derived_indicators + pl_indicator_daily T

Phase B (eve of T+next, all writes keyed to T) — TWO tracks, both consume press_review:
press_review ─► pl_fundamental_article + pl_article_segment
     │
     ├─► daily_analysis ─► compass_brief                          [LEGACY track]
     │        ▲
     │  meteo ┘
     │
     └─► ensemble_compute ─► ensemble_explainer ─► compass_brief_ensemble   [ENSEMBLE track]
              ▲  (reads pl_article_segment for the MacroEventLayer)
              │
   compute_indicators (pl_derived_indicators) + v_contract_data_chained
```

**Key rule**: if an upstream job fails, all downstream jobs that ran will have **degraded or wrong** input. They must be re-executed in order after the upstream is fixed. **press_review feeds BOTH tracks** — a press_review failure silently degrades the legacy narrative AND the ensemble MacroEventLayer (the ensemble decision is recomputed without the weekend/overnight news segment).

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

> **⚠️ Same-eve re-run vs backfilling a past session — get the date arg right.**
> The bare `gcloud run jobs execute <job> --wait` (no date args) relies on each job's
> default date derived from `today()`. That is correct **only if you re-run on the same eve**
> as the original cron. If you discover the failure the **next morning** (e.g. a Sunday-eve
> failure found Monday), the default targets the WRONG session — pass `--session-date T`
> so the rows land back on the failed session T.
>
> Date-arg convention (UNIFORM across every Phase-B job since the `--session-date`
> refactor — one flag, one value, `data_date` derivation centralized in
> `scripts/db.py:resolve_phase_b_dates`):
>
> | job(s) | flag | value to pass | meaning |
> |---|---|---|---|
> | press-review · ensemble-compute · daily-analysis · ensemble-explainer · compass-brief · compass-brief-ensemble | `--session-date` | **`T`** | the session being recovered = the row date every job writes. `target_date = next_session(T)` is derived internally for prompt framing only — never operator-facing. |
>
> Add `--force` to overwrite the degraded rows the failed run already left behind
> (and to bypass the eve-of-trading-day gate). daily-analysis also needs
> `--algorithm-version legacy` (pins the legacy row, leaves the ensemble row
> untouched). ensemble-compute: add `--historical` **only** if a contract roll
> happened between T and now (otherwise it resolves the wrong front-month).
>
> **⚠️ `--args` REPLACES the job's ENTIRE default arg list.** Replicate the defaults
> from `deploy.yml` and only ADD your date/force flags — in particular
> **`--language,both`** on press-review, meteo, daily-analysis, ensemble-explainer and
> compass-brief-ensemble. Omitting it silently regenerates the **fr row only** and the
> EN row/brief for that session never exists (bitten 2026-07-22; repaired with a
> `--language,en` re-run).
>
> Worked example — backfilling Friday `2026-06-19` (every job takes the SAME session date now):
> ```bash
> R="--region=europe-west9 --project=cacaooo --wait"
> gcloud run jobs execute cc-press-review-agent      $R --args="press-review,--language,both,--session-date,2026-06-19,--force"
> gcloud run jobs execute cc-ensemble-compute        $R --args="ensemble-compute,--session-date,2026-06-19,--force"
> gcloud run jobs execute cc-ensemble-explainer      $R --args="ensemble-explainer,--language,both,--session-date,2026-06-19,--force"
> gcloud run jobs execute cc-daily-analysis          $R --args="daily-analysis,--algorithm-version,legacy,--language,both,--session-date,2026-06-19,--force"
> gcloud run jobs execute cc-compass-brief           $R --args="compass-brief,--session-date,2026-06-19,--force"
> gcloud run jobs execute cc-compass-brief-ensemble  $R --args="compass-brief-ensemble,--language,both,--session-date,2026-06-19,--force"
> ```
> Verify each job SUCCEEDED before launching the next — never cascade onto a re-failed producer.

#### Scenario A — barchart_scraper failed

Root of the graph → re-run the Phase A chain, then the ENTIRE Phase B (both tracks).

```bash
R="--region=europe-west9 --project=cacaooo --wait"
# Phase A — sequential, wait for each
gcloud run jobs execute cc-barchart-scraper           $R
gcloud run jobs execute cc-ice-stocks-scraper         $R
gcloud run jobs execute cc-cftc-scraper               $R
gcloud run jobs execute cc-barchart-stocks-eu-scraper $R
gcloud run jobs execute cc-compute-indicators         $R
```
Then run the **full Phase B cascade from Scenario C** (press_review → ensemble_compute → ensemble_explainer → daily_analysis → both briefs).

#### Scenario B — meteo_agent failed

meteo feeds the narrative jobs (daily_analysis legacy **and** ensemble_explainer) + both briefs. The ensemble DECISION (ensemble_compute) does not read weather, so it need not re-run.

```bash
R="--region=europe-west9 --project=cacaooo --wait"
gcloud run jobs execute cc-meteo-agent             $R
gcloud run jobs execute cc-ensemble-explainer      $R
gcloud run jobs execute cc-daily-analysis          $R --args="daily-analysis,--algorithm-version,legacy,--language,both,--force"
gcloud run jobs execute cc-compass-brief           $R
gcloud run jobs execute cc-compass-brief-ensemble  $R
```

#### Scenario C — press_review_agent failed

press_review feeds BOTH tracks → re-run the full Phase B cascade. **Same-eve** form below
(default dates). For a **next-day backfill**, use the explicit date args from the Step 4 ⚠️ note above.

```bash
R="--region=europe-west9 --project=cacaooo --wait"
gcloud run jobs execute cc-press-review-agent      $R   # writes article + segment
gcloud run jobs execute cc-ensemble-compute        $R   # re-reads segment into MacroEventLayer
gcloud run jobs execute cc-ensemble-explainer      $R
gcloud run jobs execute cc-daily-analysis          $R --args="daily-analysis,--algorithm-version,legacy,--language,both,--force"
gcloud run jobs execute cc-compass-brief           $R
gcloud run jobs execute cc-compass-brief-ensemble  $R
```

#### Scenario D — compute_indicators failed

`pl_derived_indicators` feeds BOTH daily_analysis (legacy) and ensemble_compute → re-run both tracks.

```bash
R="--region=europe-west9 --project=cacaooo --wait"
gcloud run jobs execute cc-compute-indicators      $R
gcloud run jobs execute cc-ensemble-compute        $R
gcloud run jobs execute cc-ensemble-explainer      $R
gcloud run jobs execute cc-daily-analysis          $R --args="daily-analysis,--algorithm-version,legacy,--language,both,--force"
gcloud run jobs execute cc-compass-brief           $R
gcloud run jobs execute cc-compass-brief-ensemble  $R
```

#### Scenario E — daily_analysis failed (legacy row only)

Legacy track only — the ensemble row is written by ensemble_explainer, untouched here.

```bash
R="--region=europe-west9 --project=cacaooo --wait"
gcloud run jobs execute cc-daily-analysis  $R --args="daily-analysis,--algorithm-version,legacy,--language,both,--force"
gcloud run jobs execute cc-compass-brief   $R
```

#### Scenario F — compass_brief failed

```bash
gcloud run jobs execute cc-compass-brief  --region=europe-west9 --project=cacaooo --wait
```

#### Scenario G — ensemble_compute failed

Cascade: ensemble_explainer + compass_brief_ensemble consume its output. Legacy track is unaffected.

```bash
R="--region=europe-west9 --project=cacaooo --wait"
gcloud run jobs execute cc-ensemble-compute        $R
gcloud run jobs execute cc-ensemble-explainer      $R
gcloud run jobs execute cc-compass-brief-ensemble  $R
```

If it fails with `KeyError: 'k'` or `pl_algorithm_version row missing` / `No specialist_model
rows`, the algorithm-version or artifact seeding is the root cause — see
[ensemble-failure-recovery.md](./ensemble-failure-recovery.md); do NOT just relaunch.

#### Scenario H — ensemble_explainer failed

Only compass_brief_ensemble depends on the narrative it writes. A fail-loud
`EnsembleRowMissingError` means ensemble_compute didn't populate the row first — fix that
(Scenario G) before re-running.

```bash
R="--region=europe-west9 --project=cacaooo --wait"
gcloud run jobs execute cc-ensemble-explainer      $R
gcloud run jobs execute cc-compass-brief-ensemble  $R
```

### Step 5 — Verify recovery

1. **Dashboard**: open `https://app.com-compass.com/dashboard`, confirm today's data is present (signal, gauges, press review, weather, audio)
2. **DB spot-check** (via bastion tunnel — see [db-sync-from-gcp.md](./db-sync-from-gcp.md)):

```sql
SELECT
  (SELECT MAX(date) FROM pl_contract_data_daily)     AS market_max,
  (SELECT MAX(date) FROM pl_indicator_daily)         AS indicator_max,
  (SELECT MAX(date) FROM pl_fundamental_article)     AS press_max,
  (SELECT MAX(article_date) FROM pl_article_segment) AS segment_max,
  (SELECT MAX(date) FROM pl_orchestrator_decision)   AS ensemble_max,
  (SELECT MAX(date) FROM pl_weather_observation)     AS weather_max;
```

All six should show the latest session date. **When backfilling a PAST session** (today's
rows may already exist and dominate `MAX`), check that specific session `<T>` instead:

```sql
SELECT 'article'    AS t, COUNT(*) FROM pl_fundamental_article    WHERE date='<T>' AND is_active
UNION ALL SELECT 'segment',    COUNT(*) FROM pl_article_segment       WHERE article_date='<T>'
UNION ALL SELECT 'orch',       COUNT(*) FROM pl_orchestrator_decision WHERE date='<T>'
UNION ALL SELECT 'specialist', COUNT(*) FROM pl_specialist_prediction WHERE date='<T>';
```

Both the `legacy` and `ensemble_v1_softgate_wrapper` rows in `pl_indicator_daily` for `<T>`
should carry a non-empty `eco` + `conclusion` (narratives re-enriched). A local helper for
the tunnel + queries lives at `.local/db-prod.sh` (gitignored).

3. **Sentry**: confirm no new errors after relaunch
4. **Audio**: confirm `<YYYYMMDD>-CompassAudio.<ext>` (legacy) / `<YYYYMMDD>-CompassAudio-Ensemble.<ext>` exists in the Drive folder. ⚠️ Re-running the brief jobs regenerates the `.txt` **only** — NotebookLM voicing is a **separate manual/external step**. If the degraded brief was already voiced, re-voice it by hand; the brief re-run does NOT refresh the audio.

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
