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
19:15 UTC  cc-compute-indicators         → pl_derived_indicators + pl_dashboard_gauge T
22:10 UTC  cc-ice-cot-eu-scraper         → pl_cot_eu_weekly (own report_date)

Phase B — eve of T+next, agent-gated; ALL writes keyed to data_date = T:
19:00 UTC  cc-meteo-agent        → pl_weather_observation T                    [INDEPENDENT]
19:05 UTC  cc-press-review-agent → pl_fundamental_article + pl_article_segment T
19:45 UTC  cc-roll-watchdog      → Sentry nudge only, writes nothing
19:50 UTC  cc-regime-shadow      → pl_regime_shadow + pl_judge_shadow
                                  + adapter row in pl_indicator_daily T   ← THE SERVED DECISION
19:55 UTC  cc-regime-brief       → UPDATE narrative on that row (fr+en)
                                  + Drive <T>-CompassBrief-Regime{,-EN}.txt

Publication gate — every 30 min, 20:00 → 09:30 next morning:
           cc-publish-session    → pl_session_release (atomic dashboard flip)
```

> **Retired 2026-08-19.** `cc-ensemble-compute`, `cc-daily-analysis`,
> `cc-ensemble-explainer`, `cc-compass-brief`, `cc-compass-brief-ensemble` and
> `cc-ensemble-bootstrap-artifacts` no longer exist — schedulers destroyed, code
> deleted, Cloud Run jobs deleted. **Executing them now fails with "job not
> found."** If you are following an old copy of this runbook, stop. Replay
> procedure for their historical rows:
> [docs/archive/pipelines/](../archive/pipelines/#how-to-replay-one-of-them-now).

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
           │
           ├─► compute_indicators ─► pl_derived_indicators + pl_dashboard_gauge
           │        (the DASHBOARD GAUGES and the S1/R1 pivots — NOT the decision)
           │
           └─► v_contract_data_chained ─► regime_shadow (raw prices, self-computed features)

Phase B (eve of T+next, all writes keyed to T) — ONE track:
press_review ─► pl_fundamental_article + pl_article_segment ─┐
meteo        ─► pl_weather_observation ─────────────────────┤
                                                            ▼
                              regime_shadow  (one execution, three steps)
                                L1+L2 regime → pl_regime_shadow
                                L3 judge     → pl_judge_shadow      (reads press + meteo)
                                adapter row  → pl_indicator_daily   ← SERVED
                                                            │
                                                            ▼
                              regime_brief ─► narrative on that row + Drive .txt
                                                            │
                                                            ▼
                              publish_session ─► pl_session_release
```

**Key rule**: if an upstream job fails, all downstream jobs that ran will have **degraded or wrong** input. They must be re-executed in order after the upstream is fixed.

**Two dependency facts that are counter-intuitive and change the cascade:**

1. **`compute_indicators` does NOT feed the decision.** Regime self-computes its
   features from raw prices via `v_contract_data_chained` and never reads
   `pl_derived_indicators`. A `compute_indicators` failure blanks the **gauges**
   and the S1/R1 pivots (which the intraday monitor and the brief's "À surveiller"
   block read) — the signal itself is unaffected. Do not re-run regime for it.

2. **The judge reads the two agents, so they DO feed the decision.** press_review
   and meteo are inputs to the L3 overlay. A failure there does not just empty a
   dashboard section — it changes what the judge sees, and therefore possibly the
   published call. Re-run `regime-shadow` after repairing either.

⚠️ **The judge's prior-brief window reads regime's own adapter rows at J-1 / J-2
and fails loud if they are missing.** A gap in the adapter rows kills the *next*
night's run, not only its own. Any regime backfill must write adapter rows — it
does, `--no-judge` included.

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
> | press-review · meteo-agent · regime-shadow · regime-brief | `--session-date` | **`T`** | the session being recovered = the row date every job writes. `target_date = next_session(T)` is derived internally for prompt framing only — never operator-facing. |
>
> Add `--force` to overwrite the degraded rows the failed run already left behind
> (and to bypass the eve-of-trading-day gate). `regime-brief` has **no `--force`**:
> it overwrites the narrative on the served row unconditionally.
>
> **⚠️ `--args` REPLACES the job's ENTIRE default arg list.** Replicate the defaults
> from `deploy.yml` and only ADD your date/force flags — in particular
> **`--language,both`** on press-review, meteo and regime-brief. Omitting it silently
> regenerates the **fr row only** and the EN row/brief for that session never exists
> (bitten 2026-07-22; repaired with a `--language,en` re-run).
>
> Worked example — backfilling Friday `2026-06-19` (every job takes the SAME session date):
> ```bash
> R="--region=europe-west9 --project=cacaooo --wait"
> gcloud run jobs execute cc-press-review-agent $R --args="press-review,--language,both,--session-date,2026-06-19,--force"
> gcloud run jobs execute cc-meteo-agent        $R --args="meteo-agent,--language,both,--session-date,2026-06-19,--force"
> gcloud run jobs execute cc-regime-shadow      $R --args="regime-shadow-compute,--session-date,2026-06-19,--force"
> gcloud run jobs execute cc-regime-brief       $R --args="regime-brief,--language,both,--session-date,2026-06-19"
> ```
> Verify each job SUCCEEDED before launching the next — never cascade onto a re-failed producer.

