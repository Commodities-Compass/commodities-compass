# CODE_MAP — Single Entry Point

> **Read this first.** This is the map a new engineer (or AI) opens before touching anything. It tells you what each subsystem does, where it lives, which tables it reads/writes, and where to go deeper. It is deliberately terse — follow the links for detail.

## Companion docs (business + ops context)

- **[PIPELINE_LEGACY.md](./PIPELINE_LEGACY.md)** — LLM-as-decision-maker track (`cc-daily-analysis` → `cc-compass-brief`), T+1 horizon, ~18 months in prod.
- **[PIPELINE_ENSEMBLE.md](./PIPELINE_ENSEMBLE.md)** — Campaign 5 ML track (14 specialists + Bayesian soft-gate + Compass wrapper + explainer + ensemble brief), J+4–J+5 horizon. The dashboard already serves this.
- **[JOBS_AND_SCRAPERS.md](./JOBS_AND_SCRAPERS.md)** — exhaustive catalog of all 19 Cloud Run Jobs + 16 schedulers + dependency graph + shared-vs-specific tables. Read for the UTC timeline.
- **[ENSEMBLE_BRIDGE_FROM_LEGACY.md](./ENSEMBLE_BRIDGE_FROM_LEGACY.md)** — how the ensemble row coexists with / overrides legacy.

> **Flow deep-dives** live in [`docs/architecture/flows/`](./flows/) — five cross-cutting traces produced by the 2026-06-18 backend audit (read these for the failure-prone paths):
> [contract-roll](./flows/contract-roll.md) · [date-semantics](./flows/date-semantics.md) · [algo-contract-resolution](./flows/algo-contract-resolution.md) · [daily-pipeline](./flows/daily-pipeline.md) · [dual-track-brief](./flows/dual-track-brief.md).
>
> The per-subsystem `flows/<subsystem>.md` links in the rows below are marked **(planned)** — future per-subsystem deep-dives not yet written; until then the companion docs above + the `reads/writes/invariants` rows here are authoritative for those.

---

## How data flows, in one paragraph

Every weekday after market close (**Phase A**, ~18:30–19:15 UTC), scrapers write raw market data into `pl_contract_data_daily` (OHLCV+IV, keyed on `(date, contract_id)`), into the weekly/quarterly cadence tables (`pl_stock_observation`, `pl_cot_eu_weekly`, `pl_cot_us_weekly`, `pl_supply_demand_observation`), and into the shared external table `pl_external_indicator` (FX daily, ENSO monthly). The **indicator engine** (`compute-indicators`) then reads `pl_contract_data_daily`, computes 26 derived indicators → `pl_derived_indicators`, applies 5-day smoothing + rolling 252-day z-scores, runs the power-formula composite, and writes scores + decision into `pl_indicator_daily` (+ per-indicator decomposition into `pl_signal_component`). On the **eve of the next trading day** (**Phase B**, gated by `is_eve_of_trading_day()`), the agents fire: meteo + press review write fundamentals (`pl_weather_observation`, `pl_fundamental_article`, `pl_article_segment`); **ensemble-compute** runs 14 specialists + soft-gate + Compass wrapper and writes 14 `pl_specialist_prediction` + 1 `pl_orchestrator_decision` + the ensemble row of `pl_indicator_daily`; **daily-analysis** (legacy) and **ensemble-explainer** add LLM narrative to their respective `pl_indicator_daily` rows; the two **briefs** render `.txt` to Google Drive for NotebookLM audio. The **FastAPI dashboard** reads only `pl_*` tables, resolves the user's calendar `display_date` back to a session `date`, picks the active contract (handling rolls) and the date-aware algorithm version (ensemble where rows exist, else legacy), and serves the result. Every row is keyed to a **session date** and a **contract_id**; the dashboard's `display_date` (= next trading day) is the only place that offset lives.

---

## Subsystems

