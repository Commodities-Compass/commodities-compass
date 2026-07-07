# Daily Pipeline — Flow

> **Scope**: the end-to-end nightly data flow. *When* each job fires (cron + gate), *what* it reads/writes, *how* failures propagate, and the fail-loud contract that governs the whole chain. This is the operational companion to [JOBS_AND_SCRAPERS.md](../JOBS_AND_SCRAPERS.md) (per-job catalog), [PIPELINE_LEGACY.md](../PIPELINE_LEGACY.md), and [PIPELINE_ENSEMBLE.md](../PIPELINE_ENSEMBLE.md) (business logic).

> **Source of truth**: cron schedules are defined in [`infra/terraform/scheduler.tf`](../../../infra/terraform/scheduler.tf) (`local.cron_jobs` map). Gate logic lives in [`backend/scripts/db.py`](../../../backend/scripts/db.py) (`is_eve_of_trading_day`, `get_next_session_date`, `get_previous_session_date`). All times **UTC**.

---

## 1 — The two-phase model (P2b)

The pipeline is split into two phases that differ on *trigger semantics* and *which session date the writes are keyed to*.

| | **Phase A — Market close** | **Phase B — Next-session refresh** |
|---|---|---|
| **Trigger** | Weekday-only cron (`* * 1-5`) | Daily cron (`* * *`) + in-agent gate `is_eve_of_trading_day()` |
| **Fires when** | Mon–Fri, regardless of holidays | Eve of any trading day (Sun eve → Mon, skips Fri/Sat eves & holiday eves) |
| **Row date written** | Session date **T** (the day trading happened) | `data_date` from `resolve_phase_b_dates()` — **also T**, the just-closed session |
| **Backfill flag** | per-scraper `--date` | uniform `--session-date T` (the row date to regenerate) across all 7 jobs |
| **`target_date` (derived)** | n/a (writes "today") | `next_session(T)` — drives prompt framing, filename, Sentry context only; never operator-facing |
| **Jobs** | scrapers + indicator engine | LLM agents + ensemble compute + briefs |

**The invariant**: every Phase A and Phase B write for a given session lands on the **same `date = T`**. Phase B derives its pair once via `scripts/db.py:resolve_phase_b_dates(args.session_date)` — `target_date` (T+next) is used only for *framing* and brief filenames, while every DB write is keyed to `data_date = T`. This is what keeps `pl_indicator_daily`, `pl_orchestrator_decision`, `pl_fundamental_article`, `pl_weather_observation` all consistent on one session date — which is exactly what the dashboard's `_parse_and_validate_date()` resolves from `display_date = next_trading_day(T)`.

**Why Phase B is daily, not weekday-only**: the old weekday-only Phase B left a ~60h Sun→Mon freshness gap. Now Phase B fires **Sunday eve** for Monday's session — and crucially, `cc-ensemble-compute` (19:18) reads the `pl_article_segment` that `cc-press-review-agent` (19:05) just wrote that same Sunday evening with `article_date = Friday`. That is the mechanism by which the ensemble decision for Friday's session incorporates news that broke over the weekend.

**Skip = success**: on Fri/Sat eve (and the eve of a holiday), the gate returns False, the agent exits 0, and Sentry cron monitors read that as a clean run — no false-positive alerts on weekends.

---

## 2 — Timeline (UTC weekdays)

