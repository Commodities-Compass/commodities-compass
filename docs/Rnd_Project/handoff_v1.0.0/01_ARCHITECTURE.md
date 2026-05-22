# 01 — Architecture système et infrastructure

## Plateforme

| Composant | Détail |
|---|---|
| Cloud provider | GCP (project `cacaooo`) |
| Région compute | `europe-west9` (Paris) |
| Région scheduler | `europe-west1` (Belgique) — Cloud Scheduler ne supporte pas `europe-west9` |
| Cloud SQL | PostgreSQL 15, private IP `10.119.160.3`, accès via bastion IAP |
| Cloud Run Services | `backend` (FastAPI), `frontend` (Vite SPA) |
| Cloud Run Jobs | 14 jobs (13 schedulés + 1 manuel `cc-ensemble-bootstrap-artifacts`) |
| Cloud Scheduler | 13 crons + 1 manual job |
| Secret Manager | 13 secrets (DATABASE_URL, OPENAI_API_KEY, AUTH0_*, GOOGLE_DRIVE_*, SENTRY_DSN, etc.) |
| Bastion | VM `cc-bastion` zone `europe-west9-a` (tunneled via IAP TCP port forwarding) |
| Domaine | `api.com-compass.com` (backend), `app.com-compass.com` (frontend) — Global HTTPS LB, static IP `34.36.87.103` |
| CI/CD | GitHub Actions (`.github/workflows/ci.yml` + `deploy.yml`), keyless via Workload Identity Federation |
| Auth | Auth0 SPA (frontend) + JWT RS256 validation (backend, JWKS 6h cache) |
| Sentry | Monitoring + cron health (slugs `ensemble-compute`, `ensemble-bootstrap-artifacts`, +12 scrapers/agents) |

## Cloud Run Jobs déployés

13 jobs schedulés + 1 manuel. Pour chaque : image, mémoire, args.

| Job | Image | Mémoire | Args (poetry script) |
|-----|-------|---------|----------------------|
| `cc-barchart-scraper` | `Dockerfile.jobs` | 2Gi | `barchart-scraper` |
| `cc-ice-stocks-scraper` | `Dockerfile.jobs` | 512Mi | `ice-stocks-scraper` |
| `cc-cftc-scraper` | `Dockerfile.jobs` | 512Mi | `cftc-scraper` |
| `cc-press-review-agent` | `Dockerfile.jobs` | 1Gi | `press-review` |
| `cc-meteo-agent` | `Dockerfile.jobs` | 1Gi | `meteo-agent` |
| `cc-compute-indicators` | `Dockerfile.jobs` | 1Gi | `compute-indicators,--all-contracts,--all-versions` |
| `cc-daily-analysis` | `Dockerfile.jobs` | 1Gi | `daily-analysis,--algorithm-version,legacy` |
| `cc-compass-brief` | `Dockerfile.jobs` | 1Gi | `compass-brief` |
| `cc-enso-scraper` | `Dockerfile.jobs` | 512Mi | `enso-scraper` |
| `cc-fx-scraper` | `Dockerfile.jobs` | 512Mi | `fx-scraper` |
| `cc-ice-cot-eu-scraper` | `Dockerfile.jobs` | 512Mi | `ice-cot-eu-scraper` |
| `cc-barchart-stocks-eu-scraper` | `Dockerfile.jobs` | 512Mi | `barchart-stocks-eu-scraper` |
| **`cc-ensemble-compute`** | `Dockerfile.jobs` | **1Gi** | `ensemble-compute` |
| **`cc-ensemble-bootstrap-artifacts`** | `Dockerfile.jobs` | 1Gi | `ensemble-bootstrap-artifacts` (manual trigger only, no scheduler) |

Tous : `--max-retries=0` (fail-loud), `cc-cloud-run-jobs@cacaooo.iam.gserviceaccount.com` SA, VPC connector `cc-vpc-connector`.

Image registries : `europe-west9-docker.pkg.dev/cacaooo/commodities-compass/{backend,jobs}` — multi-tag par commit-sha pour audit.

