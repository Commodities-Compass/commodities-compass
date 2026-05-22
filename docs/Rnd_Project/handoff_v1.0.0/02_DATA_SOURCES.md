# 02 — Data sources ingérées

Toutes les sources externes consommées par la pipeline Compass. **Aucune** ne nécessite d'auth payante : tout est public ou via SA Google Drive en read-only.

## Vue d'ensemble

| Job | Cadence (UTC) | Source | Output table | Idem | LLM cost |
|-----|---------------|--------|--------------|------|----------|
| `cc-barchart-scraper` | `0 19 * * 1-5` | Barchart HTML (no auth) | `pl_contract_data_daily` (insert OHLCV+IV) | UPSERT | none |
| `cc-ice-stocks-scraper` | `5 19 * * 1-5` | ICE public XLS | `pl_contract_data_daily.stock_us` (update) | Conditional update | none |
| `cc-cftc-scraper` | `5 19 * * 1-5` | CFTC HTML public | `pl_contract_data_daily.com_net_us` (update) | Conditional update | none |
| `cc-press-review-agent` | `5 19 * * 1-5` | 6 news sources (URLs) + OpenAI `o4-mini` | `pl_fundamental_article` + `pl_article_segment` (4 themes) | Per-(date, provider) | $1-2 / day |
| `cc-meteo-agent` | `0 19 * * 1-5` | Open-Meteo (no auth) + OpenAI `gpt-4.1` | `pl_weather_observation` | Per date | $1-2 / day |
| `cc-enso-scraper` | `0 22 20 * *` | NOAA PSL ASCII | `pl_external_indicator.enso_*` | Per (date) UPSERT | none |
| `cc-fx-scraper` | `30 18 * * 1-5` | ECB SDMX CSV | `pl_external_indicator.fx_*` | Per (date) UPSERT | none |
| `cc-ice-cot-eu-scraper` | `10 22 * * 1-5` | ICE public CSV (annual) | `pl_cot_eu_weekly` (weekly) | Per (release_date, contract_market) | none |
| `cc-barchart-stocks-eu-scraper` | `10 19 * * 1-5` | Barchart HTML cmdty | `pl_contract_data_daily.stock_eu_bags60kg` (update only) | Conditional update | none |
| `cc-compute-indicators` | `15 19 * * 1-5` | Reads pl_contract_data_daily | `pl_derived_indicators` + `pl_indicator_daily` | UPSERT per (date, contract, algo_version) | none |
| **`cc-ensemble-compute`** | **`18 19 * * 1-5`** | **Reads pl_* tables + vendor artifacts** | **`pl_specialist_prediction` + `pl_orchestrator_decision` + `pl_indicator_daily` (UPSERT)** | **Per (date, contract, algo_version)** | **none** |
| `cc-daily-analysis` | `20 19 * * 1-5` | Reads pl_* + OpenAI `gpt-4-turbo` | `pl_indicator_daily.macroeco_* + conclusion` (legacy fields) | UPSERT | $0.50-1 / day |
| `cc-compass-brief` | `30 19 * * 1-5` | Reads pl_* | Google Drive (.txt for NotebookLM) | Per date (overwrite) | none |
| `cc-ensemble-bootstrap-artifacts` | manual | `backend/vendor/.../frozen/` (BYTEA load) | `pl_model_artifact` (38 rows) | One-shot UPSERT | none |

## Source par source