```
Time   Job                                Phase  Track       Writes
─────  ─────────────────────────────────  ─────  ──────────  ────────────────────────────────────
13:00  cc-eca-grindings-scraper           gated  shared      pl_supply_demand_observation (ECA)
14:00  cc-nca-grindings-scraper           gated  shared      pl_supply_demand_observation (NCA)
16:00  cc-publication-calendar-watchdog   daily  shared      Sentry alert (no DB write)
18:30  cc-fx-scraper                      A      shared      pl_external_indicator.fx_*
19:00  cc-barchart-scraper                A      shared      pl_contract_data_daily (OHLCV+IV)  ◄── ROOT
19:00  cc-meteo-agent                     B      both        pl_weather_observation, pl_seasonal_score
19:05  cc-ice-stocks-scraper              A      shared      pl_stock_observation (region=us)
19:05  cc-cftc-scraper                    A      shared      pl_cot_us_weekly
19:05  cc-press-review-agent              B      both        pl_fundamental_article, pl_article_segment
19:10  cc-barchart-stocks-eu-scraper      A      shared      pl_stock_observation (region=eu)
19:15  cc-compute-indicators              A      shared      pl_derived_indicators, pl_indicator_daily (z)
19:18  cc-ensemble-compute                B      ENSEMBLE    14× specialist_prediction, orchestrator_decision, ind_daily(ENS)
19:20  cc-daily-analysis                  B      LEGACY      UPDATE pl_indicator_daily (legacy row, LLM)
19:25  cc-ensemble-explainer              B      ENSEMBLE    UPDATE pl_indicator_daily (ensemble row, LLM narrative)
19:30  cc-compass-brief                   B      LEGACY      Drive: YYYYMMDD-CompassBrief.txt
19:35  cc-compass-brief-ensemble          B      ENSEMBLE    Drive: YYYYMMDD-CompassBrief-Ensemble.txt
22:10  cc-ice-cot-eu-scraper              A      ENSEMBLE    pl_cot_eu_weekly
─────  ─────────────────────────────────  ─────  ──────────  ────────────────────────────────────
Monthly (20th, 22:00)  cc-enso-scraper            ENSEMBLE    pl_external_indicator.enso_*
On-demand (no cron)    cc-ensemble-bootstrap-artifacts  ENSEMBLE  pl_model_artifact (38 BYTEA rows)
```

**Count**: 19 scheduled jobs (`scheduler.tf` `local.cron_jobs`) + 1 manual-trigger job (`cc-ensemble-bootstrap-artifacts`, deployed without a scheduler) = 20 Cloud Run Jobs.

**Region note**: jobs execute in `europe-west9` (Paris). Cloud Scheduler does **not** support `europe-west9`, so the cron triggers live in `europe-west1` (Belgium) — scheduler location affects only where the trigger fires, not where the job runs.

### Gate / trigger taxonomy

| Trigger type | Cron pattern | Skip behaviour | Jobs |
|---|---|---|---|
| Phase A (weekday) | `M H * * 1-5` | Cron itself skips Sat/Sun; no holiday awareness | fx, barchart, ice-stocks, cftc, barchart-eu, compute-indicators, ice-cot-eu |
| Phase B (eve-gated) | `M H * * *` | `is_eve_of_trading_day()` → exit 0 on Fri/Sat/holiday eve | meteo, press-review, ensemble-compute, daily-analysis, ensemble-explainer, compass-brief, compass-brief-ensemble |
| Calendar-gated | `M H * * 1-5` | `ref_publication_calendar` window → exit 0 if no publi pending | eca-grindings, nca-grindings |
| Daily watchdog | `0 16 * * 1-5` | Always runs; non-zero exit only if rows overdue ≥ 21d | publication-calendar-watchdog |
| Monthly | `0 22 20 * *` | Fires the 20th (dow MUST be `*` — Cloud Scheduler ORs dom+dow) | enso-scraper |
| Manual | none | n/a | ensemble-bootstrap-artifacts |

---

## 3 — Dependency graph