### 1. Indicator computation engine — `backend/app/engine/`
Production Python pipeline that replaced the Google Sheets formula engine: 14 indicators → 26 derived columns, 5-day SMA smoothing, rolling 252-day z-scores, power-formula composite with two-pass momentum → OPEN/HEDGE/MONITOR. Contract-centric, config-as-data.
- **Entrypoints**: `runner.py` (CLI `poetry run compute-indicators [--all-contracts|--contract CAK26] [--dry-run|--full] [--algorithm legacy --algorithm-version 1.0.1]`), `pipeline.py` (orchestrator), `registry.py` (topo-sort), `composite.py`, `normalization.py`, `smoothing.py`, `db_writer.py`, `indicators/`, `types.py`. See `app/engine/README.md`.
- **Reads**: `pl_contract_data_daily`, `ref_contract`, `pl_indicator_daily` (macroeco LEFT JOIN), `pl_algorithm_version`, `pl_algorithm_config`.
- **Writes**: `pl_derived_indicators`, `pl_indicator_daily`, `pl_signal_component`.
- **Docs**: `flows/indicator-engine.md` (planned) · [PIPELINE_LEGACY.md](./PIPELINE_LEGACY.md) · [PIPELINE_ENSEMBLE.md](./PIPELINE_ENSEMBLE.md).
- **Key invariants**: rolling 252-day z-score over **session date** (never `display_date`) — replaces Sheets full-history look-ahead bug; two-pass momentum (base score with momentum=0 first); `pl_signal_component.raw_value`/`normalized_value` must trace to a computation, never literals (pipeline-continuity); config (16 coeff/exp pairs, k, thresholds) loaded from `pl_algorithm_config`, `LEGACY_V1` is fallback only; idempotent upsert on `(date, contract_id[, algorithm_version_id])`; warmups EMA26=26, MACDSignal=35, RSI=15, Stoch/ATR=14, Bollinger=20.

### 2. Models & migrations — `backend/app/models/` + `backend/alembic/versions/`
SQLAlchemy ORM + 38 Alembic migrations defining the contract-centric `pl_*`, reference `ref_*`, and audit `aud_*` schema. The bridge between typed Python models and the PostgreSQL 15 prod schema.
- **Entrypoints**: `models/pipeline.py`, `reference.py`, `signal.py`, `audit.py`, `test_range.py`, `base.py`; legacy (`technicals.py`, `indicator.py`, `market_research.py`, `weather_data.py` — present for audit, unused by prod). Migrations in `backend/alembic/versions/` (e.g. `n8i9j0k1l2m3_create_v_contract_data_chained.py`, `r2m3n4o5p6q7_stocks_cot_us_dedicated_tables.py`).
- **Reads/Writes**: all `pl_*` / `ref_*` / `aud_*` tables + `test_range` (schema authority for every other subsystem).
- **Docs**: `flows/schema.md` (planned) · `.local`/HEDI_DATA_MAP for column-level detail.
- **Key invariants**: `display_date = next_trading_day(session date)`; only `pl_contract_data_daily` carries `display_date`, all other `pl_*` use session `date` only. Weekly/quarterly cadence tables (`pl_stock_observation`, `pl_cot_*_weekly`, `pl_supply_demand_observation`) keyed on `report_date`, never stamped daily. `GENERATED` columns (`prod_merc_net`, `m_money_net` on both COT tables) are never written directly. **Migrations reach prod via `main` only** (migrations-prod-via-main-only); idempotent UP/DOWN (`_has_column` / `IF NOT EXISTS`).