#### Scenario A — barchart_scraper failed

Root of the graph. No OHLCV row → no gauges, and regime has no prices to compute
from. Re-run Phase A, then the whole of Phase B.

```bash
R="--region=europe-west9 --project=cacaooo --wait"
# Phase A — sequential, wait for each
gcloud run jobs execute cc-barchart-scraper           $R
gcloud run jobs execute cc-ice-stocks-scraper         $R
gcloud run jobs execute cc-cftc-scraper               $R
gcloud run jobs execute cc-barchart-stocks-eu-scraper $R
gcloud run jobs execute cc-compute-indicators         $R
# Phase B
gcloud run jobs execute cc-regime-shadow              $R
gcloud run jobs execute cc-regime-brief               $R
```

#### Scenario B — meteo_agent failed

Weather is an input to the **L3 judge**, not just a dashboard section. Re-running
it can change the published call, so regime must follow.

```bash
R="--region=europe-west9 --project=cacaooo --wait"
gcloud run jobs execute cc-meteo-agent    $R --args="meteo-agent,--language,both,--force"
gcloud run jobs execute cc-regime-shadow  $R
gcloud run jobs execute cc-regime-brief   $R
```

#### Scenario C — press_review_agent failed

Same shape as B: the judge reads the press review. It is also the one input where
a *silent* degradation is plausible — the agent can succeed while missing a market-
moving story, which no job will flag (see the 2026-07-31 COCOBOD case).

```bash
R="--region=europe-west9 --project=cacaooo --wait"
gcloud run jobs execute cc-press-review-agent $R --args="press-review,--language,both,--force"
gcloud run jobs execute cc-regime-shadow      $R
gcloud run jobs execute cc-regime-brief       $R
```

#### Scenario D — compute_indicators failed

**Does not invalidate the decision.** Regime self-computes from raw prices and
never reads `pl_derived_indicators`. What breaks is the gauge row, the S1/R1
pivots the brief's "À surveiller" block and the intraday monitor read.

```bash
R="--region=europe-west9 --project=cacaooo --wait"
gcloud run jobs execute cc-compute-indicators $R
# Only if the brief already ran WITHOUT pivots — it embeds them at render time:
gcloud run jobs execute cc-regime-brief       $R
```
To repair only the gauges over a window, without touching any algorithm row:
`poetry run compute-indicators --all-contracts --stage gauges --gauge-days N`.

#### Scenario E — regime_shadow failed (no decision at all)

The serious one: **no adapter row means no signal on the dashboard**, and
`cc-regime-brief` will fail loud right after with nothing to enrich. There is no
cross-algorithm fallback — ensemble and legacy stopped writing on 2026-08-18.

```bash
R="--region=europe-west9 --project=cacaooo --wait"
gcloud run jobs execute cc-regime-shadow $R --args="regime-shadow-compute,--force"
gcloud run jobs execute cc-regime-brief  $R
```

If only the **judge leg** died (regime rows exist, `pl_judge_shadow` empty), re-run
that leg alone rather than recomputing the regime:

```bash
poetry run judge-shadow-compute --session-date <T>
```

⚠️ Leaving a hole in the adapter rows breaks the **next** night too: the judge's
prior-brief window reads J-1 / J-2 and fails loud when they are missing. Backfill
the gap even if the session itself no longer matters.

#### Scenario F — regime_brief failed (decision present, no prose)

The dashboard shows the signal, the gauges and the tiles, but the Recommandation
tabs and the "À surveiller" sidebar stay empty, and no `.txt` reaches Drive — so
no NotebookLM audio, and `cc-publish-session` will hold the session back.

```bash
gcloud run jobs execute cc-regime-brief --region=europe-west9 --project=cacaooo --wait \
  --args="regime-brief,--language,both"
```

