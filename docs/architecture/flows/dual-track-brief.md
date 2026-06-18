# Flow — Dual-Track Brief (legacy + ensemble)

> **Scope**: the end-to-end data flow that produces the *two* daily NotebookLM briefs — the **legacy** LLM-decision brief and the **ensemble** ML-decision brief — and how the frontend picks which audio to serve.
>
> This is a **flow doc**: it traces inputs → jobs → DB rows → Drive files → audio → dashboard, and the invariants that keep both tracks isolated. It is *not* a runbook (operations live in [docs/runbooks/brief-dual-track.md](../../runbooks/brief-dual-track.md)) nor a pipeline reference (decision logic lives in [PIPELINE_LEGACY.md](../PIPELINE_LEGACY.md) + [PIPELINE_ENSEMBLE.md](../PIPELINE_ENSEMBLE.md)).
>
> **Status (2026-06)**: both tracks run in production every trading-eve. Two `.txt` briefs and two NotebookLM audios are produced per session. The audio served to the dashboard is gated by `BRIEF_DEFAULT_VERSION` (default `legacy`) with a per-request `?version=` override.

---

## 1 — Why two tracks at all

The product is migrating its daily audio podcast from a **legacy LLM-as-decision-maker** (T+1 horizon, operational ~18 months) to a **14-specialist ML ensemble** (J+4–J+5 horizon). Rather than a hard cutover, both pipelines run side-by-side:

- Same shared inputs (scrapers, press review, meteo).
- Fully isolated outputs (distinct `pl_indicator_daily` rows, distinct Drive filenames, distinct NotebookLM audios).
- Switchable at serve-time without redeploying the pipeline — flip an env var or pass a query param.
- Legacy is **not** a silent fallback for ensemble. If the ensemble track fails, it fails loud; the dashboard does not auto-degrade to legacy audio. That is a deliberate product choice, not graceful degradation (see [.claude/rules/pipeline-error-handling.md](../../../.claude/rules/pipeline-error-handling.md) §3).

The two tracks converge at exactly one point: the frontend `/v1/dashboard/audio` endpoint, which resolves *which* audio to hand the player.

---

## 2 — The flow at a glance

```
                       ┌──────────────────────────────────────────────┐
                       │   SHARED INPUTS (Phase A + Phase B)            │
                       │   pl_contract_data_daily (OHLCV+IV)            │
                       │   pl_derived_indicators (27 indicators)        │
                       │   pl_fundamental_article (press review)        │
                       │   pl_weather_observation (meteo)               │
                       │   pl_article_segment / pl_seasonal_score / ... │
                       └──────────────────────────────────────────────┘
                                          │
                ┌─────────────────────────┴──────────────────────────┐
                ▼                                                      ▼
   ╔════════════════════════════╗                    ╔══════════════════════════════════╗
   ║  TRACK LEGACY              ║                    ║  TRACK ENSEMBLE                   ║
   ╠════════════════════════════╣                    ╠══════════════════════════════════╣
   ║ 19:20 cc-daily-analysis    ║                    ║ 19:18 cc-ensemble-compute         ║
   ║   --algorithm-version      ║                    ║   → pl_orchestrator_decision      ║
   ║     legacy                 ║                    ║   → 14× pl_specialist_prediction  ║
   ║   → UPDATE legacy row of   ║                    ║   → ensemble row of               ║
   ║     pl_indicator_daily     ║                    ║     pl_indicator_daily            ║
   ║     (eco, decision, conf,  ║                    ║     (decision = wrapped_decision) ║
   ║      direction, conclusion)║                    ║                                    ║
   ║                            ║                    ║ 19:25 cc-ensemble-explainer        ║
   ║                            ║                    ║   (thin wrapper → DBAnalysisEngine)║
   ║                            ║                    ║   → UPDATE ensemble row :          ║
   ║                            ║                    ║     eco, confidence, direction,    ║
   ║                            ║                    ║     conclusion (decision IMMUTABLE)║
   ║                            ║                    ║                                    ║
   ║ 19:30 cc-compass-brief     ║                    ║ 19:35 cc-compass-brief-ensemble   ║
   ║   → Drive:                 ║                    ║   → Drive:                         ║
   ║     YYYYMMDD-              ║                    ║     YYYYMMDD-CompassBrief-         ║
   ║     CompassBrief.txt       ║                    ║     Ensemble.txt                   ║
   ╚════════════════════════════╝                    ╚══════════════════════════════════╝
                │                                                      │
                ▼                                                      ▼
   YYYYMMDD-CompassAudio.{wav,m4a,mp4}        YYYYMMDD-CompassAudio-Ensemble.{wav,m4a,mp4}
   (NotebookLM, next morning)                 (NotebookLM, next morning)
                │                                                      │
                └─────────────────────────┬────────────────────────────┘
                                           ▼
                            GET /v1/dashboard/audio
                            AudioService._normalize_version(version)
                              version param  →  ensemble | legacy
                              else            →  settings.BRIEF_DEFAULT_VERSION
                            → resolves YYYYMMDD-CompassAudio[-Ensemble].{ext}
                            → backend-proxied stream to the <audio> element
```