```
                         ┌──────────────────────┐
  18:30                  │ cc-fx-scraper        │──► pl_external_indicator.fx_*
                         └──────────────────────┘            │
                                                             │
  PHASE A (market close, session T)                          │ (read by ensemble-compute)
  ════════════════════════════════════════════════════════  │  ════════════════════════
                                                             │
  19:00  ┌──────────────────────┐                            │
  ROOT   │ cc-barchart-scraper  │──► pl_contract_data_daily (OHLCV+IV) ◄── single root dependency
         └──────────┬───────────┘                  ▲ ▲ ▲
                    │  (independent enrichers, own report_date keys)
   19:05 ┌──────────┴───────┐  19:05 ┌────────────┐  19:10 ┌─────────────────┐
         │ cc-ice-stocks    │        │ cc-cftc    │        │ cc-barchart-eu  │
         │ → pl_stock_obs   │        │ → cot_us_wk│        │ → pl_stock_obs  │
         └──────────────────┘        └────────────┘        └─────────────────┘
                    │
   19:15 ┌──────────▼──────────────┐
         │ cc-compute-indicators   │──► pl_derived_indicators
         │  (all compute_enabled   │──► pl_indicator_daily (z-scores, 2 rows: legacy + ensemble)
         │   versions)             │
         └──────────┬──────────────┘
                    │
  PHASE B (next-session refresh, written to T)
  ════════════════════════════════════════════════════════════════════════════
                    │
   ┌────────────────┴─────────────────────────────────────────────────────────┐
   │ INDEPENDENT (no upstream within Phase B):                                  │
   │  19:00 cc-meteo-agent       ──► pl_weather_observation, pl_seasonal_score  │
   │  19:05 cc-press-review-agent──► pl_fundamental_article, pl_article_segment │
   └────────────────┬───────────────────────────┬──────────────────────────────┘
                    │ (derived_indicators)        │ (article_segment, weather)
   19:18 ┌──────────▼──────────────┐              │
         │ cc-ensemble-compute     │◄── pl_external_indicator (fx+enso), pl_cot_eu_weekly,
         │  reads: derived_ind,    │     pl_model_artifact, v_contract_data_chained
         │  article_seg, ext_ind,  │──► 14× pl_specialist_prediction
         │  cot_eu, model_artifact │──► pl_orchestrator_decision (soft-gate + wrapper diagnostics)
         └──────────┬──────────────┘──► pl_indicator_daily ENSEMBLE row (decision; eco/conf/dir = NULL)
                    │
   19:20 ┌──────────▼──────────────┐        19:25 ┌──────────────────────────┐
         │ cc-daily-analysis       │              │ cc-ensemble-explainer    │
         │  --algorithm-version    │              │  (thin wrapper on         │
         │   legacy                │              │   DBAnalysisEngine,       │
         │  UPDATE ind_daily LEGACY│              │   auto-align)             │
         │  (LLM decision)         │              │  UPDATE ind_daily ENSEMBLE│
         └──────────┬──────────────┘              │  (eco/conf/dir/conclusion)│
                    │                             └──────────┬───────────────┘
   19:30 ┌──────────▼──────────────┐        19:35 ┌──────────▼───────────────┐
         │ cc-compass-brief        │              │ cc-compass-brief-ensemble │
         │  reads is_active row    │              │  reads ENSEMBLE row       │
         │  → Drive (legacy .txt)  │              │  → Drive (-Ensemble.txt)  │
         └─────────────────────────┘              └───────────────────────────┘
                    │                                        │
                    └──────────► NotebookLM (overnight) ◄────┘
                         YYYYMMDD-CompassAudio[-Ensemble].{wav,m4a,mp4}

  OUT-OF-BAND (own cadence, feed ensemble-compute or watchdog):
   13:00 cc-eca-grindings ─┐ calendar-gated ─► pl_supply_demand_observation
   14:00 cc-nca-grindings ─┘ (dormant: briefs don't read it yet)
   16:00 cc-publication-calendar-watchdog ─► Sentry (silence detector)
   22:10 cc-ice-cot-eu-scraper ─► pl_cot_eu_weekly  (read by next eve's ensemble-compute)
   20th  cc-enso-scraper ─► pl_external_indicator.enso_*  (14d lag applied at compute-time)
```

### Critical-path observations

- **Single hard root**: `cc-barchart-scraper`. If OHLCV is missing, `compute-indicators` fails → both decision engines fail → no briefs. Everything else is either independent or degradable.
- **The two decision tracks fan out from `compute-indicators`** and never re-converge in the DB — they write to two distinct rows of `pl_indicator_daily` (legacy vs ensemble) and two distinct Drive files. The frontend picks per-date via `_resolve_algo_for_date()` (row-existence) and audio via `BRIEF_DEFAULT_VERSION`.
- **Stock/COT enrichers are decoupled** (since the 2026-05-27 refactor): they write their own tables (`pl_stock_observation`, `pl_cot_us_weekly`) keyed on the publisher's `report_date`, not on the OHLCV row. A failure there is tolerable — consumers forward-fill the last observation.
- **`cc-ensemble-compute` is sandwiched** between press-review (19:05, supplies fresh `pl_article_segment`) and daily-analysis (19:20, can read the ensemble row). The 13-minute gap after press-review is deliberate.