### 3. API endpoints — `backend/app/api/api_v1/endpoints/`
FastAPI router layer: auth + dashboard (position, indicators, recommendations, chart, news, weather, audio, ensemble diagnostics, macro panel, positioning) + non-trading calendar. HTTP ⇄ business-logic translation; validation, date/contract/algorithm resolution, rate limiting, DTO formatting. Read-only (no writes).
- **Entrypoints**: `api.py` (aggregator), `auth.py`, `dashboard.py`, `audio.py`.
- **Reads**: `pl_indicator_daily`, `pl_derived_indicators`, `pl_contract_data_daily`, `pl_fundamental_article`, `pl_weather_observation`, `pl_signal_component`, `pl_orchestrator_decision`, `pl_specialist_prediction`, `pl_external_indicator`, `pl_cot_eu_weekly`, `pl_stock_observation`, `pl_seasonal_score`, `pl_article_segment`, `pl_sentiment_feature`, `pl_algorithm_version`, `ref_contract`/`ref_exchange`/`ref_trading_calendar`.
- **Docs**: `flows/dashboard-request.md` (planned) · § "API Structure" + "Google Drive Audio Integration" in CLAUDE.md.
- **Key invariants**: date resolution is `display_date → session_date` (never reverse); every response carries `source_algorithm`; algorithm version is **date-aware** (ensemble where rows exist, else legacy, no retroactive backfill); recommendations narrative skips debug-string rows; `/audio/stream` is intentionally **unauthenticated** (HTML `<audio>` / iOS Safari), `/audio/info` + `/dashboard/audio` require auth; dual-track audio via `?version=` / `BRIEF_DEFAULT_VERSION`; YTD scored on **J+4** horizon; rate limits 60/min (data) / 10/min (audio).

### 4. Services — `backend/app/services/`
Business-logic layer behind the endpoints: position/decision, YTD, indicator gauges, recommendations, news, weather enrichment, audio metadata, COT/stock positioning, macro panel, ensemble diagnostics. All reads, no writes.
- **Entrypoints**: `dashboard_service.py` (+ `dashboard_transformers.py`), `audio_service.py` (Google Drive singleton), `positioning_service.py`, `macro_panel_service.py`, `weather_service.py`, `ensemble_diagnostics_service.py`.
- **Reads**: same `pl_*` set as the API layer (contract-centric); legacy `Technicals`/`Indicator` never imported.
- **Docs**: `flows/services.md` (planned).
- **Key invariants**: cross-contract fallback on rolls via `resolve_contract_for_date()` + `v_contract_data_chained` (`DISTINCT ON date ORDER BY oi DESC`); position defaults to MONITOR on null (benign) but logs ERROR on unrecognized values (never silent corruption); YTD + running-accuracy on **J+4** (`YTD_EVAL_HORIZON_DAYS=4`); contract/algo lookups cached 5min, audio lookups 1h hit / 5min miss; ensemble diagnostics only populated on ensemble dates (404 → conditional frontend render).

### 5. Core & utils — `backend/app/core/` + `backend/app/utils/`
Infrastructure: Pydantic config, Auth0 JWT validation (JWKS cached 6h), dual DB engines (async for FastAPI, sync for Alembic/scripts), slowapi limiter, Sentry init; utils for contract/algorithm resolution, date parsing, trading calendar, type converters.
- **Entrypoints**: `core/config.py`, `core/auth.py`, `core/database.py`, `core/rate_limit.py`, `core/sentry.py`; `utils/contract_resolver.py` (async — `ENSEMBLE_VERSION_NAME = "ensemble_v1_softgate_wrapper"`, `LEGACY_VERSION_NAME = "legacy"`, `get_algorithm_version_for_date()`), `utils/date_utils.py`, `utils/trading_calendar.py`, `utils/converters.py`.
- **Reads**: `ref_contract`, `pl_algorithm_version`, `pl_indicator_daily`, `pl_contract_data_daily`, `ref_exchange`, `ref_trading_calendar`.
- **Docs**: `flows/resolution.md` (planned).
- **Key invariants**: `async_engine` → FastAPI only, `sync_engine` → Alembic/scripts only (mixing deadlocks the loop); 4-tier contract fallback always yields a `contract_id` (no gaps across rolls); `PlIndicatorDaily` keyed `(date, contract_id, algorithm_version_id)`, no retroactive ensemble backfill; TTLCache auto-expires (5min resolver / 6h JWKS), no manual invalidation — scrapers in other processes see stale `contract_id` until TTL (acceptable, rolls are rare). **Note**: `app/utils/contract_resolver.py` (async) and `scripts/contract_resolver.py` (sync) are two separate modules — never mix in one process.