## Pipeline schedule complet (UTC weekdays)

```
18:30  cc-fx-scraper                  ── ECB SDMX FX rates       → pl_external_indicator.fx_*
19:00  cc-barchart-scraper            ── Barchart OHLCV+IV       → pl_contract_data_daily (insert row)
19:00  cc-meteo-agent                 ── Open-Meteo + GPT-4.1    → pl_weather_observation (independent)
19:05  cc-ice-stocks-scraper          ── ICE XLS public          → pl_contract_data_daily.stock_us (update)
19:05  cc-cftc-scraper                ── CFTC COT HTML            → pl_contract_data_daily.com_net_us (update)
19:05  cc-press-review-agent          ── 6 news sources + OpenAI → pl_fundamental_article + pl_article_segment (4 themes)
19:10  cc-barchart-stocks-eu-scraper  ── Barchart cmdty HTML     → pl_contract_data_daily.stock_eu_bags60kg (update)
19:15  cc-compute-indicators          ── Local DAG (no LLM)       → pl_derived_indicators + pl_indicator_daily (raw scores)
       ↓ (depends on OHLCV + indicators)
19:18  cc-ensemble-compute            ── 14 specialists + SG + WR → pl_specialist_prediction (14) + pl_orchestrator_decision (1) + pl_indicator_daily (1 UPSERT)
       ↓ (parallel — both consume pl_indicator_daily)
19:20  cc-daily-analysis              ── 2 GPT-4-turbo calls     → pl_indicator_daily.macroeco_* + conclusion (legacy LLM agent)
19:30  cc-compass-brief               ── Build .txt from pl_*    → Google Drive (NotebookLM input)
22:10  cc-ice-cot-eu-scraper          ── ICE public CSV           → pl_cot_eu_weekly (weekly snapshot)

Monthly (20th, 22:00 UTC) :
       cc-enso-scraper                ── NOAA PSL ASCII           → pl_external_indicator.enso_*
```

## Dépendances data critiques

```
cc-barchart-scraper  ┐
                     ├──► cc-compute-indicators ──► cc-ensemble-compute
cc-ice-stocks        │                                  ▲
cc-cftc              │                                  │
cc-press-review      ┴──────────────────────────────────┘
                     (pl_article_segment for MacroSignal)
```

Si `cc-press-review-agent` fail le matin → `cc-ensemble-compute` fail à 19:18 (`EnsembleLoaderError: pl_article_segment empty`). Pas de fallback macro stub (`pipeline-error-handling.md` rule).

Si `cc-barchart-scraper` fail → `cc-compute-indicators` fail (pas de close pour calculer indicators) → `cc-ensemble-compute` fail.

`cc-meteo-agent` et `cc-daily-analysis` sont indépendants du chain ensemble — leur fail n'arrête pas ensemble.

## Migrations Alembic — chronologie Campaign 5

| Revision | Date | Migration | Objet créé |
|----------|------|-----------|-----------|
| `f0a1b2c3d4e5` | 2026-05-20 | add_pl_external_indicator | Table `pl_external_indicator` (commodity-agnostic ENSO+FX) |
| `g1b2c3d4e5f6` | 2026-05-20 | add_pl_cot_eu_weekly | Table `pl_cot_eu_weekly` (ICE Europe COT) |
| `h2c3d4e5f6g7` | 2026-05-20 | add_stock_eu_bags60kg | Colonne `pl_contract_data_daily.stock_eu_bags60kg` |
| `i3d4e5f6g7h8` | 2026-05-21 | add_pl_model_artifact | Table `pl_model_artifact` (BYTEA registry) |
| `j4e5f6g7h8i9` | 2026-05-21 | add_pl_specialist_prediction | Table `pl_specialist_prediction` (14 votes/jour) |
| `k5f6g7h8i9j0` | 2026-05-21 | add_pl_orchestrator_decision | Table `pl_orchestrator_decision` (SG + WR audit) |
| `l6g7h8i9j0k1` | 2026-05-21 | seed_ensemble_algorithm_version | Row `ensemble_v1_softgate_wrapper` v1.0.0 + 22 config rows (5 SG + 13 wrapper + 14 cluster) |
| `m7h8i9j0k1l2` | 2026-05-21 | set_ensemble_v1_inactive_shadow | `is_active=FALSE, compute_enabled=FALSE` (shadow mode safeguard) |
| `n8i9j0k1l2m3` | 2026-05-21 | create_v_contract_data_chained | VIEW `v_contract_data_chained` (front-month-by-OI) |
| `o9j0k1l2m3n4` | 2026-05-22 | seed_compass_wrapper_threshold | Row `pl_algorithm_config.compass_wrapper_dispersion_with_acc_threshold = 0.60` |