---

## 4 — Fail-loud policy

> Authoritative rule: [`.claude/rules/pipeline-error-handling.md`](../../../.claude/rules/pipeline-error-handling.md). Continuity contract: [`.claude/rules/pipeline-continuity.md`](../../../.claude/rules/pipeline-continuity.md).

### 4.1 Principle

Pipeline **producers** (scrapers, LLM agents, compute jobs) must **fail loud and stop**. The recovery path is always: **diagnose → fix root cause → manual relaunch**. Never auto-recover in a way that hides the original failure.

Infra enforces this: every Cloud Run Job is `--max-retries=0` and every Cloud Scheduler trigger is `retryCount=0`. A failure surfaces immediately and stays failed until a human relaunches it.

### 4.2 The four hard rules

1. **No automatic retry or provider fallback.** If an LLM returns bad JSON or an API 5xxs, the agent logs ERROR + reports to Sentry + exits non-zero. It does **not** retry the same provider, swap providers, or degrade to partial output silently. (Auto-retry masks flaky prompts and upstream regressions — fix the parser/prompt, not the symptom.)
2. **No silent error swallowing.** Every error is logged at ERROR with reproduction context, sent to Sentry with structured tags (`service`, `release`, `environment`), and reflected in a non-zero exit. Never `except: pass`. Never convert an error into a default value without logging.
3. **Graceful degradation is for CONSUMERS, not PRODUCERS.** A downstream consumer MAY run on incomplete input (e.g. `daily-analysis` proceeds with an empty press review, `compass-brief` renders "(pas de conclusion narrative)" when the LLM section is missing) — its input was incomplete, but it didn't itself fail. The **producer** that failed must NOT emit partial/fallback output: it either succeeds fully or fails fully.
4. **Manual relaunch is the recovery path.** Diagnose from logs/Sentry → fix root cause (code/prompt/parser/infra) → deploy if needed → relaunch the failed job **and every downstream job that ran with degraded input**, in dependency order.

### 4.3 Continuity contract (storage mirrors computation)

The engine is a math pipeline; the writer is a faithful mirror. **If a value is computed, store it as-is; if it's not yet computable, store NULL — never substitute a constant.** Zero is a valid result, not a placeholder. (Origin: momentum computed but never returned, writer hardcoded `0.0`, corrupted 3 prod rows.) Before any `INSERT`/`UPDATE`, every column must trace back to a computation return value or an explicit caller parameter — the only hardcode-OK exceptions are identity/metadata (`pipeline_name`, `status`), schema defaults, and intentional config-as-data coefficients.

### 4.4 Skip is not failure

Phase B gating (`is_eve_of_trading_day()` → exit 0) and calendar gating (no pending publication → exit 0) are **clean successes**. Sentry cron monitors treat exit 0 as a healthy run, so weekends, holidays, and the ~250 quarterly-publication no-op days per year produce no false alerts. The `publication-calendar-watchdog` exists precisely to convert *publisher silence* (which is otherwise indistinguishable from a clean gated skip) into a visible ERROR past a 21-day grace window.

---

## 5 — Failure cascade

When an upstream job fails, every downstream job that already ran did so on **degraded or wrong input** and must be re-executed in dependency order after the fix — even if those downstream jobs reported "success".