### 6. Barchart scrapers — `backend/scripts/barchart_scraper/` + `backend/scripts/barchart_stocks_eu_scraper/`
(1) OHLCV+IV for the active front-month **plus** next delivery month (Playwright). (2) ICE Europe certified stocks (60kg bags, httpx + BeautifulSoup).
- **Entrypoints**: `poetry run barchart-scraper [--dry-run|--verbose|--headful|--force]` (cron 19:00 UTC); `poetry run barchart-stocks-eu-scraper [--dry-run|--verbose|--force]` + `…-backfill` (cron 19:10 UTC).
- **Reads**: `ref_contract` (code + `is_active`), `pl_contract_data_daily`.
- **Writes**: `pl_contract_data_daily` (OHLCV+IV upsert by `date+contract_id`), `pl_stock_observation` (EU, `region='eu'`, `source='barchart_ic345drw'`).
- **Docs**: [JOBS_AND_SCRAPERS.md](./JOBS_AND_SCRAPERS.md) · § "Scrapers" in CLAUDE.md.
- **Key invariants**: **never** uses `CA*0` continuous symbol — contract codes from `ref_contract.is_active` (env `ACTIVE_CONTRACT` is transient-failure fallback only); front-month fail-loud, back-month best-effort; IV stored as decimal (÷100); EU stocks go to `pl_stock_observation` not `pl_contract_data_daily` (legacy `stock_eu_bags60kg` dropped, migration `r2m3n4o5p6q7`); stocks staleness > 14d → Sentry ERROR; XHR primary, HTML max-volume raw block fallback (XHR omits OI).

### 7. Fundamentals scrapers — `backend/scripts/{ice_stocks_scraper,cftc_scraper,ice_cot_eu_scraper,eca_grindings_scraper,nca_grindings_scraper,publication_calendar_watchdog}/`
Supply/positioning ingestion: ICE US stocks, CFTC US COT, ICE EU COT, ECA/NCA quarterly grindings (calendar-gated), + the publication watchdog.
- **Entrypoints**: `poetry run {ice-stocks-scraper,cftc-scraper,ice-cot-eu-scraper,eca-grindings-scraper,nca-grindings-scraper,publication-calendar-watchdog}` (+ `…-backfill` variants). Crons per JOBS doc.
- **Reads**: `ref_publication_calendar` (ECA/NCA gate + watchdog).
- **Writes**: `pl_stock_observation`, `pl_cot_us_weekly`, `pl_cot_eu_weekly`, `pl_supply_demand_observation`, `ref_publication_calendar` (`actual_publication_date`).
- **Docs**: [JOBS_AND_SCRAPERS.md](./JOBS_AND_SCRAPERS.md) · `flows/fundamentals.md` (planned).
- **Key invariants**: weekly/quarterly provenance — `report_date` distinct from `release_date`, never stamped on daily OHLCV; ECA/NCA **calendar-gated** (exit 0 = success when nothing pending), watchdog escalates silence past grace window; `contract_market='cocoa'` hardcoded default (multi-market schema, cocoa-only MVP); `GENERATED` net columns never written; `pl_stock_observation` stores both `value_native` and `value_tonnes`; idempotent `ON CONFLICT DO UPDATE`.

### 8. External scrapers (FX + ENSO) — `backend/scripts/fx_scraper/` + `backend/scripts/enso_scraper/`
FX (USD/EUR + GBP/EUR daily from ECB SDMX → 4 derived columns) and ENSO (ONI + Niño 3.4 monthly from NOAA PSL) into one commodity-agnostic shared table.
- **Entrypoints**: `poetry run fx-scraper` (cron 18:30 UTC weekdays) + `fx-scraper-backfill`; `poetry run enso-scraper` (cron 22:00 UTC on the 20th) + `enso-scraper-backfill`.
- **Reads/Writes**: `pl_external_indicator` (partial UPSERT — FX touches only `fx_*`, ENSO only `enso_*`).
- **Docs**: [JOBS_AND_SCRAPERS.md](./JOBS_AND_SCRAPERS.md) · `docs/user-stories/P1-scraper-{fx,enso}.md`.
- **Key invariants**: **partial UPSERT** — each scraper only its own columns, never overwrites the other's; same `date` UNIQUE key, daily vs monthly writes don't collide; ENSO 14-day lag applied **downstream** (`merge_asof(direction='backward')` in macro panel + engine), scraper stores raw publication date; FX skips weekends/EU holidays unless `--force`; fail-loud, no retry/fallback; frozen dataclasses, idempotent.

