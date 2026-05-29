# Réponse agent prod — Counter-proposal R&D Snapshot Bridge

```yaml
from:           Agent prod Com Compass
to:             Hedi (CTO)
date:           2026-05-19
re:             Réponse au BRIEF_PROD_OPTIMIZER_BRIDGE_2026-05-17.md
status:         counter-proposal — challenge welcome
source_brief:   ./BRIEF_PROD_OPTIMIZER_BRIDGE_2026-05-17.md
source_note:    ./NOTE_HEDI_2026-05-16.md
```

## TL;DR

- **Je rejette l'approche endpoint API du brief original.** Audit prod montre que 3 sources fondamentales (COT LCE, ERA5, ENSO + FX) **n'existent pas dans la prod** — le brief les assume implicitement. L'acceptance test rtol=1e-6 sur 92 colonnes est mathématiquement non-atteignable, et porter ces ingestions vers prod ferait exploser le scope à 3-4 semaines pour des sources qui ne servent à aucun client Com Compass.
- **Counter-proposal** : snapshot Parquet quotidien sur GCS, consommé par Julien via `gsutil`. Zéro ligne de code dans le service Cloud Run prod, zéro migration Alembic, zéro middleware auth custom, zéro surface d'attaque ajoutée à `api.com-compass.com`.
- **Effort total : 2 jours homme.** À comparer aux 3-5 jours du brief (qui sous-estimait, en plus, par 5-8 jours).
- **Couvre 100% du besoin réel** : Julien a accès **chaque matin** aux ~40 colonnes que prod produit (OHLCV + 27 indicateurs techniques + COT US + sentiment + weather), et merge côté lui dans son cockpit local avec ses propres sources externes (COT LCE / ERA5 / ENSO / FX) que R&D Compass possède déjà.

---

## 1. Pourquoi le brief original ne tient pas

### 1.1 Gap data critique

Audit du pipeline prod actuel :

| Source mentionnée dans le brief | Présente en prod ? | Détail |
|---------------------------------|--------------------|--------|
| OHLCV cocoa (ICE Europe) | ✅ | `pl_contract_data_daily` via barchart-scraper |
| 27 indicateurs techniques | ✅ | `pl_derived_indicators` via `app/engine/` |
| Scores normalisés + composite + decision | ✅ | `pl_indicator_daily` (multi-version) |
| Composantes de signal (decomposition) | ✅ | `pl_signal_component` |
| COT **US** (CFTC) | ✅ | `pl_contract_data_daily.com_net_us` via cftc-scraper |
| ICE US stocks | ✅ | `pl_contract_data_daily.stock_us` via ice-stocks-scraper |
| Press review (news) | ✅ | `pl_fundamental_article` |
| Sentiment segments (zone × theme) | ⚠️ | Table `pl_article_segment` existe mais **vide** (branche `feat/pattern-extractor` non mergée) |
| Weather forecast (6 zones Ghana/CI) | ✅ | `pl_weather_observation` (texte LLM, pas variables numériques) |
| **COT LCE (Londres / ICE Europe)** | ❌ | Aucun scraper, aucune table, aucune migration |
| **ERA5 (reanalysis ECMWF)** | ❌ | Le `meteo_agent` fait du **forecast** Open-Meteo, pas du **reanalysis** historique |
| **ENSO / ONI** | ❌ | Pas de tracker NOAA, pas de table |
| **FX (GBPUSD, DXY)** | ❌ | Aucun scraper |

**Verdict** : prod ne dispose que de **~40% des 92 colonnes** mentionnées dans la spec brief section 2.1.

### 1.2 Inversion de dépendance

C'est R&D Compass qui possède les sources enrichies (le dataset canonique `cocoa_rd_dataset_20260512.csv` ingère COT LCE / ERA5 / ENSO / FX depuis le repo R&D). Demander à prod d'absorber l'ingestion de ces sources pour servir 1 user externe :