### `cc-barchart-scraper`
- **File** : `backend/scripts/barchart_scraper/`
- **Source** : `https://www.barchart.com/futures/quotes/{CONTRACT}/overview` + `/volatility-greeks` (London Cocoa #7, ICE Europe, GBP/tonne)
- **Method** : Playwright headful → extracts inline JSON raw blocks (max-volume heuristic to pick correct contract block among 4+). IV via XHR interception or HTML regex fallback.
- **Active contract** : Resolved from `ref_contract.is_active=TRUE` at runtime (`resolve_active_code()`). NEVER hardcoded.
- **Volume** : raw contract count (no conversion)
- **IV conversion** : percentage → decimal (e.g., `55.38 → 0.5538`)
- **Output** : 1 row INSERT in `pl_contract_data_daily` per (date, contract_id) — UNIQUE constraint prevents duplicates.
- **Side effect** : Sets `display_date = next_trading_day(date)` for dashboard masthead.
- **Fail-loud** : Network/parse/UNIQUE violation → exit non-0. No auto-retry.
- **Backfill history** : 2016-01-04 → 2026-05-21 (2615 rows over 10+ years, ~250 trading days/year, multi-contract per delivery month).

### `cc-ice-stocks-scraper`
- **File** : `backend/scripts/ice_stocks_scraper/`
- **Source** : `https://www.ice.com/publicdocs/futures_us_reports/cocoa/cocoa_cert_stock_YYYYMMDD.xls`
- **Method** : Pure httpx + pandas. Walks back business days (up to 60) until report found. Parses "GRAND TOTAL" row, converts bags → tonnes (`bags × 70 / 1000`).
- **Output** : `pl_contract_data_daily.stock_us` update on active contract row (5min after barchart-scraper to ensure row exists).
- **Fail-loud** : 404/parse errors → exit non-0.

### `cc-cftc-scraper`
- **File** : `backend/scripts/cftc_scraper/`
- **Source** : `https://www.cftc.gov/dea/futures/ag_lf.htm`
- **Method** : Pure httpx + regex. Parses "COCOA - ICE FUTURES U.S." section, extracts Producer/Merchant Long − Short.
- **Cadence note** : Daily UPSERT (idempotent). New data only Friday post-21:30 CET (CFTC weekly publish). Daily cron catches late publishes.
- **Output** : `pl_contract_data_daily.com_net_us` (commercial net position).
- **Fail-loud** : HTTP/parse errors → exit non-0.

### `cc-press-review-agent`
- **File** : `backend/scripts/press_review_agent/`
- **Source** : 6 news URLs (cocoa industry, daily English+French scraping → consolidated for LLM)
- **LLM provider** : OpenAI `o4-mini` (production). Claude / Gemini available via `--provider claude|gemini|all` for testing only.
- **Active flag** : `pl_fundamental_article.is_active` controls which provider's articles dashboard reads. Set by `PRODUCTION_PROVIDER` in `config.py` = `openai`.
- **Contract context** : Prompt injects active contract code + delivery month (e.g., `CAK26`, `2026-07`) via `contract_resolver`.
- **Output** : 1 row `pl_fundamental_article` + 4 rows `pl_article_segment` (themes : `production`, `chocolat`, `transformation`, `economie`) per day.
- **Extraction version** : `inline_v1` (current). Legacy `v1` for old extractions.
- **Fail-loud** : LLM parse error → exit non-0. No fallback to neutral / claude / gemini (rule `pipeline-error-handling.md`).
- **Cost** : ~$1-2/day (5-10 articles × 2k tokens × $0.005).

### `cc-meteo-agent`
- **File** : `backend/scripts/meteo_agent/`
- **Source** : Open-Meteo API (free, no auth) for 6 cocoa-growing locations (3 Côte d'Ivoire + 3 Ghana) + OpenAI `gpt-4.1`
- **Locations** : Daloa, San-Pédro, Soubré (CI) + Kumasi, Takoradi, Goaso (GH)
- **Output** : `pl_weather_observation` (summary, impact_assessment, diagnostics JSONB)
- **Fail-loud** : Open-Meteo HTTP/LLM error → exit non-0.

### `cc-enso-scraper`
- **File** : `backend/scripts/enso_scraper/`
- **Source** : NOAA Physical Sciences Laboratory ASCII
  - `https://psl.noaa.gov/data/correlation/oni.data` (ONI monthly)
  - `https://psl.noaa.gov/data/correlation/nina34.anom.data` (Niño 3.4 anomaly)
- **Format** : `year jan feb ... dec` ASCII. Missing sentinel `-99.9*` filtered.
- **Output** : `pl_external_indicator` (partial UPSERT — preserves FX columns)
  - `enso_oni_month` (DECIMAL)
  - `enso_nino34_anomaly` (DECIMAL)
- **Cadence** : Monthly 20th 22:00 UTC (NOAA publishes mid-month for prior month, 5-day buffer).
- **Lag policy** : 14 days applied at compute-time by ensemble engine, NOT by scraper.
- **Backfill** : 1950-2026, 950+ rows (one row per month-first).
- **CLI backfill** : `poetry run enso-scraper-backfill --verify` (from `docs/onboarding/ENSO/{oni,nino34}_monthly.csv`).

### `cc-fx-scraper`
- **File** : `backend/scripts/fx_scraper/`
- **Source** : ECB SDMX 2.1 CSV (free, no auth)
  - `https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A?format=csvdata`
  - `https://data-api.ecb.europa.eu/service/data/EXR/D.GBP.EUR.SP00.A?format=csvdata`
- **Method** : Pure httpx + stdlib csv. Combines 2 series by date (union).
- **Output** : `pl_external_indicator` (partial UPSERT — preserves ENSO columns)
  - `fx_dxy_proxy = 1 / usd_per_eur` (USD strength proxy)
  - `fx_eurusd = 1 / usd_per_eur` (alias of dxy_proxy)
  - `fx_gbpusd = usd_per_eur / gbp_per_eur` (consumed by C5 specialists)
  - `fx_gbpeur = gbp_per_eur` (raw passthrough)
- **Backfill** : 2014-2026, ~3000 rows (business days only).
- **Why ECB not yfinance/FRED/Stooq** : R&D rejected those (Cloudflare blocks, API-key, rate limits). ECB = most reliable open source.

### `cc-ice-cot-eu-scraper`
- **File** : `backend/scripts/ice_cot_eu_scraper/`
- **Source** : `https://www.theice.com/publicdocs/futures/COTHist{YYYY}.csv` (one file per year, ~175 columns, UTF-8 BOM)
- **Filter** : `Market_and_Exchange_Names == "ICE Cocoa Futures - ICE Futures Europe"` + `FutOnly_or_Combined == "FutOnly"`
- **Method** : Pure httpx + stdlib `csv.DictReader`. BOM-stripping + strict header validation (fail-loud on schema drift).
- **Lag** : `release_date = report_date + 3 days` (ICE/CFTC convention).
- **Output** : `pl_cot_eu_weekly` (weekly snapshot table) with Producer/Merchant (long/short), Managed Money (long/short — the R&D signal), Other Reportables, Non-Reportable, Open Interest.
- **GENERATED columns** : `prod_merc_net`, `m_money_net` (Postgres-computed, never written directly).
- **Cadence** : Daily 22:10 UTC weekdays (UPSERT idempotent on `(release_date, contract_market)`). ICE publishes Friday ~21:30 CET for prior Tuesday's snapshot.
- **Backfill** : 2014-2026, 607 rows (~52 weeks × 12 years).
- **CLI backfill** : `poetry run ice-cot-eu-scraper --year YYYY`

### `cc-barchart-stocks-eu-scraper`
- **File** : `backend/scripts/barchart_stocks_eu_scraper/`
- **Source** : `https://www.barchart.com/cmdty/data/fundamental/explore/IC345DRW.CS` (Barchart convention: `.CS` = Cocoa Stocks)
- **Method** : Pure httpx + BeautifulSoup. Two HTML tables : metadata + 7-day history. Native unit `60 Kg Bag` + Multiplier `1` validated in parser.
- **Output** : `pl_contract_data_daily.stock_eu_bags60kg` UPDATE only (never INSERT — OHLCV row must already exist from `cc-barchart-scraper`).
- **Fail-loud** : Missing OHLCV row → `StockEuRowMissingError`. Unit/Multiplier drift → fail.
- **Backfill** : 2024-11 → 2026-05, 333 dates with non-NULL stock_eu_bags60kg.
- **Historical depth available** : 2012-02-07 onwards (14+ years on Barchart, but only backfilled 18 months — additional history one-shot if needed).

### `cc-compute-indicators` (existant, déjà legacy avant Campaign 5)
- **File** : `backend/scripts/compute_indicators/` (or `backend/app/engine/runner.py`)
- **Method** : Topological DAG over 14 technical indicators. No LLM, no external API.
- **Output** : `pl_derived_indicators` (raw indicator values per date+contract) + `pl_indicator_daily` (scored z-scores + composite + decision per algorithm_version).
- **Algorithm versions supported** : `legacy 1.0.0`, `legacy 1.0.1`, `power10years 2.0.0`, `ensemble_v1_softgate_wrapper 1.0.0`. With `--all-versions` flag : compute every `compute_enabled=TRUE` version.
- **Caveat** : `ensemble_v1_softgate_wrapper.compute_enabled=FALSE` → cc-compute-indicators does NOT write ensemble's pl_indicator_daily row. The ensemble's row is written by `cc-ensemble-compute` only.

### `cc-ensemble-compute` (le sujet principal)
- **File** : `backend/scripts/ensemble_compute/main.py`
- **Source** : Reads many `pl_*` tables + vendor artifacts (loaded once from `pl_model_artifact` BYTEA at boot).
- **Reads** (exact tables) :
  - `pl_contract_data_daily` (via VIEW `v_contract_data_chained`) — 600d market_history
  - `pl_derived_indicators` — joined on (date, contract_id) with chained VIEW
  - `pl_orchestrator_decision` — trailing 10d (LIMIT 10) for wrapper running_acc + recent_decisions
  - `pl_specialist_prediction` — trailing 10d window for wrapper cluster_dispersion
  - `pl_article_segment` — 90d window (confidence ≥ 0.70 filtered inside MacroEventLayer)
  - `pl_model_artifact` — 38 BYTEA artifacts (loaded at job init)
  - `pl_algorithm_config` — cluster mapping (14 rows) + Compass threshold (1 row)
  - `pl_algorithm_version` — version_id resolution + training_month
- **Does NOT read** (despite being available) :
  - `pl_cot_eu_weekly` — Managed Money signal R&D-prepared but unused in v1.0.0
  - `pl_weather_observation` — used by legacy daily-analysis only
  - `pl_seasonal_score` — context for meteo-agent prompt only
  - `pl_external_indicator.enso_*` — see `06_DATA_NOT_USED.md` (to verify if MacroEventLayer reads it via macro_segments or not)
  - `pl_sentiment_feature` — shadow mode, threshold n≥250 not met (~October 2026)
- **Writes** : 14 rows `pl_specialist_prediction` + 1 row `pl_orchestrator_decision` + 1 row UPSERT `pl_indicator_daily`.
- **Fail-loud** : Missing market_history row, empty pl_article_segment 90d window, missing pl_model_artifact rows, missing cluster_mapping rows, missing Compass threshold row → `EnsembleLoaderError` exit non-0.
- **Cost** : None (no LLM). Pure compute on vendor frozen models.

### `cc-ensemble-bootstrap-artifacts`
- **File** : `backend/scripts/ensemble_bootstrap/main.py` (wraps R&D `tools/load_artifacts_to_pg.py`)
- **Source** : `backend/vendor/campaign5_ensemble_v1.0.0/frozen/` directory
- **Output** : 38 rows in `pl_model_artifact` (BYTEA + SHA-256 + provenance JSONB) :
  - 14 `specialist_model` (.pkl loaded as BYTEA)
  - 14 `specialist_hp` (.json loaded as BYTEA)
  - 1 `long_run_anomaly`
  - 1 `long_run_priors`
  - 1 `long_run_regime_clusters`
  - 2 `tuned_config` (soft_gate.json + transition_wrapper.json)
  - 5 `canonical_snapshot` (R&D test data : `pl_contract_data_daily.parquet`, `pl_derived_indicators.parquet`, `pl_article_segment.parquet`, `ref_contract.parquet`, `regime_tags.csv`)
- **Trigger** : Manual via `gcloud run jobs execute cc-ensemble-bootstrap-artifacts --region=europe-west9`. No scheduler.
- **When to run** : Initial setup (already done 2026-05-21) + every new R&D vendor release (v1.1.0+).
- **Fail-loud** : SHA-256 mismatch → exit non-0. UPSERT idempotent on `(algorithm_version_id, artifact_kind, artifact_name, training_month)`.

### `cc-daily-analysis` (legacy LLM, **PAS** déprécié)
- Continue de tourner en parallèle de l'ensemble (19:20 UTC)
- Lit `pl_indicator_daily` (decision écrit par ensemble OU legacy selon `is_active`)
- Pinned to `--algorithm-version legacy` → can NEVER overwrite ensemble's pl_indicator_daily.decision
- Écrit `macroeco_score`, `macroeco_bonus`, `eco`, `conclusion`, `confiance`, `direction` (champs LLM-generated text dashboard-facing)
- À termer une fois l'ensemble en live + frontend adapté

### `cc-compass-brief`
- Inchangé, génère le `.txt` quotidien pour NotebookLM podcast audio. Lit `pl_indicator_daily` + autres pl_* pour synthèse.

### `cc-compute-sentiment-features` (shadow, pas critique)
- **File** : `backend/scripts/compute_sentiment_features/main.py`
- Lit `pl_article_segment` (extraction_version='inline_v1', zone='all'), agrège par (date, theme), calcule rolling z-score 21d + delta 3d
- Output : `pl_sentiment_feature` (shadow mode, seuil n≥250 not yet reached)
- Activé si la pipeline atteint 250 observations par theme (~October 2026 selon le rythme actuel)

## Backfill historique disponible

| Source | Backfill range | Rows | CLI |
|--------|---------------|------|-----|
| `pl_contract_data_daily` | 2016-01-04 → 2026-05-21 | 2615 (10+ years, multi-contract) | barchart historical (one-shot via R&D snapshot or manual) |
| `pl_derived_indicators` | Same range | 2612 | `poetry run compute-indicators --all-contracts --full` |
| `pl_external_indicator.enso_*` | 1950-2026 | 950+ months | `poetry run enso-scraper-backfill --verify` |
| `pl_external_indicator.fx_*` | 2014-2026 | ~3000 business days | `poetry run fx-scraper-backfill --verify` |
| `pl_cot_eu_weekly` | 2014-10-03 → 2026-05-15 | 607 weeks | `poetry run ice-cot-eu-scraper --year YYYY` (looping) |
| `pl_contract_data_daily.stock_eu_bags60kg` | 2024-11 → 2026-05 | 333 dates | `poetry run barchart-stocks-eu-scraper --backfill` |
| `pl_article_segment` | 2025-04-30 → 2026-05-21 | 751 (672 v1 + 79 inline_v1) | Backfill via `cc-press-review-agent` daily |
| `pl_orchestrator_decision (ensemble)` | 2025-12-15 → 2026-05-21 | 105 | `.local/backfill_ensemble_prod.sh` (already executed once) |
| `pl_specialist_prediction (ensemble)` | Same | 1470 (= 105 × 14) | Same script |

## Coûts récurrents

| Job | Mensuel | Volume |
|-----|---------|--------|
| `cc-press-review-agent` | ~$30-60 | OpenAI o4-mini, 5-10 articles × ~2k tokens/jour, 22 jours ouvrés |
| `cc-meteo-agent` | ~$30-60 | OpenAI gpt-4.1, 6 locations × ~1k tokens/jour |
| `cc-daily-analysis` | ~$15-30 | OpenAI gpt-4-turbo, 2 calls/jour × 1500 tokens |
| `cc-ensemble-compute` | **$0** | Pure compute (no LLM) |
| Cloud Run Jobs compute | ~$15-30 | 14 jobs × ~3 min/jour × 22 jours @ 1-2 vCPU |
| Cloud SQL | ~$70-100 | db-f1-micro tier (à upgrade quand volume monte) |
| Cloud Storage (artifacts) | ~$5 | Docker images + GCS state Terraform |
| **Total** | **~$150-220/mois** | |