### 9. Press review + meteo agents — `backend/scripts/press_review_agent/` + `backend/scripts/meteo_agent/`
Phase-B LLM agents: press review (o4-mini, 6+ sources → French analysis + 4 theme sentiments) and meteo (gpt-4.1, 6 West-African stations + seasonal phenology → 24h risk + J+1→J+5 outlook).
- **Entrypoints**: `poetry run press-review [--provider …|--target-date|--force|--dry-run]` (cron 19:05 UTC); `poetry run meteo-agent [--bootstrap-memory|--target-date|--force|--dry-run]` (cron 19:00 UTC). Both eve-gated.
- **Reads**: `pl_contract_data_daily` (latest CLOSE), `ref_contract` (`is_active`), `pl_fundamental_article` (provider shadow filter), `pl_seasonal_score`, `pl_external_indicator` (ENSO regime block).
- **Writes**: `pl_fundamental_article`, `pl_article_segment` (4 theme rows guaranteed), `pl_weather_observation`, `aud_llm_call`.
- **Docs**: [PIPELINE_LEGACY.md](./PIPELINE_LEGACY.md) · [PIPELINE_ENSEMBLE.md](./PIPELINE_ENSEMBLE.md) · `flows/agents-fundamentals.md` (planned).
- **Key invariants**: **P2b date semantics** — prompt frames `target_date` (upcoming session) but every DB row keyed to `data_date = get_previous_session_date(target_date)` (violation = empty dashboard sections the next morning); `is_active` controls provider shadowing (only `PRODUCTION_PROVIDER` shown); all 4 themes mandatory daily (neutral fallback + Sentry warning if missing); duplicate guards fail-loud unless `--force`; active contract from `ref_contract.is_active`, never env var.

### 10. Daily analysis agent — `backend/scripts/daily_analysis/`
LLM decision engine (legacy track): 2 sequential gpt-4-turbo calls (macro/weather → MACROECO_BONUS; technicals → DECISION/CONFIANCE) writing narrative + signals. Also the shared engine that ensemble-explainer wraps.
- **Entrypoints**: `poetry run daily-analysis [--dry-run|--contract|--algorithm-version|--target-date]` (cron 19:20 UTC); engine `db_analysis_engine.py` (`DBAnalysisEngine.run()`).
- **Reads**: `pl_contract_data_daily`, `pl_derived_indicators`, `pl_indicator_daily`, `pl_fundamental_article` (+`market_research` fallback), `pl_weather_observation` (+`weather_data` fallback), `pl_orchestrator_decision`, `pl_algorithm_version`, `ref_contract`, `pl_stock_observation`, `pl_cot_us_weekly`, `ref_trading_calendar`.
- **Writes**: `pl_indicator_daily` (UPDATE narrative + decision), `pl_signal_component` (macroeco row), `aud_pipeline_run`, `aud_llm_call` (2 rows).
- **Docs**: [PIPELINE_LEGACY.md](./PIPELINE_LEGACY.md) · `flows/daily-analysis.md` (planned).
- **Key invariants**: single-transaction write atomicity (rollback → exit non-zero → Sentry); **auto-align on ensemble** — when an ensemble row exists and no `--algorithm-version` override, writes the ensemble row and **pins `decision` to `ensemble.decision_wrapped`** (force-corrects + warns if LLM disagrees); direction coherence normalized (OPEN→HAUSSIERE etc.); `macroeco_bonus` is an LLM scalar (never recomputed), `final_indicator` recomputed via `app.engine.composite`; P2b date keying; no partial output on error.