Head DB prod actuel : `o9j0k1l2m3n4`.

Précédent head (avant Campaign 5) : `e5f6a7b8c9d0` (widen sentiment_raw_score precision, 2026-04-20).

## Étapes d'exécution `cc-ensemble-compute` (step-by-step)

```python
# scripts/ensemble_compute/main.py
1.  Resolve contract_id (active or historical front-month-by-OI)
2.  Resolve algorithm_version_id ('ensemble_v1_softgate_wrapper')
3.  Resolve training_month (MAX from pl_model_artifact.specialist_model rows)
4.  Load cluster_mapping (14 rows from pl_algorithm_config WHERE param LIKE 'cluster_%')
5.  Instantiate DBArtifactLoader(adapter, algo_version_id)
6.  pipeline = EnsemblePipeline.from_loader(loader, training_month, cluster_mapping)
       ├─► Load 14 specialist_model + 14 specialist_hp (BYTEA → pickle.loads)
       ├─► Load anomaly_veto + structural_priors + regime_clusters (long_run)
       ├─► Load soft_gate_config + wrapper_config (tuned_configs)
       └─► Load regime_tags canonical_snapshot
7.  Load compass_wrapper_threshold from pl_algorithm_config
8.  Assert vendor wrapper config has use_trend_conflict=False AND use_three_way_disagreement=False
9.  Swap pipeline.wrapper = CompassTransitionWrapper(config, cluster_mapping, threshold)
10. Load market_history (v_contract_data_chained × pl_derived_indicators, 600d trailing)
11. Load recent_decisions (pl_orchestrator_decision LIMIT 10 trailing, with forward_return LATERAL on chained view)
12. Load recent_votes (pl_specialist_prediction window 10d trailing)
13. Load macro_signal (pl_article_segment 90d window → MacroEventLayer.fit().score_for_date())
14. decision = pipeline.decide(DecideRequest{today, contract_id, market_history, recent_decisions, recent_votes, macro})
       ├─► Run 14 specialists in parallel → per_specialist_votes
       ├─► Compute anomaly + priors + regime weights → OrchestratorContext
       ├─► SoftGateOrchestrator.decide(context) → SoftGateDecision
       └─► CompassTransitionWrapper.apply(decisions_df, votes_df, returns_series) → wrapped_decision + diagnostics
15. Write 14 rows pl_specialist_prediction + 1 row pl_orchestrator_decision + 1 row UPSERT pl_indicator_daily
16. session.commit()
17. Sentry.set_context('ensemble_decision', {...}) + log SUCCESS
```

Runtime observé en prod : ~40-60s par execution (charge 38 BYTEA + 600d × 14 specialists + 1330+ recent_votes window).

## Convention vendor read-only

Le package `backend/vendor/campaign5_ensemble_v1.0.0/` est **read-only par convention R&D**. Compass ne patche jamais le code vendor. 3 paths d'override autorisés :

| Path | Quand | Exemple |
|------|-------|---------|
| Config-only (DB) | Tuner un threshold sans changer la logique | `compass_wrapper_dispersion_with_acc_threshold = 0.60` dans `pl_algorithm_config` |
| Subclass + override hook | Changer une logique de combinaison ou un fallback | `CompassTransitionWrapper(TransitionProtectionWrapper)` |
| Bypass total | Skip un composant vendor (large blast radius) | (jamais utilisé en v1.0.0) |