---

## 3 — Date semantics (the one thing that breaks if you get it wrong)

Both brief jobs are **Phase B** jobs (next-session refresh). They run on a daily cron, gated in-agent on `is_eve_of_trading_day()`, and they juggle two dates:

| Variable | Meaning | Drives |
|---|---|---|
| `target_date` | The **upcoming** trading session the brief speaks about. Defaults to `get_next_session_date(today())`. | Brief header / framing, and the P2b-keyed reads (`pl_fundamental_article`, `pl_weather_observation`, which are written tagged to the upcoming session). |
| `data_date` | `get_previous_session_date(target_date)` = the **last completed** session. The row date that Phase A (`cc-compute-indicators` 19:15) and `cc-ensemble-compute` (19:18) wrote at. | The WHERE/UPDATE key for `pl_indicator_daily`, `pl_orchestrator_decision`, `pl_specialist_prediction`. |

**Critical invariant — filename is keyed on `data_date` (= `session_date`), NOT `target_date`:**

```
filename = f"{previous_session.strftime('%Y%m%d')}-CompassBrief[-Ensemble].txt"
```

This is what keeps **brief ↔ NotebookLM audio ↔ dashboard lookup** aligned. The dashboard calendar shows `display_date` (= `next_trading_day(session)`); when a user opens it, `_parse_and_validate_date()` resolves `display_date → session_date`, and `AudioService.get_audio_file_info()` looks up `YYYYMMDD-CompassAudio[-Ensemble].{ext}` where `YYYYMMDD = session_date`. If the brief filename used `target_date` instead, the audio would be one trading day out of phase with everything the dashboard queries.

> Both CLI entry points encode this explicitly (`scripts/compass_brief/main.py`, `scripts/compass_brief_ensemble/main.py`): they compute `previous_session = get_previous_session_date(target_date)` purely to derive the filename, even though the publication framing uses `target_date`.

**Weekend edge case**: Sunday eve (= eve of Monday) the gate fires. Sunday 19:05 the press review writes `pl_article_segment` with `article_date = Friday`; the ensemble brief for Friday's session therefore incorporates weekend news. `data_date` = Friday, so the filename is `YYYYMMDD(Friday)-...`.

---

## 4 — Track LEGACY flow

### 4.1 Decision producer — `cc-daily-analysis` (19:20)