### 11. Ensemble compute (Campaign 5) — `backend/scripts/ensemble_compute/`
Daily orchestration of 14 LightGBM+GARCH specialists via Bayesian soft-gate + `TransitionProtectionWrapper`, with Compass-side relaxation (`compass_wrapper.py`). Produces the wrapped ensemble decision.
- **Entrypoints**: `poetry run ensemble-compute [--date|--historical|--dry-run]` (cron 19:18 UTC, eve-gated); vendored R&D in `backend/vendor/campaign5_ensemble_v1.0.0/` (read-only; `v1.0.1` also vendored).
- **Reads**: `v_contract_data_chained` (OHLCV/indicators + trailing 10-row decision/specialist windows, chained across rolls), `pl_derived_indicators`, `pl_orchestrator_decision`, `pl_specialist_prediction`, `pl_article_segment` (90d macro signal), `pl_algorithm_version`, `pl_algorithm_config`, `pl_model_artifact`, `ref_contract`, `ref_trading_calendar`.
- **Writes**: `pl_specialist_prediction` (14 rows), `pl_orchestrator_decision` (1 row, ~22 diagnostics), `pl_indicator_daily` (1 row UPSERT).
- **Docs**: [PIPELINE_ENSEMBLE.md](./PIPELINE_ENSEMBLE.md) · `docs/runbooks/wrapper-levers-tuning.md` · `docs/runbooks/ensemble-failure-recovery.md`.
- **Key invariants**: config-as-data (wrapper thresholds, macro-gate cap, regime-monitor all from `pl_algorithm_config`; optional levers default OFF when absent); **chained window** via `v_contract_data_chained` so `running_acc_5d` doesn't reset to NaN on a roll; forward-return scored on **soft-gate** decision, not wrapper output (self-reference loop broke live 2026-05-07); eve-gate incorporates weekend news (Sunday eve reads Friday-dated `pl_article_segment`); fail-loud on data gaps; NULL preferred over hardcoded 0.0 for missing diagnostics. **Shadow state**: `compute_enabled` must stay FALSE in prod until the job is deployed (else `KeyError 'k'`).

### 12. Briefs (legacy + ensemble) + explainer — `backend/scripts/{compass_brief,compass_brief_ensemble,ensemble_explainer}/`
Dual-track `.txt` brief generation for NotebookLM audio. Legacy brief = yesterday+today; ensemble brief (P4) = forward-looking + 14-specialist decomposition. Explainer enriches the ensemble `pl_indicator_daily` row with LLM narrative.
- **Entrypoints**: `poetry run compass-brief` (cron 19:30 UTC), `poetry run compass-brief-ensemble [--target-date|--dry-run]` (cron 19:35 UTC), `poetry run ensemble-explainer [--target-date|--dry-run|--force]` (cron 19:25 UTC — thin wrapper around `DBAnalysisEngine`).
- **Reads**: `pl_indicator_daily` (active-algo join), `pl_orchestrator_decision`, `pl_specialist_prediction`, `pl_contract_data_daily`, `pl_derived_indicators`, `pl_fundamental_article` (+`market_research`), `pl_weather_observation` (+`weather_data`), `pl_stock_observation`, `pl_cot_us_weekly`, `pl_seasonal_score`, `pl_algorithm_version`, `ref_contract`, `v_contract_data_chained`.
- **Writes**: briefs are read-only (output to Google Drive); **explainer** writes via `DBAnalysisEngine` (updates the ensemble `pl_indicator_daily` row: `eco`, `confidence`, `direction`, `conclusion`).
- **Docs**: `docs/runbooks/brief-dual-track.md` · `brief-rollback-procedure.md` · `brief-ensemble-evolution.md`.
- **Key invariants**: P2b date semantics (`test_date_semantics.py` enforces); roll-robust contract resolution (`v_contract_data_chained` / `resolve_active()`, no hardcoded codes); idempotent upload (same filename = update; `-Ensemble` suffix coexists in same Drive folder); fail-loud on missing ensemble row (`EnsembleBriefDataMissingError` / `EnsembleRowMissingError`); **forbidden-substring guard** — ensemble brief raises `UnsafeBriefContentError` if engine-revealing tokens (soft-gate, wrapper, running_acc…) leak into rendered text.