La v1.0.0 utilise **path #2** pour `CompassTransitionWrapper` (relaxation dispersion-only veto) et **path #1** pour le threshold (config-as-data).

## Sécurité + IAM

Service account `cc-cloud-run-jobs@cacaooo.iam.gserviceaccount.com` (jobs runtime) — roles :
- `roles/secretmanager.secretAccessor` (lit secrets DB URL, API keys, Sentry DSN)
- `roles/cloudsql.client` (R/W sur Cloud SQL via private IP)
- `roles/logging.logWriter` (Cloud Logging)
- `roles/monitoring.metricWriter` (custom metrics, Sentry crons)
- `roles/run.developer` (peut invoquer d'autres Cloud Run Jobs si chaîne future)

GitHub Actions : `cc-github-actions@cacaooo.iam.gserviceaccount.com` via Workload Identity Federation (keyless, OIDC token Github → STS GCP). Pas de SA key files.

Auth0 : SPA client + RS256 JWT. Backend valide via JWKS (cache 6h). Pas de cookies, tokens stockés `localStorage` (`auth0_token`).

## Observabilité

| Stack | Détail |
|-------|--------|
| Logs Cloud Run | Stackdriver, retention 30d. Filterable par `resource.labels.job_name="cc-ensemble-compute"`. |
| Cloud Logging severity | INFO par défaut (`configure_logging()` + `--verbose` pour DEBUG) |
| Sentry errors | `sentry_sdk.capture_exception(exc)` au top-level try/except de chaque main() |
| Sentry crons | `@sentry_sdk.crons.monitor(monitor_slug='ensemble-compute')` (= ping at start + end ; alert si missing) |
| Sentry contexts | `set_context('ensemble_decision', {target_date, wrapped_decision, fired_running_acc, fired_dispersion, n_specialists})` |
| Custom metrics | Aucune (Cloud Monitoring n'a pas de metric custom Compass au-delà des HTTP req counts) |
| DB query observability | Aucune (pas de pg_stat_statements export) — à ajouter si latence ensemble-compute monte |

## Network / Auth

- Cloud SQL private IP only — accessible :
  - Depuis Cloud Run Jobs : via VPC connector
  - Depuis dev local : via `./.local/db-prod.sh up` (IAP TCP forwarding bastion → `:5434` local)
- API publique `api.com-compass.com` derrière HTTPS Load Balancer
- Frontend `app.com-compass.com` CSP whitelisted : `*.com-compass.com`, `*.auth0.com`, `*.sentry.io`
- CORS backend : whitelist Auth0 audience + own origin

## Disaster recovery

| Scénario | Procédure |
|----------|-----------|
| `cc-ensemble-compute` crash en boucle | `gcloud scheduler jobs pause cc-ensemble-compute --location=europe-west1` puis investigate (cf runbook). Dashboard unaffected (shadow mode). |
| Bad decisions écrits en prod | Scoped DELETE sur `pl_orchestrator_decision` / `pl_specialist_prediction` / `pl_indicator_daily` WHERE `algorithm_version_id = ensemble_v1`. Re-backfill via `.local/backfill_ensemble_prod.sh`. |
| Backend service crash post-deploy | Auto-failover sur revision précédente (Cloud Run traffic routing). Revert merge commit en cas de need. |
| Cloud SQL outage | Aucun DR actif (HA non activé). Restore from latest backup (~daily). |
| Bastion VM down | Auto-restart via Cloud Run / VM start. Si gcloud auth expired : `gcloud auth application-default login`. |

## Référence

- Code Compass-side : `backend/scripts/ensemble_compute/` (4 fichiers : main.py, db_loader.py, db_writer.py, compass_wrapper.py + cluster_mapping_loader.py)
- Vendor R&D : `backend/vendor/campaign5_ensemble_v1.0.0/` (intouchable)
- Terraform infra : `infra/terraform/` (state sur GCS bucket `tf-state-cacaooo/terraform/state`)
- Workflows CI/CD : `.github/workflows/ci.yml` + `deploy.yml`
- Runbooks : `docs/runbooks/` (notamment `ensemble-failure-recovery.md`)
