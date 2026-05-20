# Scraper FX — USD strength + GBP/USD pour les spécialistes (9/14)

**Statut :** Proposed (non implémenté)
**Date :** 2026-05-19
**Owner :** TBD (Hedi)
**Slug :** `scraper-fx`
**Cible repo :** `docs/user-stories/P1-scraper-fx.md`
**Deadline :** P1 — 1 sprint (~1 semaine)
**Dépendance launch C5 :** bloquante (9/14 spécialistes consomment FX — tous les panels `fx_focus` + variantes `+garch_fx` / `fx_enso_focus`)

---

## 1. Contexte

Le déploiement Campaign 5 ensemble ([CAMPAIGN_5_PROD_DEPLOYMENT.md](../onboarding/CAMPAIGN_5_PROD_DEPLOYMENT.md)) requiert deux features FX consommées par **9 des 14 spécialistes** ([HEDI_DATA_MAP.md §1.2-1.3](../onboarding/HEDI_DATA_MAP.md)) — la cocoa London #7 cote en GBP, l'USD strength influence directement les flux exportateurs Côte d'Ivoire/Ghana :

- `fx_dxy_proxy` — USD strength proxy = `1 / (USD per EUR)`. Rises when USD strengthens.
- `fx_gbpusd` — USD per 1 GBP = `(USD per EUR) / (GBP per EUR)`. Direct hedge currency exposure pour LCE.

Optionnellement (audit only, non consommé directement) :
- `fx_eurusd` = `1 / (USD per EUR)` (alias DXY proxy, redondant)
- `fx_gbpeur` = `GBP per EUR` (raw — utile pour cross-check + future features)