### 13. Shared CLI + DB helpers — `backend/scripts/_shared/` + `backend/scripts/{db.py,contract_resolver.py,roll_contract.py}`
Dependency-injection layer for all ~19 jobs: Sentry bootstrap + cron monitor, argparse base, logging, single-attempt HTTP, sync DB sessions, **sync** contract resolution, trading-calendar helpers, shared stock-observation writer, publication-calendar queries.
- **Entrypoints**: `_shared/{cli.py,sentry.py,http.py,logging.py,publication_calendar.py,stock_observation_writer.py}`, `db.py` (`get_session`, `is_eve_of_trading_day`, `get_next_session_date`, `get_previous_session_date`, `get_display_date`), `contract_resolver.py` (`resolve_active_code`, `resolve_active_at_date`, `next_contract_code`), `roll_contract.py` (`poetry run roll-contract <CODE>`).
- **Reads**: `ref_contract`, `ref_exchange`, `ref_trading_calendar`, `ref_publication_calendar`, `pl_contract_data_daily`, `pl_indicator_daily`, `pl_algorithm_version`, `pl_stock_observation`.
- **Writes**: `ref_contract` (`is_active` flip via `roll-contract` only), `pl_stock_observation` (`upsert_stock_observation`).
- **Docs**: `docs/runbooks/contract-roll-procedure.md` · `flows/shared-cli.md` (planned).
- **Key invariants**: contract codes match `CA[HKNUZ]\d{2}`, no `CA*0` fallback; `resolve_active_code()` enforces exactly one active contract (else `ContractResolverError`); `contract_month` always derived (`H:3,K:5,N:7,U:9,Z:12`), never hardcoded; `is_eve_of_trading_day()` gates Phase-B agents; `resolve_active_at_date()` (front-month-by-OI tiebreak) for backfill only, live uses `resolve_active()`; `fail_loud_get()` = single HTTP attempt, no retry; `DATABASE_SYNC_URL` mandatory (no local fallback); `upsert_stock_observation` does deterministic bag→tonne (`bags × 60 / 1000`).

### 14. Peripheral R&D / backtest / utility — `backend/scripts/{research,seasonal_backtest,watchlist_eval,archive,backfill_diagnostics.py,pattern_extractor,...}/`
Non-production research, evaluation, and one-off utilities (macro-gate retune, wrapper backtests, decade IV-proxy tests, watchlist eval, Julien R&D handoff, coverage diagnostics). They query prod data but do **not** drive the dashboard or live decisions.
- **Entrypoints**: `poetry run {p0-macro-gate-retune,wrapper-conditioning-backtest,wrapper-levers-decade-backtest,robustness-fixes-backtest,resimulate-may-to-now,zero-cost-ivproxy-coherence,historical-conditioning-coherence,watchlist-eval,backtest-seasonal,julien-handoff}`; ad-hoc `scripts/research/…`, `scripts/_analyze_*.py`.
- **Reads**: ensemble + indicator + COT + article + weather tables, `v_contract_data_chained`, `ref_contract` (broad, read-only).
- **Writes**: `pl_seasonal_score` only (backtest, `--write-db`).
- **Docs**: `flows/research.md` (planned) · `docs/architecture/ENSEMBLE_MAY_2026_*` investigations.
- **Key invariants**: read-only exploratory (only optional write is `pl_seasonal_score`); forward returns computed **within contract** (`groupby contract_id`) — rolls appear as NaN, dropped; uniform J+4 scoring grid across all ensemble validation scripts (cross-script comparability); query ensemble by `name='ensemble_v1_softgate_wrapper'` (not UUID); IV data sparse (2025-01-28+) — decade tests use zero-cost proxies.

---

## Load-bearing invariants (cross-subsystem — break these and prod breaks)