- Ajoute 3-4 nouveaux scrapers Cloud Run Jobs (COT LCE, ERA5 mensuel, ENSO mensuel, FX daily)
- Ajoute 3-4 tables `pl_*` + migrations Alembic
- Ajoute backfill historique (10 ans pour ERA5/ENSO si on veut matcher R&D)
- Ajoute dépendances externes (NOAA NCEP, ECMWF Copernicus, ICE Europe COT, Bloomberg/Yahoo FX)
- Ajoute maintenance perpétuelle de ces sources qui ne profitent à aucun client Com Compass

**Effort total réaliste : 3-4 semaines, pas 3-5 jours.**

### 1.3 Acceptance test non-atteignable

Le brief section 3 exige parité numérique `rtol=1e-6` avec `cocoa_rd_dataset_20260512.csv` sur 92 colonnes. Avec ~50% des sources absentes côté prod, l'endpoint retournerait `null` sur ces colonnes → diff fail à la première ligne. Le critère et la réalité du pipeline sont incompatibles.

### 1.4 Surface d'attaque vs valeur

L'endpoint ajoute à `api.com-compass.com` :
- Une nouvelle route publiquement résolvable
- Un bearer token statique custom (séparé d'Auth0, rotation manuelle)
- Un middleware auth parallèle
- Un secret manager entry
- Du rate limiting, du caching, du monitoring spécifique

…pour **1 user**. Le ratio surface/valeur ne tient pas, surtout quand l'alternative est triviale.

---

## 2. Counter-proposal — Snapshot Parquet quotidien sur GCS

### 2.1 Architecture

```
Pipeline prod existant (19:00-19:30 UTC weekdays)
         │
         ▼
  pl_* tables (Cloud SQL — accès via VPC connector existant)
         │
         ▼
[NOUVEAU] cc-rnd-snapshot Cloud Run Job (19:40 UTC weekdays)
         │
         ▼
  gs://cc-rnd-snapshots/cocoa/
    ├── YYYY-MM-DD.parquet    (snapshot du jour, daté)
    ├── _latest.parquet       (pointeur stable, écrasé chaque jour)
    └── _meta.json            (schema_version, row_count, sha256, freshness)
         │
         ▼
  Julien pull en local depuis son cockpit:
    gcloud auth activate-service-account --key-file=julien-rnd-reader.json
    gsutil cp gs://cc-rnd-snapshots/cocoa/_latest.parquet ./data/prod_snapshot.parquet
         │
         ▼
  R&D Compass local merge avec ses propres sources externes
  (COT LCE / ERA5 / ENSO / FX) → cockpit Optimizer
```

**Aucun endpoint API. Aucun module dans le service Cloud Run `backend`. Aucune migration Alembic.**

### 2.2 Comparaison avec le brief original

| Critère | API route (brief original) | Snapshot GCS (cette solution) |
|---------|----------------------------|-------------------------------|
| Code dans le service `backend` | +400 LOC (router, auth, feature_builder, validator, tests) | **0 LOC** |
| Migrations Alembic | Potentiellement 3-4 (COT LCE, ERA5, ENSO, FX) | **0** |
| Nouveaux scrapers ingestion | 3-4 (COT LCE, ERA5, ENSO, FX) | **0** |
| Surface d'attaque ajoutée à `api.com-compass.com` | +1 route + bearer statique | **0** (bucket privé IAM-only) |
| Auth | Middleware custom + Secret Manager + rotation manuelle | IAM GCP standard (`roles/storage.objectViewer`) |
| Rate limit | À implémenter (slowapi config) | Inutile (GCS scale infini) |
| Cache | À implémenter (60min in-memory) | Inutile (le fichier EST le cache) |
| Coût GCP / mois | Cloud Run instance + LB + monitoring | ~$0.05 (10MB × 30j stockage + egress négligeable) |
| Suppressibilité | 1 PR + audit prod | 1 PR + 1 cmd `gcloud storage rm` |
| Effort dev | 5-8 jours minimum | **2 jours** |
| Acceptance test rtol=1e-6 sur 92 col | Mathématiquement impossible | Non-applicable (Julien merge côté lui) |
| Versioning schema | Implicite, fragile | Explicite, `schema_version` dans `_meta.json` |

### 2.3 Schéma du snapshot

Joints LEFT sur clé `(date, contract_id)` pour la commodity active (résolue via `ref_contract.is_active`), 365 derniers jours :

| Préfixe colonne | Source | Exemples |
|-----------------|--------|----------|
| `ohlc_*` | `pl_contract_data_daily` | `ohlc_open`, `ohlc_high`, `ohlc_low`, `ohlc_close`, `ohlc_volume`, `ohlc_oi`, `ohlc_iv`, `ohlc_stock_us`, `ohlc_com_net_us` |
| `tech_*` | `pl_derived_indicators` | `tech_rsi_14d`, `tech_macd`, `tech_macd_signal`, `tech_atr_14d`, `tech_bollinger_upper`, ... (27 indicateurs) |
| `score_*` | `pl_indicator_daily` (latest `algorithm_version`) | `score_rsi_z`, `score_macd_z`, `score_composite`, `score_decision`, `score_macroeco_bonus` |
| `component_*` | `pl_signal_component` | `component_rsi_contribution`, `component_macd_contribution`, ... |
| `news_*` | `pl_fundamental_article` (latest per date, `is_active=true`) | `news_summary`, `news_category`, `news_sentiment`, `news_llm_provider` |
| `weather_*` | `pl_weather_observation` (latest per date) | `weather_summary`, `weather_diagnostics_json` |

Préfixage explicite → pas de collision, schema auto-documenté, Julien sait d'où vient chaque colonne.

### 2.4 `_meta.json` exemple

```json
{
  "schema_version": "1.0.0",
  "generated_at": "2026-05-19T19:40:00Z",
  "as_of_session": "2026-05-19",
  "commodity": "cocoa",
  "active_contract": "CAN26",
  "active_algorithm_version_id": "...",
  "row_count": 365,
  "column_count": 67,
  "sha256_latest": "abc123...",
  "freshness": {
    "ohlc_last_close":      { "date": "2026-05-19", "lag_days": 0 },
    "tech_last_compute":    { "date": "2026-05-19", "lag_days": 0 },
    "score_last_compute":   { "date": "2026-05-19", "lag_days": 0 },
    "news_last_ingested":   { "date": "2026-05-19", "lag_days": 0 },
    "weather_last_obs":     { "date": "2026-05-19", "lag_days": 0 }
  },
  "pipeline_git_sha": "..."
}
```

Pas de mensonge sur ce qui n'est pas là — on n'inclut **que** les sources que prod produit réellement. Julien sait ce qu'il a, il complète avec R&D Compass pour le reste.

### 2.5 Versioning schema

`schema_version` est sémantique :
- **MINOR** : ajout de colonnes (Julien continue de fonctionner sans changement)
- **MAJOR** : suppression ou renommage (Julien doit adapter son merge)

`CHANGELOG.md` dans `backend/scripts/rnd_snapshot/` documente chaque bump. Julien check au démarrage de son cockpit, warn si différent de celui qu'il a pinned.

---

## 3. Plomberie technique

### 3.1 Nouveau script — `backend/scripts/rnd_snapshot/`

Structure standard, alignée sur les patterns existants (`cftc_scraper/`, `compass_brief/`) :

```
backend/scripts/rnd_snapshot/
├── __init__.py
├── main.py          # CLI: poetry run rnd-snapshot [--dry-run] [--date YYYY-MM-DD]
├── exporter.py      # Logic: query pl_*, build Parquet, upload GCS
├── schema.py        # Pydantic model + schema version constants
├── CHANGELOG.md     # Schema bump log
└── README.md        # Setup gsutil pour Julien + format snapshot
```

**Réutilisation** :
- Connexion DB : `app/core/database.py` (`get_async_session`)
- Modèles SQLAlchemy : `app/models/pipeline.py`
- Sentry : `app/core/sentry.py`
- Pattern Cloud Run Job : copier la structure de `backend/scripts/compass_brief/`
- Dockerfile : `backend/Dockerfile` standard (pas besoin de Playwright)

### 3.2 Cloud Run Job — `cc-rnd-snapshot`

- Region `europe-west9` (cohérent avec prod)
- 512Mi RAM, 1 CPU
- `--max-retries=0` (fail loud — cf. règle `pipeline-error-handling.md`)
- Service account dédié `cc-rnd-snapshot@cacaooo.iam.gserviceaccount.com` :
  - `roles/cloudsql.client` (lecture pl_*)
  - `roles/storage.objectAdmin` sur le bucket (write snapshots)
  - **PAS** de droit d'écriture Cloud SQL

### 3.3 Bucket GCS — `gs://cc-rnd-snapshots/`

- Region `europe-west9`
- Uniform bucket-level access + PUBLIC ACCESS PREVENTION = enforced
- Lifecycle : delete objects > 90 jours
- Versioning OFF

### 3.4 IAM accès Julien

- Service account `julien-rnd-reader@cacaooo.iam.gserviceaccount.com`
- Rôle unique `roles/storage.objectViewer` sur le bucket uniquement
- Key JSON générée + transmise hors-bande (1Password)

Côté Julien :
```bash
gcloud auth activate-service-account --key-file=julien-rnd-reader.json
gsutil cp gs://cc-rnd-snapshots/cocoa/_latest.parquet ./data/prod_snapshot.parquet
gsutil cat gs://cc-rnd-snapshots/cocoa/_meta.json | jq .
```

### 3.5 Cloud Scheduler

- Job : `cc-rnd-snapshot-trigger`
- Region `europe-west1` (cohérent — `europe-west9` ne supporte pas Cloud Scheduler)
- Cron : `40 19 * * 1-5` (19:40 UTC weekdays — 10 min après `cc-compass-brief`)
- `retryCount=0`
- OAuth-authenticated HTTP trigger vers le Cloud Run Job

### 3.6 Terraform — `infra/terraform/rnd_bridge.tf`

Fichier dédié et isolé pour suppressibilité :
- `google_storage_bucket.cc_rnd_snapshots`
- `google_service_account.cc_rnd_snapshot` + 2 IAM bindings
- `google_service_account.julien_rnd_reader` + 1 IAM binding
- `google_cloud_run_v2_job.cc_rnd_snapshot`
- `google_cloud_scheduler_job.cc_rnd_snapshot_trigger`

Un fichier unique → suppression en 1 commit le jour où R&D pivote.

---

## 4. Estimation

| Étape | Durée |
|-------|-------|
| Script Python (`main.py`, `exporter.py`, `schema.py`, tests unit) | 6h |
| Terraform (bucket, SAs, IAM, Cloud Run Job, Scheduler) | 4h |
| `.github/workflows/deploy.yml` (ajout step build + deploy job + scheduler) | 1h |
| Documentation (`README.md`, runbook `docs/runbooks/rnd-snapshot-failure.md`, section CLAUDE.md) | 2h |
| Dry-run local + tests + smoke test post-deploy | 2h |
| Handover Julien (clé SA + setup gsutil + premier pull) | 1h |
| **Total** | **2 jours homme** |

---

## 5. Ce qui n'est PAS dans le scope

- **Pas de feature engineering qui réplique R&D Compass** (lag policy ENSO, carry-forward COT LCE, merge_asof, etc.) → ça reste là où c'est, côté R&D.
- **Pas de COT LCE / ERA5 / ENSO / FX scrapers** → ça reste côté R&D Compass.
- **Pas d'acceptance test rtol=1e-6** contre `cocoa_rd_dataset_20260512.csv` → non-applicable.
- **Pas d'endpoint API HTTP** sur `api.com-compass.com`.
- **Pas de bearer token custom**, pas de cache, pas de rate limit, pas de versioning d'API.
- **Pas de SLA** — downtime de quelques heures = OK (Julien attend le snapshot du lendemain).
- **Pas d'auto-retry** sur le job (règle prod `pipeline-error-handling.md`).
- **Pas de signal trading** — outil d'observation pour 1 user, cohérent avec caveat Phase 5.

---

## 6. Vérification end-to-end

1. **Dry-run local** :
   ```bash
   poetry run rnd-snapshot --dry-run --date 2026-05-19
   ```
   → Génère le Parquet localement, log colonnes + row count, n'upload pas.

2. **Tests unit** :
   ```bash
   poetry run pytest backend/tests/test_rnd_snapshot.py
   ```
   → Mock DB, mock GCS, asserte schema + meta + idempotence.

3. **Deploy preview** : Cloud Run Job sans scheduler, trigger manuel :
   ```bash
   gcloud run jobs execute cc-rnd-snapshot --region=europe-west9 --project=cacaooo
   gsutil ls -l gs://cc-rnd-snapshots/cocoa/
   gsutil cat gs://cc-rnd-snapshots/cocoa/_meta.json
   ```

4. **Test côté Julien** :
   ```bash
   gcloud auth activate-service-account --key-file=julien-rnd-reader.json
   gsutil cp gs://cc-rnd-snapshots/cocoa/_latest.parquet ./test.parquet
   python -c "import pandas as pd; df = pd.read_parquet('test.parquet'); print(df.shape, df.dtypes)"
   ```

5. **Activer scheduler** → laisser tourner 3 jours, monitorer Sentry + Cloud Run execution logs.

6. **Comm Julien** : URL bucket + chemin + clé SA (1Password) + README.

---

## 7. Suppressibilité

Le jour où R&D pivote ou tue la track Optimizer :

```bash
# 1 PR pour le code
git rm -r backend/scripts/rnd_snapshot/
# (retirer aussi les steps deploy.yml + le fichier Terraform)

# Infra cleanup
cd infra/terraform && terraform destroy \
  -target=google_storage_bucket.cc_rnd_snapshots \
  -target=google_cloud_run_v2_job.cc_rnd_snapshot \
  -target=google_cloud_scheduler_job.cc_rnd_snapshot_trigger

gcloud iam service-accounts delete cc-rnd-snapshot@cacaooo.iam.gserviceaccount.com
gcloud iam service-accounts delete julien-rnd-reader@cacaooo.iam.gserviceaccount.com
```

**Temps cleanup : ~30 minutes. Risque résiduel : 0** (zéro couplage avec le code prod).

---

## 8. Réponse aux questions ouvertes du brief original

| Question (brief section 6) | Réponse (cette solution) |
|----------------------------|--------------------------|
| 1. Auth bearer vs IAP vs signed URL ? | **IAM GCP standard** sur bucket privé. Pas de token statique. |
| 2. Cache TTL vs recompute ? | **N/A** — le snapshot EST le cache, écrasé 1×/jour. |
| 3. Rate limit ? | **N/A** — GCS scale infini, Julien pull à la demande. |
| 4. Deployment env (mono / sidecar) ? | **Cloud Run Job** standalone, pas de service HTTP. |
| 5. Observability ? | Cloud Logging + Sentry sur le job. Pas de dashboard dédié. |
| 6. Schema drift handling ? | **`schema_version` dans `_meta.json`** + CHANGELOG.md. Julien check au démarrage. |
| 7. Backfill historique ? | Snapshot inclut 365 derniers jours par défaut. Au-delà → on génère un one-shot à la demande. |
| 8. Versioning ? | Sem-ver dans `_meta.json`, bumpé manuellement à chaque PR sur `rnd_snapshot/`. |

---

## 9. Next steps

1. **Hedi** : tu valides l'approche ou tu objectes. Si validation → tu génères les 2 service accounts GCP côté `cacaooo` project et tu valides le nommage du bucket.
2. **Moi (agent prod)** : je scaffold le script + Terraform + tests + doc. Ouverture d'une PR draft sous 1-2 jours.
3. **Julien** : reste sur son sandbox. Reçoit clé SA + URL bucket + README quand la PR est mergée.

Si tu préfères discuter ce design en 20min plutôt qu'écrit, dis-moi — mais je pense que tout est sur la table.

— Agent prod Com Compass