- Pinned to `--algorithm-version legacy` in `deploy.yml` so it **never** auto-aligns onto the ensemble row (see §5.2 for why that matters).
- Runs `DBAnalysisEngine.run()`: 2 `gpt-4-turbo` calls (Call#1 macro/weather → `eco` + `macroeco_bonus`; Call#2 → `decision`/`confidence`/`direction`/`conclusion`), driven by the composite `final_indicator` computed from `pl_derived_indicators`.
- Writes/updates the **legacy row** of `pl_indicator_daily` (`algorithm_version_id = legacy`) at `date = data_date`.

### 4.2 Brief renderer — `cc-compass-brief` (19:30)

- `DBBriefReader.read_all()` reads the legacy row plus a yesterday/today technicals snapshot (legacy brief is T+1, "yesterday vs today" framed).
- `generate_brief()` renders the `.txt`.
- **Stale-data guard**: if `data.today.date < previous_session` (upstream technicals never caught up), the job **skips the upload** rather than overwrite a good brief, and exits 0. Re-run with `--force` after upstream catch-up. (Legacy `cc-compass-brief` does not yet take `--target-date`; it reads the two most recent `pl_contract_data_daily` dates.)
- Uploads to Drive (idempotent — same filename overwrites).

---

## 5 — Track ENSEMBLE flow

The ensemble brief needs the same *narrative* shape as the legacy brief (so NotebookLM produces a comparable podcast), but its **decision is owned by the ML pipeline and must stay immutable**. This is achieved in three steps.

### 5.1 Decision producer — `cc-ensemble-compute` (19:18)

Writes, at `date = data_date`:
- 1 row in `pl_orchestrator_decision` (soft-gate + Compass-wrapper diagnostics: `soft_gate_decision`, `wrapper_active`, `net_score`, `n_committed_specialists`, the 4 `fired_*` detector flags, `running_acc_5d`, `winter_vote_signed`/`spring_vote_signed`, macro fields, priors, etc.).
- 14 rows in `pl_specialist_prediction` (one vote each).
- 1 UPSERT in the **ensemble row** of `pl_indicator_daily` (`algorithm_version_id = ensemble_v1_softgate_wrapper`), with `decision = wrapped_decision`. At this point the narrative fields (`eco`, `confidence`, `direction`, `conclusion`) are still empty.

### 5.2 Narrative enricher — `cc-ensemble-explainer` (19:25)

This is a **thin wrapper** (`scripts/ensemble_explainer/main.py`), not a custom pipeline. It:

1. **Pre-flight (fail-loud)**: `_assert_ensemble_row_present()` checks the ensemble row exists in `pl_indicator_daily` for `(data_date, contract, ensemble_algo)`. If absent → `EnsembleRowMissingError`, exit 1. This prevents the engine from silently falling back to the legacy row and polluting the legacy track. It also avoids burning 2 `gpt-4-turbo` calls on a missing row.
2. **Invokes `DBAnalysisEngine.run()` *without* pinning `algorithm_version_name`.** The engine's built-in **auto-align** (`db_analysis_engine.py`) detects an ensemble row (`inputs.ensemble is not None` and no explicit version override), pins its cached `algorithm_version_id` to the ensemble row, swaps Call#2 to `CALL_2_PROMPT_ENSEMBLE` (injects the diagnostics block), and **force-aligns the LLM decision to `decision_wrapped`** so the narrative can never contradict the ML decision.
3. Writes `eco` / `confidence` / `direction` / `conclusion` to the **ensemble row** — same long-form `> ... • ... > A SURVEILLER AUJOURD'HUI: ...` structure the frontend recommendation parser expects.
4. **Defense in depth**: if `result.ensemble_aligned` is false after the run (engine resolved to a different row — e.g. a race with the pre-flight), raise `EnsembleRowMissingError`.

> This is why `cc-daily-analysis` is pinned to `legacy` (§4.1): the *same* auto-align mechanism would otherwise make the legacy job hijack the ensemble row. Pinning keeps the two jobs writing to disjoint rows.

If the engine ever logs `LLM returned decision=X but ensemble said Y — forcing alignment`, the narrative was preserved but the prompt is drifting — monitor `CALL_2_PROMPT_ENSEMBLE` in `scripts/daily_analysis/prompts.py`.

### 5.3 Brief renderer — `cc-compass-brief-ensemble` (19:35)

`read_brief_data()` (`scripts/compass_brief_ensemble/db_reader.py`) assembles a forward-looking `EnsembleBriefData` from:

| Section input | Source | Notes |
|---|---|---|
| Decision + narrative | ensemble row of `pl_indicator_daily` (enriched by 5.2) | fail-loud `EnsembleBriefDataMissingError` if missing |
| Diagnostics (25+ fields) | `pl_orchestrator_decision` | soft-gate, wrapper flags, votes, macro, priors |
| 14 specialist votes | `pl_specialist_prediction` | mapped to editorial labels via `specialist_catalog.py` |
| Press review | `pl_fundamental_article` (latest active, `date <= target_date`) | summary / impact / sentiment |
| Meteo | `pl_weather_observation` + `pl_seasonal_score` campaign trajectory | daily obs + cumulative seasonal health |
| Technicals snapshot | `pl_contract_data_daily` (+ `pl_stock_observation`, `pl_cot_us_weekly`) | last completed session OHLCV/IV/stocks/COM-NET |
| YTD + running accuracy | recomputed via `_compute_ytd_score` / `_compute_running_accuracy` | **same J+4 Compass scoring formula as the dashboard "Performance YTD" badge**, `COALESCE(ensemble, legacy)` — the number read aloud must equal the dashboard number, and the raw R&D `running_acc_5d` is NaN-prone during the post-retraining bootstrap |

`render_brief()` (`scripts/compass_brief_ensemble/brief_generator.py`) outputs an intro + 6 numbered sections:

```
I    — SIGNAL                              (decision + confidence + direction + YTD)
II   — LECTURE ÉDITORIALE                  (headline specialist + thematic convergence)
III  — ÉCO & PRESS REVIEW                  (LLM eco + press summary/impact/sentiment)
IV   — WEATHER WATCH                       (meteo summary + campaign trajectory + impact)
V    — CHIFFRES TECHNIQUES DERNIÈRE SESSION
VI   — RECOMMANDATIONS OPÉRATIONNELLES     (LLM conclusion)
```

**Engine-opacity guard (`_assert_safe`)**: everything in the brief is read aloud by NotebookLM, so the renderer must never leak the decision engine's internals. Before rendering, every LLM-written field (`eco`, `press_summary`, `conclusion`, `confidence_rationale`) is scanned against `_FORBIDDEN_SUBSTRINGS` (`soft-gate`, `wrapper`, `running_acc`, `14 spécialistes`, `net_score`, `machine learning`, `cluster winter/spring`, …). Any hit → `UnsafeBriefContentError`, exit 1. The recovery path is to fix the upstream enrichment (typically the explainer prompt), not to scrub the text in place. Specialist names/codes/counts/clusters/horizons are never rendered — only editorial labels from the catalog.

Upload is idempotent (same filename overwrites). On success the job sets Sentry context (decision, persistence, specialist count, file id).

---

## 6 — Isolation invariants (what keeps the two tracks from colliding)

| Asset | Legacy | Ensemble | Isolation mechanism |
|---|---|---|---|
| `pl_indicator_daily` row | `algorithm_version_id = legacy` | `algorithm_version_id = ensemble_v1_softgate_wrapper` | UNIQUE `(date, contract_id, algorithm_version_id)` → one track physically cannot touch the other's row |
| `pl_orchestrator_decision` | — | exclusive | ensemble-only table |
| `pl_specialist_prediction` | — | 14 rows/day, exclusive | ensemble-only table |
| Job → row binding | `--algorithm-version legacy` pin | engine auto-align (no pin) | pinning keeps the legacy job off the ensemble row |
| Drive `.txt` | `YYYYMMDD-CompassBrief.txt` | `YYYYMMDD-CompassBrief-Ensemble.txt` | filename suffix; `YYYYMMDD = data_date` for both |
| Drive audio | `YYYYMMDD-CompassAudio.{ext}` | `YYYYMMDD-CompassAudio-Ensemble.{ext}` | NotebookLM inherits the brief prefix |

All four `YYYYMMDD` values for a given session collapse to the **same `session_date` (= `data_date`)** — that single alignment is what lets the dashboard fetch either track's audio with one date lookup.

---

## 7 — Serve-time convergence (which audio the dashboard plays)

`AudioService._normalize_version(version)` (`backend/app/services/audio_service.py`) resolves the track:

1. Explicit `?version=ensemble|legacy` on the request → that track.
2. Else → `settings.BRIEF_DEFAULT_VERSION` (default `legacy`).
3. Unknown value → `ValueError` (fail-loud, no silent default).

The resolved version maps to a filename suffix (`_VERSION_FILENAME_SUFFIX = {"legacy": "", "ensemble": "-Ensemble"}`), and `get_audio_file_info()` looks up `YYYYMMDD-CompassAudio{suffix}.{wav|m4a|mp4}` in the Drive folder, cache-gated (1h hit / 5min miss TTL). Endpoints honoring `?version=`:

- `GET /v1/dashboard/audio`
- `GET /v1/audio/info`
- `GET /v1/audio/stream` (unauthenticated, for the HTML `<audio>` element)

**Global flip** (no redeploy of jobs):

```bash
gcloud run services update backend --region europe-west9 --project cacaooo \
  --update-env-vars BRIEF_DEFAULT_VERSION=ensemble   # rollback: =legacy
```

New Cloud Run instances pick up the env var at boot; old instances drain over a few minutes.

---

## 8 — Failure modes & where they surface

| Failure | Detection | Behavior | Recovery |
|---|---|---|---|
| `cc-ensemble-compute` did not write the ensemble row | `cc-ensemble-explainer` pre-flight `_assert_ensemble_row_present` | `EnsembleRowMissingError`, exit 1 | run ensemble-compute first; see [ensemble-failure-recovery.md](../../runbooks/ensemble-failure-recovery.md) |
| Explainer enrichment ran but engine resolved wrong row | `result.ensemble_aligned is False` | `EnsembleRowMissingError`, exit 1 | check `pl_orchestrator_decision` freshness |
| Ensemble row / orchestrator row missing at brief time | `cc-compass-brief-ensemble` reader | `EnsembleBriefDataMissingError`, exit 1 | rerun explainer chain, then brief |
| LLM field leaks engine internals | `_assert_safe` substring scan | `UnsafeBriefContentError`, exit 1 | fix upstream enricher prompt, relaunch — never scrub in place |
| Legacy upstream technicals stale | `cc-compass-brief` stale-data guard | skip upload, exit 0 | `--force` after catch-up |
| Brief job runs on a non-trading eve | `is_eve_of_trading_day()` gate | skip cleanly, exit 0 (Sentry cron monitor reads as success) | none — expected |

All jobs are **fail-loud, no auto-retry, no silent fallback** ([pipeline-error-handling.md](../../../.claude/rules/pipeline-error-handling.md)). Manual relaunch order for the ensemble track: `cc-ensemble-compute` → `cc-ensemble-explainer` → `cc-compass-brief-ensemble` (explainer must precede the brief — it writes the narrative the brief reads).

---

## 9 — Cost

- Legacy: 2× `gpt-4-turbo`/day (`cc-daily-analysis`).
- Ensemble: 2× `gpt-4-turbo`/day (`cc-ensemble-explainer`, same engine) ≈ +$30/year — the price of narrative parity with the legacy brief; the ML decision itself is ~free.
- 2 `.txt` files + 2 NotebookLM audios/day. NotebookLM quota is the thing to watch under dual-track, not LLM spend.

---

## 10 — Source map

| Concern | Path |
|---|---|
| Legacy decision engine | `backend/scripts/daily_analysis/db_analysis_engine.py` (auto-align logic), `scripts/daily_analysis/prompts.py` |
| Legacy brief | `backend/scripts/compass_brief/{main,db_reader,brief_generator}.py` |
| Ensemble decision | `backend/scripts/ensemble_compute/` (+ `backend/vendor/campaign5_ensemble_v1.0.x/`) |
| Ensemble explainer | `backend/scripts/ensemble_explainer/main.py` |
| Ensemble brief | `backend/scripts/compass_brief_ensemble/{main,db_reader,brief_generator,specialist_catalog}.py` |
| Audio serve-time routing | `backend/app/services/audio_service.py`, `backend/app/api/api_v1/endpoints/{dashboard,audio}.py` |
| Job/scheduler args | `.github/workflows/deploy.yml` |
| Operations | [docs/runbooks/brief-dual-track.md](../../runbooks/brief-dual-track.md), [brief-rollback-procedure.md](../../runbooks/brief-rollback-procedure.md), [brief-ensemble-evolution.md](../../runbooks/brief-ensemble-evolution.md) |
| Pipeline references | [PIPELINE_LEGACY.md](../PIPELINE_LEGACY.md), [PIPELINE_ENSEMBLE.md](../PIPELINE_ENSEMBLE.md), [JOBS_AND_SCRAPERS.md](../JOBS_AND_SCRAPERS.md) |