1. **Active-contract / `is_active` roll hazard (the big one).** Exactly one `ref_contract` row is `is_active=TRUE`. Scrapers, agents, and the engine all resolve the active contract from it at run time — **never** from a hardcoded code or `CA*0` continuous symbol (env `ACTIVE_CONTRACT` is a transient-failure fallback only). A roll is a single `poetry run roll-contract <NEW>` that flips the flag; every job auto-detects on next run, then `cc-compute-indicators --full --all-versions` backfills. The dashboard survives the gap because reads chain across rolls via **`v_contract_data_chained`** (`DISTINCT ON date ORDER BY oi DESC`) and the 4-tier `resolve_contract_for_date()` fallback. **If you introduce a new consumer, it must resolve the contract through these paths — never assume a fixed code.** (See `docs/runbooks/contract-roll-procedure.md`, memory `feedback_no_hardcoded_contracts`.)

2. **Session date vs `display_date`.** `pl_contract_data_daily.date` = session date (immutable trading day, what every `pl_*` row and all computation key on). `display_date = next_trading_day(date)` exists **only** on `pl_contract_data_daily` and is the value the frontend calendar shows. Resolution is always `display_date → session_date`, never reverse. No `-1 day` offset in the frontend.

3. **P2b two-phase date keying.** Phase A (market close, weekday) writes session `date = T`. Phase B (eve of next trading day, daily cron + `is_eve_of_trading_day()` gate) frames prompts/filenames on `target_date` (= next session) but keys **every DB write** to `data_date = get_previous_session_date(target_date) = T`. This keeps `pl_indicator_daily` / `pl_fundamental_article` / `pl_weather_observation` / `pl_orchestrator_decision` all on a single session date the dashboard can resolve. Violating it = empty dashboard sections the next morning (PRs #15–#17, #35).

4. **Migrations reach prod via `main` only.** Never `alembic upgrade head` against GCP Cloud SQL from a feature branch. DB prod revision must never be ahead of `main` (a cold-start `alembic upgrade head` then crashloops). Local DB: any branch is fine. (migrations-prod-via-main-only.)

5. **Pipeline continuity — no invented values.** DB writers receive computed values; they never hardcode a literal where a computation belongs. `pl_signal_component.raw_value` ≠ `normalized_value` (two sources). Missing computed value → NULL, never 0.0. (pipeline-continuity.)

6. **Fail loud, no silent recovery (producers).** Pipeline producers (scrapers, agents, compute jobs) exit non-zero + Sentry on any error — no auto-retry, no provider fallback, no partial output. Recovery = diagnose → fix root cause → manual relaunch. Consumers (dashboard, briefs) MAY degrade gracefully on missing upstream data. (pipeline-error-handling.)

7. **Date-aware algorithm versioning, no retroactive backfill.** `pl_indicator_daily` is keyed `(date, contract_id, algorithm_version_id)`. The dashboard prefers `ensemble_v1_softgate_wrapper` where a row exists (post 2025-12-15) and falls back to `legacy` for older dates — ensemble is **never** backfilled retroactively (look-ahead bias protection). When auto-aligned, the LLM `decision` is pinned to `ensemble.decision_wrapped`.

8. **Config-as-data.** Algorithm coefficients/thresholds, wrapper levers, macro-gate cap live in `pl_algorithm_config` rows — flip without redeploy. Hardcoded `LEGACY_V1` is fallback only. `GENERATED` columns (COT net positions) are never written directly. (north-star-alignment.)

9. **Engine math correctness.** Rolling 252-day z-scores over session date (not full-history — fixes Sheets look-ahead); Wilder RSI/ATR; symmetric Bollinger; two-pass momentum (base first). YTD / running-accuracy on **J+4** horizon (Compass override of R&D bootstrap), uniform across dashboard, briefs, and all backtest scripts.

10. **Async/sync engine separation.** `async_engine` → FastAPI only; `sync_engine` → Alembic + scripts only. `app/utils/contract_resolver.py` (async) and `scripts/contract_resolver.py` (sync) are distinct modules with distinct caches — never mixed in one process.