A `NarrationError` about line count or the `>` marker is the **guard working as
intended**, not a flake: the model returned prose the dashboard cannot lay out into
three tabs. Re-run once; if it repeats, the prompt or the model changed — fix that,
do not loosen the guard.

#### Scenario G — publish_session never released the day

Data and audio are both present but the dashboard still shows yesterday. The gate
runs every 30 min until 09:30 UTC and has a morning fallback that releases
data-only, so a late audio cannot freeze the dashboard indefinitely. Diagnosis
first — check `pl_session_release` — then:

```bash
gcloud run jobs execute cc-publish-session --region=europe-west9 --project=cacaooo --wait
```
See [session-publish-gate.md](./session-publish-gate.md).

### Step 5 — Verify recovery

1. **Dashboard**: open `https://app.com-compass.com/dashboard`, confirm today's data is present (signal, gauges, press review, weather, audio)
2. **DB spot-check** (via bastion tunnel — see [db-sync-from-gcp.md](./db-sync-from-gcp.md)):

```sql
SELECT
  (SELECT MAX(date) FROM pl_contract_data_daily)     AS market_max,
  (SELECT MAX(date) FROM pl_indicator_daily)         AS indicator_max,
  (SELECT MAX(date) FROM pl_fundamental_article)     AS press_max,
  (SELECT MAX(article_date) FROM pl_article_segment) AS segment_max,
  (SELECT MAX(date) FROM pl_weather_observation)     AS weather_max,
  (SELECT MAX(date) FROM pl_regime_shadow)           AS regime_max,
  (SELECT MAX(date) FROM pl_judge_shadow)            AS judge_max,
  (SELECT MAX(session_date) FROM pl_session_release) AS released_max;
```

`pl_orchestrator_decision` is **not** in this list on purpose: it froze on
2026-08-18 and its `MAX(date)` will never move again. Reading it as a freshness
check would report a permanent failure.

All eight should show the latest session date. **When backfilling a PAST session** (today's
rows may already exist and dominate `MAX`), check that specific session `<T>` instead:

```sql
SELECT 'article'  AS t, COUNT(*) FROM pl_fundamental_article WHERE date='<T>' AND is_active
UNION ALL SELECT 'segment', COUNT(*) FROM pl_article_segment WHERE article_date='<T>'
UNION ALL SELECT 'weather', COUNT(*) FROM pl_weather_observation WHERE date='<T>'
UNION ALL SELECT 'regime',  COUNT(*) FROM pl_regime_shadow    WHERE date='<T>'
UNION ALL SELECT 'judge',   COUNT(*) FROM pl_judge_shadow     WHERE date='<T>';
```

The **adapter rows** are what the dashboard actually serves — check them explicitly,
in both languages, and check the prose landed:

```sql
SELECT i.language, i.final_indicator, i.confidence_score,
       LEFT(i.conclusion, 60) AS conclusion_head, i.eco IS NOT NULL AS has_eco
FROM pl_indicator_daily i
JOIN pl_algorithm_version v ON v.id = i.algorithm_version_id
WHERE i.date = '<T>' AND v.name = 'regime'
ORDER BY i.language;
```

Two rows (`fr`, `en`), both with a non-empty `conclusion` and `eco`. An empty
`conclusion` with a present `final_indicator` = Scenario F: the decision landed,
the brief did not. A local helper for the tunnel + queries lives at
`.local/db-prod.sh` (gitignored).

3. **Sentry**: confirm no new errors after relaunch
4. **Audio**: confirm `<YYYYMMDD>-CompassAudio-Regime.<ext>` (and `-Regime-EN`) exists in the Drive folder. ⚠️ Re-running `cc-regime-brief` regenerates the `.txt` **only** — NotebookLM voicing is a **separate manual step**. If the degraded brief was already voiced, re-voice it by hand; the brief re-run does NOT refresh the audio, and `cc-publish-session` waits on the audio.

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
- Consumers (dashboard, brief) MAY degrade gracefully on missing input, but producers must NEVER produce partial output silently. Note the asymmetry that the flip introduced: with one track left there is **no cross-algorithm fallback** — a failed producer is a visibly empty dashboard section, not a stale-but-plausible one. That is the intended behaviour.

## Related files

- Fail-loud philosophy: `.claude/rules/pipeline-error-handling.md`
- Pipeline continuity: `.claude/rules/pipeline-continuity.md`
- Cloud Run Jobs Terraform: `infra/terraform/cloud_run_jobs.tf`
- Cloud Scheduler Terraform: `infra/terraform/cloud_scheduler.tf`
- Job entrypoints: `backend/scripts/<agent>/main.py`