| Failed job | Downstream impact | Relaunch cascade |
|---|---|---|
| **cc-barchart-scraper** | ❌ Total: no OHLCV → compute-indicators fails → both decision engines fail → no briefs | barchart → ice-stocks → cftc → barchart-eu → compute-indicators → ensemble-compute → daily-analysis → ensemble-explainer → both briefs |
| **cc-compute-indicators** | ❌ ensemble-compute + daily-analysis fail (no indicators) | compute-indicators → ensemble-compute → daily-analysis → ensemble-explainer → both briefs |
| **cc-ensemble-compute** | ⚠️ ensemble-explainer fails (no ensemble row), compass-brief-ensemble fails. Legacy track intact. | ensemble-compute → ensemble-explainer → compass-brief-ensemble |
| **cc-daily-analysis** | ⚠️ legacy brief missing decision/eco. Ensemble track intact. | daily-analysis → compass-brief |
| **cc-ensemble-explainer** | ⚠️ ensemble brief has decision but NULL narrative. Legacy track intact. | ensemble-explainer → compass-brief-ensemble |
| **cc-press-review / cc-meteo** | ⚠️ Both briefs get an empty press/weather section (consumer degrades, doesn't fail) | press-review (or meteo) → daily-analysis → ensemble-explainer → both briefs |
| **cc-ice-stocks / cc-cftc / cc-barchart-eu** | ⚠️ Tolerable — independent tables since 2026-05-27; consumers forward-fill last observation | the single failed scraper only |
| **cc-fx-scraper** | ⚠️ ensemble-compute FX specialists read stale/last FX (merge_asof backward) | fx-scraper → ensemble-compute (+ ensemble downstream) |
| **cc-ice-cot-eu / cc-enso** | ⚠️ ensemble FX/Spring specialists read prior week/month value | the failed scraper; next eve's ensemble-compute picks it up |
| **cc-eca / cc-nca** | ⚠️ No short-term impact (briefs don't read supply_demand yet); watchdog alerts after 21d | the failed scraper |

Standard relaunch command (sequential, wait for each):

```bash
gcloud run jobs execute <job> --region=europe-west9 --project=cacaooo --wait
```

Force a Phase B rerun for a specific session date (bypass the eve gate):

```bash
gcloud run jobs execute cc-press-review-agent --region=europe-west9 --project=cacaooo \
  --args="press-review,--session-date,2026-05-26,--force"
```

Full diagnosis + per-scenario cascades: [pipeline-failure-recovery.md](../../runbooks/pipeline-failure-recovery.md). Ensemble-specific: [ensemble-failure-recovery.md](../../runbooks/ensemble-failure-recovery.md).

---

## 6 — Recovery verification

After a relaunch cascade, confirm the session date propagated everywhere (via the bastion tunnel — see [db-sync-from-gcp.md](../../runbooks/db-sync-from-gcp.md)):

```sql
SELECT
  (SELECT MAX(date) FROM pl_contract_data_daily)    AS market_max,
  (SELECT MAX(date) FROM pl_derived_indicators)     AS derived_max,
  (SELECT MAX(date) FROM pl_indicator_daily)        AS indicator_max,
  (SELECT MAX(data_date) FROM pl_orchestrator_decision) AS ensemble_max,
  (SELECT MAX(date) FROM pl_fundamental_article)    AS press_max,
  (SELECT MAX(date) FROM pl_weather_observation)    AS weather_max;
```

All should show the same session date **T**. Then:

1. **Dashboard** — `https://app.com-compass.com/dashboard`: signal, gauges, press, weather, audio all present for T.
2. **Sentry** — no new errors after the relaunch.
3. **Drive** — both `YYYYMMDD-CompassBrief.txt` and `-Ensemble.txt` present; NotebookLM audio appears overnight.

---

## 7 — See also

- [JOBS_AND_SCRAPERS.md](../JOBS_AND_SCRAPERS.md) — per-job catalog (source, method, output table, known issues)
- [PIPELINE_LEGACY.md](../PIPELINE_LEGACY.md) / [PIPELINE_ENSEMBLE.md](../PIPELINE_ENSEMBLE.md) — business logic of each track
- [pipeline-failure-recovery.md](../../runbooks/pipeline-failure-recovery.md) — step-by-step recovery runbook
- [ensemble-failure-recovery.md](../../runbooks/ensemble-failure-recovery.md) — ensemble-specific recovery
- [brief-dual-track.md](../../runbooks/brief-dual-track.md) — dual-track audio operations
- [`.claude/rules/pipeline-error-handling.md`](../../../.claude/rules/pipeline-error-handling.md) — fail-loud rule
- [`.claude/rules/pipeline-continuity.md`](../../../.claude/rules/pipeline-continuity.md) — computation-to-storage contract
- [`infra/terraform/scheduler.tf`](../../../infra/terraform/scheduler.tf) — cron source of truth
- [`backend/scripts/db.py`](../../../backend/scripts/db.py) — gate functions (`is_eve_of_trading_day`, `get_next_session_date`, `get_previous_session_date`)