Aucun feed FX n'existe en prod aujourd'hui ([Q1 R&D doc](../onboarding/CAMPAIGN_5_PROD_DEPLOYMENT.md#L137)). Le code R&D du scraper est déjà disponible et propre : [docs/onboarding/ingest_fx.py](../onboarding/ingest_fx.py) (~70 LOC, ECB SDMX 2.1 CSV parsing).

**Pourquoi maintenant** : sans FX en prod, 9/14 spécialistes ne peuvent pas inférer correctement. **Plus grand point d'aveuglement** des spécialistes après ENSO (mais avec impact daily vs monthly). Bloque le launch C5.

**Backfill historique** : ~12 ans de données daily business-days disponibles via ECB SDMX (2014-01 → today), CSV pré-calculés disponibles dans [docs/onboarding/FX/](../onboarding/FX/) (`dxy_proxy_daily.csv`, `gbpusd_daily.csv`, ~3164 rows chacun). Le backfill se fait **au launch** via script one-shot, puis scraper en forward-only daily.

---

## 2. Goals & non-goals

### Goals (cette itération)

- Créer le scraper `cc-fx-scraper` (Cloud Run Job daily business-days) qui écrit dans `pl_external_indicator` (table mutualisée avec [P1-scraper-enso.md](P1-scraper-enso.md))
- Backfill 12 ans (2014-01 → today, ~3164 rows) au launch via script one-shot
- Si l'US ENSO ship en premier : pas de nouvelle migration nécessaire (les colonnes FX existent déjà dans `pl_external_indicator`). Sinon : la migration mutualisée crée la table avec toutes les colonnes ENSO + FX.
- Crons Cloud Scheduler + terraform + deploy.yml
- Tests unit + intégration TDD (80%+ coverage)
- Sentry monitor + fail-loud
- **Window de validation 5 jours ouvrés** avant déclaration "stable"
- Doc mise à jour dans `CLAUDE.md` (section Scrapers)

### Non-goals

- **Pas** de scrape ENSO dans cette US (traité dans [P1-scraper-enso.md](P1-scraper-enso.md), migration mutualisée)
- **Pas** de calcul de z-score / normalisation côté scraper — features dérivées (`fx_dxy_proxy_zscore_60d`, etc.) calculées par l'engine ensemble (matches le pattern rolling normalization, [.claude/rules/north-star-alignment.md](../../.claude/rules/north-star-alignment.md) rule #6)
- **Pas** d'auto-retry sur le job (règle prod `pipeline-error-handling.md`)
- **Pas** de nouvelle UI dashboard
- **Pas** d'autres paires FX (AUD, JPY, CHF) — hors scope C5
- **Pas** de scrape d'autres types de FX data (forward rates, swap points, central bank intervention) — hors scope
- **Pas** d'utilisation de yfinance/FRED/Stooq comme fallback — l'R&D les a éliminés (Cloudflare + API-key, [ingest_fx.py:3](../onboarding/ingest_fx.py))

---

## 3. Source & cadence

### 3.1 ECB SDMX — Free, no auth

| Série | URL | Format | Cadence publication |
|---|---|---|---|
| USD per EUR | `https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A?format=csvdata` | CSV (TIME_PERIOD, OBS_VALUE) | Daily ~16:00 CET (~14:00 UTC) business days |
| GBP per EUR | `https://data-api.ecb.europa.eu/service/data/EXR/D.GBP.EUR.SP00.A?format=csvdata` | CSV (TIME_PERIOD, OBS_VALUE) | Idem |

**Format ECB CSV** (extrait) :
```
KEY,TIME_PERIOD,OBS_VALUE,OBS_STATUS,...
D.USD.EUR.SP00.A,2026-05-15,1.0852,A,...
D.USD.EUR.SP00.A,2026-05-14,1.0834,A,...
...
```

- Une ligne d'en-tête + une ligne par date business-day
- `TIME_PERIOD` au format ISO `YYYY-MM-DD`
- `OBS_VALUE` = valeur du taux (USD ou GBP per EUR selon la série)
- Pas de publication weekend (samedi/dimanche absents)
- Holidays bancaires européens absents aussi

### 3.2 Formules dérivées

```python
# Côté scraper, après fetch des 2 séries (usd_per_eur, gbp_per_eur) :
fx_dxy_proxy = 1.0 / usd_per_eur            # rises when USD strengthens
fx_gbpusd    = usd_per_eur / gbp_per_eur    # USD per 1 GBP
fx_eurusd    = 1.0 / usd_per_eur            # alias DXY proxy (audit)
fx_gbpeur    = gbp_per_eur                  # raw (audit)
```

Stockage : une row par date business-day dans `pl_external_indicator`, colonnes FX, colonnes ENSO restent NULL.

### 3.3 Cadence cron

- **Publication ECB** : ~16:00 CET = 14:00-15:00 UTC business days
- **Cron prod** : `30 18 * * 1-5` (18:30 UTC, marge de 3-4h après publication, avant `cc-ensemble-compute` à 19:18)
- Si ECB en retard → fail-loud, manual relaunch
- Idempotent : UPSERT sur `(date)`

### 3.4 Weekend & holidays

- ECB ne publie pas → pas de scrape
- Le scraper saute le cron grâce à `1-5` (lundi-vendredi). Si tu veux une logique plus fine (skip bank holidays UK/EU/US) → utilise `should_skip_non_trading_day(force=False)` au démarrage du main.
- L'engine ensemble fait `merge_asof(direction="backward")` pour ENSO/FX, donc une date sans valeur récupère la dernière connue. **Pas de carry-forward côté scraper**.

---

## 4. Migration DB — `pl_external_indicator` (mutualisée avec ENSO)

### 4.1 Cas 1 : ENSO ship en premier

La migration de [P1-scraper-enso.md §4.1](P1-scraper-enso.md#41-schéma) crée la table avec **toutes les colonnes** (ENSO + FX). Cette US **n'apporte aucune nouvelle migration**, juste le code scraper qui écrit les colonnes FX via UPSERT partiel :

```sql
INSERT INTO pl_external_indicator (id, date, fx_dxy_proxy, fx_gbpusd, fx_eurusd, fx_gbpeur)
VALUES (gen_random_uuid(), :date, :dxy, :gbpusd, :eurusd, :gbpeur)
ON CONFLICT (date) DO UPDATE SET
  fx_dxy_proxy = EXCLUDED.fx_dxy_proxy,
  fx_gbpusd = EXCLUDED.fx_gbpusd,
  fx_eurusd = EXCLUDED.fx_eurusd,
  fx_gbpeur = EXCLUDED.fx_gbpeur;
-- enso_oni_month et enso_nino34_anomaly NE SONT PAS TOUCHÉS si déjà présents.
```

### 4.2 Cas 2 : FX ship en premier (ou en même temps)

La migration de cette US crée la table avec **toutes les colonnes** (identique à §4.1 de l'US ENSO). Les colonnes ENSO restent NULL jusqu'à ce que le scraper ENSO soit déployé.

**Recommandation** : ship les 2 USs ensemble dans le même sprint pour éviter le state où une table avec colonnes orphelines existe en prod.

### 4.3 Modèle SQLAlchemy

Voir [P1-scraper-enso.md §4.2](P1-scraper-enso.md#42-modèle-sqlalchemy). Modèle `PlExternalIndicator` contient les 4 colonnes FX (`fx_dxy_proxy`, `fx_gbpusd`, `fx_eurusd`, `fx_gbpeur`) en plus des 2 colonnes ENSO.

---

## 5. Architecture

### 5.1 Arborescence

```
backend/scripts/
└── fx_scraper/
    ├── __init__.py
    ├── config.py             # ECB_BASE URL, series keys
    ├── ecb_client.py         # fetch_ecb() porté depuis ingest_fx.py
    ├── scraper.py            # orchestrate fetch + compute derived rates
    ├── db_writer.py          # UPSERT pl_external_indicator (colonnes FX uniquement)
    ├── main.py               # @sentry monitor, CLI argparse
    └── README.md
```

### 5.2 Code à porter

[docs/onboarding/ingest_fx.py](../onboarding/ingest_fx.py) est déjà la quasi-totalité du code. Adaptations :
- Remplacer `to_csv()` par `db_writer.upsert_fx(session, df)`
- Wrapper avec `@monitor(monitor_slug="cc-fx-scraper")` Sentry
- CLI : `--dry-run`, `--force`, `--start-date YYYY-MM-DD` (rescrape historique)
- Fail-loud sur HTTP error ECB
- Log structuré INFO/ERROR

### 5.3 Patterns à réutiliser

| Pattern | Source | Notes |
|---|---|---|
| `@monitor(monitor_slug="…")` Sentry | `backend/scripts/cftc_scraper/main.py` | Cron monitoring |
| `should_skip_non_trading_day(force=…)` | `backend/scripts/db.py` | Skip auto weekend + jours fériés UK |
| `init_sentry("scraper-name")` | `app/core/sentry.py` | Init avant `@monitor` |
| UPSERT pattern | `backend/scripts/cftc_scraper/db_writer.py` | `INSERT ... ON CONFLICT (date) DO UPDATE SET fx_* = EXCLUDED.fx_*` |
| `argparse` `--dry-run`, `--force` | tous les scrapers | Convention CLI |
| Pure httpx (no Playwright) | `backend/scripts/cftc_scraper/`, `ice_stocks_scraper/` | ECB SDMX = pure HTTP/CSV, pas besoin de browser |

### 5.4 Entry point pyproject

```toml
# backend/pyproject.toml — section [tool.poetry.scripts]
fx-scraper = "scripts.fx_scraper.main:main"
fx-scraper-backfill = "scripts.fx_scraper.backfill:main"
```

---

## 6. Schedule + déploiement

### 6.1 Cron Cloud Scheduler

| Job | Cron (UTC) | Pourquoi cette heure |
|---|---|---|
| `cc-fx-scraper` (**NOUVEAU**) | `30 18 * * 1-5` | Daily business-days 18:30 UTC. ECB publie ~14:00 UTC (marge 4h30). AVANT `cc-ensemble-compute` à 19:18 UTC. |

`europe-west1` (Scheduler ne supporte pas `europe-west9`). `retryCount=0`.

### 6.2 Cloud Run Job

- **Dockerfile** : `backend/Dockerfile` (sans Playwright, ~200MB) — pure httpx + pandas
- Region `europe-west9`
- 512Mi RAM, 1 CPU
- `--max-retries=0` (fail-loud)
- VPC connector existant (`cc-vpc-connector`)
- Secret Manager pour DB URL

### 6.3 Backfill au launch (script one-shot)

**Action manuelle J-1 launch C5**.

```bash
# Local, contre prod via bastion tunnel
poetry run fx-scraper-backfill \
  --source-csv-dxy docs/onboarding/FX/dxy_proxy_daily.csv \
  --source-csv-gbp docs/onboarding/FX/gbpusd_daily.csv \
  --start 2014-01-02 \
  --end 2026-05-15 \
  [--dry-run] [--verify]

# Avec --verify : compare value-by-value contre le CSV R&D source, refuse les mismatches > 1e-6.
```

**Implementation** : `backend/scripts/fx_scraper/backfill.py` (one-shot). Lit les 2 CSV, UPSERT row-par-row dans `pl_external_indicator` avec colonnes FX uniquement.

**Alternative** : pour les utilisateurs qui veulent re-scrape from source (plutôt que CSV), `poetry run fx-scraper --start-date 2014-01-02` itère depuis ECB directement (plus lent, ~5 min, mais ground-truth).

### 6.4 CI/CD

`.github/workflows/deploy.yml` — ajouter ligne :
```bash
deploy_job cc-fx-scraper  512Mi  "fx-scraper"
```

### 6.5 Terraform

`infra/terraform/scheduler.tf` — ajouter entry :
```hcl
fx-scraper = {
  description = "Fetch ECB SDMX FX rates: USD/EUR + GBP/EUR daily business-days"
  schedule    = "30 18 * * 1-5"
}
```

---

## 7. Critères d'acceptance

### MVP shipped quand :

1. **Migration appliquée** : table `pl_external_indicator` présente en prod GCP (avec colonnes FX + ENSO).
2. **Scraper fonctionnel en prod** : 1 Cloud Run Job déployé, 1 Cloud Scheduler job configuré, exécution quotidienne business-days.
3. **Backfill complet** : `SELECT count(*), min(date), max(date) FROM pl_external_indicator WHERE fx_dxy_proxy IS NOT NULL` retourne **≥ 3000 rows** avec date_range `>= 2014-01-02` et `<= last business day before launch`.
4. **Validation value-by-value backfill** : pour chaque date entre 2014-01-02 et J-1, la valeur DB matche la valeur du CSV R&D ([docs/onboarding/FX/dxy_proxy_daily.csv](../onboarding/FX/dxy_proxy_daily.csv) + `gbpusd_daily.csv`) à ±1e-6.
5. **Window de validation 5 jours ouvrés** :
   - 5 exécutions automatiques successives en succès
   - 5 rows écrites avec `fx_dxy_proxy IS NOT NULL` et `fx_gbpusd IS NOT NULL` pour les 5 derniers business days
   - Aucune alerte Sentry sur la fenêtre
6. **Tests unit ≥ 80% coverage** sur `scripts/fx_scraper/` (parser ECB CSV avec edge cases, formules DXY/GBPUSD, db_writer UPSERT, fail-loud).
7. **Tests d'intégration** : 1 test qui mocke ECB SDMX, vérifie le parsing CSV, les formules, et l'upsert DB.
8. **Sentry monitor configuré** pour `cc-fx-scraper`.
9. **Doc mise à jour** : section "Scrapers" de `CLAUDE.md`, README.md dans le module.
10. **Aucune contamination des colonnes ENSO** par le backfill FX (ENSO restent NULL aux dates où ENSO scraper n'a pas écrit).

### Rejet si :

- `try/except` qui swallow une erreur silencieusement (cf. `pipeline-error-handling.md`).
- Auto-retry / fallback à un autre provider (yfinance, FRED, etc.) si ECB down (interdit).
- Calcul de z-score / normalisation côté scraper (doit rester côté engine).
- Migration touche une colonne existante de `pl_contract_data_daily` (FX vit dans `pl_external_indicator`, agnostique commodity).
- Codes contrats hardcodés (n/a ici, mais règle générique).
- Pas de validation value-by-value vs CSV R&D au backfill.

---

## 8. Plan de vérification

### 8.1 Tests unitaires

```bash
poetry run pytest backend/tests/fx_scraper/ -v --cov=scripts.fx_scraper --cov-report=term-missing
```

Cas testés :
- Parsing nominal ECB CSV (2 rows, 1 row, 0 rows)
- Edge case : NaT dans `TIME_PERIOD` (dropped silently — confirmé par le code R&D ligne 38)
- Edge case : NaN dans `OBS_VALUE` (dropped silently)
- Formules : `fx_dxy_proxy = 1 / 1.0852 ≈ 0.9215` ; `fx_gbpusd = 1.0852 / 0.7878 ≈ 1.3774`
- Merge des 2 séries USD/EUR + GBP/EUR sur date inner-join (les dates où les 2 publient)
- DB UPSERT idempotent (re-run sur même date → 0 changement)
- Backfill : value-by-value match contre CSV R&D
- Fail-loud : HTTP 500 ECB → exit non-zero + Sentry error

### 8.2 Tests d'intégration local

```bash
# Pre-req: DB locale + migration appliquée (de l'US ENSO ou de celle-ci)
pnpm db:up
poetry run alembic upgrade head

# Test 1: dry-run
poetry run fx-scraper --dry-run --verbose

# Test 2: real scrape (1 row business-day écrite, le dernier jour publié)
poetry run fx-scraper

psql -h localhost -p 5433 -U postgres -d commodities_compass -c "
  SELECT date, fx_dxy_proxy, fx_gbpusd, fx_eurusd, fx_gbpeur
  FROM pl_external_indicator
  WHERE fx_dxy_proxy IS NOT NULL
  ORDER BY date DESC LIMIT 5;
"

# Test 3: backfill one-shot
poetry run fx-scraper-backfill \
  --source-csv-dxy docs/onboarding/FX/dxy_proxy_daily.csv \
  --source-csv-gbp docs/onboarding/FX/gbpusd_daily.csv \
  --start 2014-01-02 --end 2026-04-30 \
  --verify

# Vérif count
psql -c "SELECT count(*) FROM pl_external_indicator WHERE fx_dxy_proxy IS NOT NULL;"
# attendu : ≥ 3000 rows
```

### 8.3 Window de validation 5 jours (prod)

Sur 5 business-days post-activation :

```bash
./.local/db-prod.sh exec "
  WITH last_5_bd AS (
    SELECT date,
           fx_dxy_proxy IS NOT NULL AS has_dxy,
           fx_gbpusd IS NOT NULL AS has_gbpusd
    FROM pl_external_indicator
    WHERE date >= CURRENT_DATE - INTERVAL '14 days'
      AND EXTRACT(DOW FROM date) NOT IN (0, 6)  -- skip weekends
      AND fx_dxy_proxy IS NOT NULL
    ORDER BY date DESC LIMIT 5
  )
  SELECT * FROM last_5_bd;
"
```

Critère : 5/5 lignes avec `has_dxy = TRUE AND has_gbpusd = TRUE`.

Monitoring Sentry sur 5 jours :
```bash
gcloud logging read 'resource.type=cloud_run_job AND resource.labels.job_name="cc-fx-scraper" AND severity>=WARNING' \
  --limit 50 --project=cacaooo --freshness=7d
```

Aucune ligne attendue.

### 8.4 Validation cross-source

Compare les 5 dernières valeurs DB vs ECB direct :

```bash
# Quick smoke check : la valeur USD/EUR du dernier business-day matche ECB ?
curl -s "https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A?format=csvdata&startPeriod=2026-05-12" | tail -5
# Compare avec :
psql -c "SELECT date, 1.0/fx_dxy_proxy AS usd_per_eur FROM pl_external_indicator WHERE date >= '2026-05-12' ORDER BY date DESC;"
```

Tolérance ±1e-4 (rounding decimal).

---

## 9. Risques & mitigation

| Risque | Probabilité | Impact | Mitigation |
|---|---|---|---|
| ECB SDMX down ou bloque IP | Faible | Élevé (bloque le cron daily) | User-Agent réaliste, log + Sentry alert. Plan B : VPN, ou fallback CSV one-shot manuel jusqu'au retour ECB. **Pas de provider fallback automatique** (règle interdite). |
| Format ECB SDMX change (rare) | Très faible | Moyen | Tests unit avec fixtures CSV. Détection : mismatch parser → fail-loud. |
| Publication ECB décalée (>4h après 16:00 CET) | Faible | Faible (cron à 18:30 UTC = 19:30 CET → 3h30 marge) | Acceptable. Si retard > 6h → relance manuelle le lendemain. |
| Backfill value mismatch CSV R&D vs DB | Faible | Élevé (corruption silencieuse) | Option `--verify` au backfill : fail-loud si mismatch > 1e-6. Pas de UPSERT sans check. |
| ECB modifie une valeur historique (correction) | Très faible | Faible (rare, audit visible) | Le scraper en mode `--start-date YYYY-MM-DD` permet le rescrape de range, qui UPSERT. Documenter dans README. |
| Weekend skip casse la cadence | n/a | n/a | Cron `* * 1-5` skip natif weekend. Les bank holidays UK/EU/US peuvent fail-loud → manual rescrape. À tolérer (3-5 jours/an). |
| Cocoa London cote en GBP, on track surtout DXY proxy (USD strength) — adéquation features | n/a | Moyen | R&D a validé que les 2 features (`fx_dxy_proxy` + `fx_gbpusd`) sont les signaux pertinents pour LCE. Pas de scope creep dans cette US. |
| Conflict avec la migration ENSO (table déjà créée) | Faible | Faible (idempotent) | `_has_table()` check, `IF NOT EXISTS` partout. Migration ENSO/FX coordonnée ou shipped same sprint. |

---

## 10. Open questions / décisions à prendre

1. **Granularité** : `date` daily business-day, pas intra-day. R&D confirme. Validé.
2. **Faut-il stocker AUSSI les 2 séries brutes** (`usd_per_eur`, `gbp_per_eur`) en plus des 4 colonnes dérivées ? → Recommandation : NON (les dérivées sont déjà des fonctions pures des brutes, on peut recompute si besoin). Économie de 2 colonnes inutiles.
3. **Inclure d'autres paires majeures** (AUD/USD, JPY/USD, CHF/USD) pour les futurs algos ? → NON pour MVP. Le panel R&D n'en consomme pas. Ajoutable plus tard sans rupture (nouvelle colonne nullable).
4. **Cadence intraday** (toutes les heures pour real-time) ? → NON. R&D backtest sur daily close. Pas de besoin intraday pour C5.
5. **DXY officiel ICE vs proxy ECB-derived** ? → Le DXY officiel ICE est un panier 6 devises payant. Le proxy ECB `1/USD_per_EUR` est ~85% corrélé. R&D a validé le proxy. ICE-DXY hors scope.
6. **Bank holiday handling** : ECB skip natif → pas de row écrite ces jours-là. L'engine compute fait `merge_asof(direction="backward")` côté usage. Pas d'action côté scraper.

---

## 11. Séquence d'exécution (workplan)

Phasing pour livrer en 1 sprint (~1 semaine), idéalement parallèle à l'US ENSO :

| Jour | Tâche |
|---|---|
| J1 | Si ENSO non shipé : migration Alembic `add_pl_external_indicator` (cf. [P1-scraper-enso.md §4.1](P1-scraper-enso.md#41-schéma)). Sinon : skip. |
| J1 | Squelette `backend/scripts/fx_scraper/` (port direct de [ingest_fx.py](../onboarding/ingest_fx.py)) |
| J2 | Tests unit parser ECB CSV (fixtures fake response, edge cases) + formules dérivées |
| J2 | `db_writer.py` UPSERT + tests |
| J3 | CLI `main.py` + integration test local |
| J3 | Backfill script one-shot + tests value-by-value |
| J4 | Cloud Run Job + Scheduler + Terraform |
| J4 | deploy.yml + CI green |
| J5 | Deploy preview + smoke test |
| J5 | Update `CLAUDE.md` |
| J6 | Activation cron prod + run backfill 12y (~5 minutes) |
| J6 | Validation value-by-value backfill ([§8.2](#82-tests-dintégration-local)) |
| J7+ | Window de validation 5 business-days |

---

## Annexe A — Fichiers à créer / modifier

### Créer (nouveaux)
- `backend/scripts/fx_scraper/{__init__,config,ecb_client,scraper,db_writer,main,backfill}.py` + `README.md`
- `backend/alembic/versions/<rev>_add_pl_external_indicator.py` **si pas créée par l'US ENSO en premier**
- `backend/tests/fx_scraper/{test_ecb_client,test_db_writer,test_main,test_backfill}.py`

### Modifier (additif)
- `backend/app/models/pipeline.py` → ajouter `PlExternalIndicator` (si pas déjà ajouté par l'US ENSO)
- `backend/pyproject.toml` → entry points `fx-scraper` + `fx-scraper-backfill`
- `.github/workflows/deploy.yml` → ligne `deploy_job cc-fx-scraper 512Mi "fx-scraper"`
- `infra/terraform/scheduler.tf` → entry `fx-scraper`
- `CLAUDE.md` → section "Scrapers" mise à jour
- `docs/onboarding/HEDI_DATA_MAP.md` → §4.2 FX marqué RESOLVED

### Ne pas toucher (interdiction explicite)
- `backend/app/engine/` → la consommation FX se fait en compute-time, hors scope scraper
- Tous les autres scrapers prod (`press_review_agent/`, `barchart_scraper/`, etc.) → isolation
- `pl_contract_data_daily` → FX vit dans `pl_external_indicator`, agnostique commodity

---

## Annexe B — Liens

- Plan déploiement complet : [CAMPAIGN_5_PROD_DEPLOYMENT.md](../onboarding/CAMPAIGN_5_PROD_DEPLOYMENT.md) §5.2
- Data map détaillée : [HEDI_DATA_MAP.md](../onboarding/HEDI_DATA_MAP.md) §1.2 + §4.2
- Code R&D source : [docs/onboarding/ingest_fx.py](../onboarding/ingest_fx.py)
- Merge policy R&D : [docs/onboarding/external_data.py](../onboarding/external_data.py)
- CSV backfill : [docs/onboarding/FX/dxy_proxy_daily.csv](../onboarding/FX/dxy_proxy_daily.csv) + `gbpusd_daily.csv`
- US sœur ENSO : [P1-scraper-enso.md](P1-scraper-enso.md) (migration mutualisée)
- Pipeline error handling : [.claude/rules/pipeline-error-handling.md](../../.claude/rules/pipeline-error-handling.md)
- North-star : [.claude/rules/north-star-alignment.md](../../.claude/rules/north-star-alignment.md) (rule #4 + #6)
- Pattern scraper existant : `backend/scripts/cftc_scraper/` (pure httpx, idempotent UPSERT, daily)
- ECB SDMX documentation : https://data.ecb.europa.eu/help/api/data
- ECB EXR dataflow : https://data.ecb.europa.eu/help/api/dataflows/EXR
