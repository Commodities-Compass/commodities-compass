# Scraper ENSO — Climatologie NOAA pour les spécialistes macro (6/14)

**Statut :** Proposed (non implémenté)
**Date :** 2026-05-19
**Owner :** TBD (Hedi)
**Slug :** `scraper-enso`
**Cible repo :** `docs/user-stories/P1-scraper-enso.md`
**Deadline :** P1 — 1.5 sprint (~1.5 semaine)
**Dépendance launch C5 :** bloquante (6/14 spécialistes en dépendent — cluster Winter macro + macro_combined Spring)

---

## 1. Contexte

Le déploiement Campaign 5 ensemble ([CAMPAIGN_5_PROD_DEPLOYMENT.md](../onboarding/CAMPAIGN_5_PROD_DEPLOYMENT.md)) requiert deux features climatologiques ENSO consommées par 6 des 14 spécialistes (panel `fx_enso_focus` + variantes `+garch_fx_enso`) — notamment **`exp_optim_011`, le top scorer Campaign 4-5** ([HEDI_DATA_MAP.md §1.3](../onboarding/HEDI_DATA_MAP.md)) :

- `enso_oni` — Oceanic Niño Index, moyenne 3 mois SST anomaly (°C)
- `enso_nino34_anomaly` — Niño 3.4 SST anomaly mensuelle (°C)

Aucun feed ENSO n'existe en prod aujourd'hui ([Q1 R&D doc](../onboarding/CAMPAIGN_5_PROD_DEPLOYMENT.md#L137), confirmé par l'inventaire `pl_contract_data_daily` + `pl_derived_indicators`). Le code R&D du scraper est déjà disponible et propre : [docs/onboarding/ingest_enso.py](../onboarding/ingest_enso.py) (~100 LOC, parsing NOAA PSL ASCII).

**Pourquoi maintenant** : sans ENSO en prod, 6/14 spécialistes ne peuvent pas inférer correctement (features manquantes → imputer → perte d'information macro). Bloque le launch C5.

**Backfill historique** : ~75 ans de données mensuelles disponibles via NOAA PSL (1948-2026), CSV pré-calculés disponibles dans [docs/onboarding/ENSO/](../onboarding/ENSO/) (`oni_monthly.csv`, `nino34_monthly.csv`, ~900 rows chacun). Le backfill se fait **au launch** via un script one-shot, puis le scraper tourne en forward-only.

---

## 2. Goals & non-goals

### Goals (cette itération)

- Créer le scraper `cc-enso-scraper` (Cloud Run Job mensuel) qui écrit dans `pl_external_indicator` (NEW table agnostique, partagée avec [P1-scraper-fx.md](P1-scraper-fx.md))
- Backfill 10 ans (2016-01 → today, ~120 rows) au launch via script one-shot
- Migration Alembic idempotente créant `pl_external_indicator`
- Crons Cloud Scheduler + terraform + deploy.yml
- Tests unit + intégration TDD (80%+ coverage)
- Sentry monitor + fail-loud
- **Window de validation 2 cycles mensuels** avant déclaration "stable"
- Doc mise à jour dans `CLAUDE.md` (section Scrapers)

### Non-goals

- **Pas** de scrape FX dans cette US (traité dans [P1-scraper-fx.md](P1-scraper-fx.md), mais migration mutualisée — voir §4)
- **Pas** de calcul de z-score / normalisation côté scraper — les features dérivées (`enso_oni_zscore_60d`, etc.) sont calculées par l'engine ensemble en compute-time (matches le pattern rolling normalization, [.claude/rules/north-star-alignment.md](../../.claude/rules/north-star-alignment.md) rule #6)
- **Pas** d'auto-retry sur le job (règle prod `pipeline-error-handling.md`)
- **Pas** de nouvelle UI dashboard
- **Pas** de scraper d'autres indices climatiques (SOI, IOD, MJO) — hors scope C5

---

## 3. Source & cadence

### 3.1 NOAA PSL — Free, no auth

| Série | URL | Format | Cadence publication |
|---|---|---|---|
| ONI (3-month mean SST anomaly) | `https://psl.noaa.gov/data/correlation/oni.data` | ASCII plain-text | Mensuel, mid-month (M+15 pour mois M-1) |
| Niño 3.4 anomaly | `https://psl.noaa.gov/data/correlation/nina34.anom.data` | ASCII plain-text | Idem |

**Format PSL** (extrait `oni.data`) :
```
   1950 2026
1950  -1.5  -1.3  -1.2  -1.2  -1.1  -0.7  -0.4  -0.4  -0.3  -0.4  -0.6  -0.8
1951  -0.7  -0.5  -0.2   0.2   0.4   0.5   0.6   0.8   0.9   1.0   0.9   0.7
...
2026   1.2   1.0   0.7   0.4   0.1  -99.99 -99.99 -99.99 -99.99 -99.99 -99.99 -99.99
  -99.99
[metadata trailing lines ignored]
```

- Première ligne = range d'années couvert
- Une ligne par année : `year jan feb mar ... dec` (13 tokens)
- `-99.99` = missing value flag (mois futurs ou pré-1948 padding)
- Le scraper doit parser jusqu'à la première ligne non-numérique puis stopper.

### 3.2 Cadence cron

- **Publication NOAA** : ~mi-mois pour M-1 (e.g., janvier 2026 publié ~15 février 2026)
- **Cron prod** : `0 22 20 * 1-5` (20 du mois 22:00 UTC, marge de 5 jours après publication)
- Si publication retardée → fail-loud, manual relaunch via `gcloud run jobs execute cc-enso-scraper`
- Idempotent : UPSERT sur `(date)` (le mois — stocké comme 1er du mois)

### 3.3 Lag policy (côté engine, pas scraper)

`enso_publication_lag_days = 14` jours ([external_data.py:54](../onboarding/external_data.py)). Le scraper stocke la valeur **à la date du mois** (1er du mois). L'engine ensemble applique le shift `+14j` en compute-time via `pd.merge_asof(direction="backward")` (matches le pattern R&D existant).

---

## 4. Migration DB — `pl_external_indicator` (NEW table mutualisée ENSO + FX)

### 4.1 Schéma

Table agnostique commodity (pas de `contract_id`), keyed sur `date`. Mutualisée avec [P1-scraper-fx.md](P1-scraper-fx.md) — **une seule migration crée toutes les colonnes**.

```python
# backend/alembic/versions/<rev>_add_pl_external_indicator.py
"""add pl_external_indicator table for ENSO + FX features

Revision ID: <rev>
Revises: <down_rev>
Create Date: 2026-05-XX
"""
from alembic import op
import sqlalchemy as sa


def _has_table(name: str) -> bool:
    conn = op.get_bind()
    return conn.execute(sa.text(
        "SELECT 1 FROM information_schema.tables WHERE table_name = :n"
    ), {"n": name}).fetchone() is not None


def upgrade() -> None:
    if not _has_table("pl_external_indicator"):
        op.create_table(
            "pl_external_indicator",
            sa.Column("id", sa.Uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("date", sa.Date, nullable=False),
            # ENSO (monthly, carry-forward daily applied at engine compute-time)
            sa.Column("enso_oni_month", sa.DECIMAL(8, 4), nullable=True),
            sa.Column("enso_nino34_anomaly", sa.DECIMAL(8, 4), nullable=True),
            # FX (daily — populated by cc-fx-scraper, see P1-scraper-fx.md)
            sa.Column("fx_dxy_proxy", sa.DECIMAL(15, 6), nullable=True),
            sa.Column("fx_gbpusd", sa.DECIMAL(15, 6), nullable=True),
            sa.Column("fx_eurusd", sa.DECIMAL(15, 6), nullable=True),
            sa.Column("fx_gbpeur", sa.DECIMAL(15, 6), nullable=True),
            sa.Column("created_at", sa.TIMESTAMP, nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("date", name="uq_external_indicator_date"),
        )
        op.create_index("ix_external_indicator_date", "pl_external_indicator", ["date"])


def downgrade() -> None:
    op.drop_index("ix_external_indicator_date", table_name="pl_external_indicator")
    op.drop_table("pl_external_indicator")
```

**Notes** :
- Table mutualisée : la migration crée `pl_external_indicator` une fois, ENSO et FX écrivent leurs colonnes respectives via UPSERT partiel.
- `date` est la 1er du mois pour ENSO (granularité mensuelle native) et la date trading day pour FX. Pas de conflit : ENSO écrit ~12 rows/an aux dates `YYYY-MM-01`, FX écrit ~260 rows/an aux dates business-days.
- Idempotent via `_has_table()` (cf. patterns existants).
- Pas d'index sur ENSO/FX colonnes (jamais filtrés standalone, toujours lus par date).

### 4.2 Modèle SQLAlchemy

À ajouter dans `backend/app/models/pipeline.py` :

```python
class PlExternalIndicator(Base):
    """ENSO + FX daily values, commodity-agnostic.

    ENSO is monthly (date = 1st of month). FX is daily business days.
    Both stored in the same table; ENSO + FX scrapers write their own columns
    via UPSERT. Engine ensemble joins on date via merge_asof.
    """
    __tablename__ = "pl_external_indicator"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    date: Mapped[date] = mapped_column(DATE, nullable=False)

    # ENSO (monthly publication, carry-forward applied at compute-time)
    enso_oni_month: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(8, 4))
    enso_nino34_anomaly: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(8, 4))

    # FX (daily business days — see P1-scraper-fx.md)
    fx_dxy_proxy: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    fx_gbpusd: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    fx_eurusd: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    fx_gbpeur: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))

    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("date", name="uq_external_indicator_date"),
        Index("ix_external_indicator_date", "date"),
    )
```

### 4.3 Coordination ENSO ↔ FX

Si les 2 USs ship en même temps : **1 PR de migration**, les 2 scrapers writent leurs colonnes respectives. Si l'une ship avant l'autre : la migration crée toutes les colonnes (les colonnes FX seront NULL jusqu'à ce que FX scraper soit déployé). Pas d'ordre obligatoire.

---

## 5. Architecture

### 5.1 Arborescence

Pattern aligné sur les scrapers existants :

```
backend/scripts/
└── enso_scraper/
    ├── __init__.py
    ├── config.py             # URLs NOAA, OUT_FORMAT_VERSION
    ├── parser.py             # _parse_psl_text() porté depuis ingest_enso.py
    ├── scraper.py            # fetch + parse + return list[dict]
    ├── db_writer.py          # UPSERT pl_external_indicator (colonnes ENSO uniquement)
    ├── main.py               # @sentry monitor, CLI argparse
    └── README.md
```

### 5.2 Code à porter

[docs/onboarding/ingest_enso.py](../onboarding/ingest_enso.py) est déjà la quasi-totalité du code. Adaptations nécessaires :
- Remplacer `OUT_DIR.csv.to_csv()` par `db_writer.upsert_enso(session, df)`
- Wrapper avec `@monitor(monitor_slug="cc-enso-scraper")` Sentry
- CLI : `--dry-run`, `--force`, `--start-month YYYY-MM` (rescrape spécifique pour fix)
- Fail-loud sur HTTP error (pas de retry, exit non-zero)
- Log structuré INFO/ERROR

### 5.3 Patterns à réutiliser

| Pattern | Source | Notes |
|---|---|---|
| `@monitor(monitor_slug="…")` Sentry | `backend/scripts/cftc_scraper/main.py` | Cron monitoring |
| `should_skip_non_trading_day(force=…)` | `backend/scripts/db.py` | **Pas applicable ici** — ENSO est mensuel, indépendant des jours trading |
| `init_sentry("scraper-name")` | `app/core/sentry.py` | Init avant `@monitor` |
| UPSERT pattern | `backend/scripts/cftc_scraper/db_writer.py` | `INSERT ... ON CONFLICT (date) DO UPDATE SET enso_oni_month = EXCLUDED.enso_oni_month, ...` |
| `argparse` `--dry-run`, `--force` | tous les scrapers | Convention CLI |

### 5.4 Entry point pyproject

```toml
# backend/pyproject.toml — section [tool.poetry.scripts]
enso-scraper = "scripts.enso_scraper.main:main"
```

---

## 6. Schedule + déploiement

### 6.1 Cron Cloud Scheduler

| Job | Cron (UTC) | Pourquoi cette heure |
|---|---|---|
| `cc-enso-scraper` (**NOUVEAU**) | `0 22 20 * 1-5` | 20 du mois 22:00 UTC : NOAA publie ~mi-mois, marge de 5 jours. Hors heure prod 19:00-19:30. |

`europe-west1` (Scheduler ne supporte pas `europe-west9`). `retryCount=0`.

### 6.2 Cloud Run Job

- **Dockerfile** : `backend/Dockerfile` (sans Playwright, ~200MB) — pure httpx + pandas
- Region `europe-west9`
- 512Mi RAM, 1 CPU
- `--max-retries=0` (fail-loud)
- VPC connector existant (`cc-vpc-connector`)
- Secret Manager pour DB URL
- Workload Identity Federation

### 6.3 Backfill au launch (script one-shot)

**Action manuelle J-1 launch C5**, pas un Cloud Run Job permanent.

```bash
# Local, contre prod via bastion tunnel
poetry run enso-scraper-backfill \
  --source-csv docs/onboarding/ENSO/oni_monthly.csv \
  --source-csv-nin docs/onboarding/ENSO/nino34_monthly.csv \
  --start 2016-01-01 \
  --end 2026-05-01 \
  [--dry-run] [--verify]

# Avec --verify : compare value-by-value contre le CSV R&D source, refuse les mismatches
```

**Implementation** : `backend/scripts/enso_scraper/backfill.py` (one-shot, supprimable post-launch ou laissé pour rescrape ponctuel). Lit le CSV, UPSERT row-par-row dans `pl_external_indicator` avec les colonnes ENSO uniquement (FX colonnes restent NULL).

### 6.4 CI/CD

`.github/workflows/deploy.yml` — ajouter ligne :
```bash
deploy_job cc-enso-scraper  512Mi  "enso-scraper"
```

### 6.5 Terraform

`infra/terraform/scheduler.tf` — ajouter entry :
```hcl
enso-scraper = {
  description = "Fetch NOAA ENSO ONI + Niño 3.4 monthly anomaly"
  schedule    = "0 22 20 * 1-5"
}
```

Cloud Run Job déclaration : pas de fichier dédié dans `infra/terraform/` aujourd'hui (le deploy.yml gère). Confirmer convention avec Hedi en début de sprint.

---

## 7. Critères d'acceptance

### MVP shipped quand :

1. **Migration appliquée** : table `pl_external_indicator` (avec toutes les colonnes ENSO + FX) présente en prod GCP. Migration Alembic réversible.
2. **Scraper fonctionnel en prod** : 1 Cloud Run Job déployé, 1 Cloud Scheduler job configuré, exécution mensuelle.
3. **Backfill complet** : `SELECT count(*), min(date), max(date) FROM pl_external_indicator WHERE enso_oni_month IS NOT NULL` retourne **≥ 120 rows** (10 ans × 12 mois) avec date_range `>= 2016-01-01` et `<= last_complete_month`.
4. **Validation value-by-value backfill** : pour chaque mois entre 2016-01 et 2026-04, la valeur DB matche la valeur du CSV R&D ([docs/onboarding/ENSO/oni_monthly.csv](../onboarding/ENSO/oni_monthly.csv)) à ±1e-3.
5. **Window de validation 2 cycles mensuels** :
   - 2 exécutions automatiques successives en succès (e.g., publication mai 2026 et juin 2026)
   - 2 rows écrites avec ENSO non-NULL pour ces 2 mois
   - Aucune alerte Sentry sur la fenêtre
6. **Tests unit ≥ 80% coverage** sur `scripts/enso_scraper/` (parser PSL avec edge cases, db_writer UPSERT, fail-loud).
7. **Tests d'intégration** : 1 test qui mocke NOAA, vérifie le parsing et l'upsert DB.
8. **Sentry monitor configuré** pour `cc-enso-scraper`.
9. **Doc mise à jour** : section "Scrapers" de `CLAUDE.md`, README.md dans le module.
10. **Aucune contamination des colonnes FX** par le backfill ENSO (FX restent NULL pour les rows où le scraper FX n'a pas encore écrit).

### Rejet si :

- `try/except` qui swallow une erreur silencieusement (cf. `pipeline-error-handling.md`).
- Auto-retry / fallback à autre source si NOAA down (interdit).
- Calcul de z-score / normalisation côté scraper (doit rester côté engine).
- Migration touche une colonne existante de `pl_contract_data_daily` (table dédiée only).
- Codes contrats hardcodés (n/a ici — ENSO est commodity-agnostic, mais règle générique respectée).
- Pas de validation value-by-value vs CSV R&D au backfill.

---

## 8. Plan de vérification

### 8.1 Tests unitaires

```bash
poetry run pytest backend/tests/enso_scraper/ -v --cov=scripts.enso_scraper --cov-report=term-missing
```

Cas testés :
- Parsing nominal (rangée 2020 complète)
- Edge case `-99.99` flag (missing value detection)
- Edge case header ranges (1950-2026)
- Trailing metadata lines ignorées
- Mois en cours avec valeur manquante → NaN, pas d'erreur
- DB UPSERT idempotent (re-run produit 0 changement)
- Backfill : value-by-value match contre CSV R&D

### 8.2 Tests d'intégration local

```bash
# Pre-req: DB locale + migration appliquée
pnpm db:up
poetry run alembic upgrade head

# Test 1: dry-run
poetry run enso-scraper --dry-run --verbose

# Test 2: real scrape (1 row écrite, le dernier mois publié)
poetry run enso-scraper

psql -h localhost -p 5433 -U postgres -d commodities_compass -c "
  SELECT date, enso_oni_month, enso_nino34_anomaly
  FROM pl_external_indicator
  WHERE enso_oni_month IS NOT NULL
  ORDER BY date DESC LIMIT 5;
"

# Test 3: backfill one-shot
poetry run enso-scraper-backfill \
  --source-csv docs/onboarding/ENSO/oni_monthly.csv \
  --source-csv-nin docs/onboarding/ENSO/nino34_monthly.csv \
  --start 2016-01-01 --end 2026-04-01 \
  --verify

# Vérif count
psql -c "SELECT count(*) FROM pl_external_indicator WHERE enso_oni_month IS NOT NULL;"
# attendu : ≥ 120 rows
```

### 8.3 Window de validation 2 cycles (prod)

Sur 2 mois post-activation :

```bash
./.local/db-prod.sh exec "
  SELECT date,
         enso_oni_month IS NOT NULL AS has_oni,
         enso_nino34_anomaly IS NOT NULL AS has_nin
  FROM pl_external_indicator
  WHERE date >= CURRENT_DATE - INTERVAL '90 days'
    AND enso_oni_month IS NOT NULL
  ORDER BY date DESC LIMIT 5;
"
```

Critère : 2/2 mois récents avec `has_oni = TRUE AND has_nin = TRUE`.

Monitoring Sentry sur 2 mois :
```bash
gcloud logging read 'resource.type=cloud_run_job AND resource.labels.job_name="cc-enso-scraper" AND severity>=WARNING' \
  --limit 50 --project=cacaooo --freshness=60d
```

Aucune ligne attendue.

### 8.4 Validation côté Julien

Vérifier que `pl_external_indicator.enso_oni_month` matche la dernière valeur `oni_monthly.csv` produite par `methodology/external_data.py` côté R&D. Tolérance : ±1e-3 (Decimal(8,4) vs CSV float).

---

## 9. Risques & mitigation

| Risque | Probabilité | Impact | Mitigation |
|---|---|---|---|
| NOAA PSL down ou bloque IP | Faible | Élevé (bloque le cron mensuel) | User-Agent réaliste, log + skip + Sentry alert. Plan B : rescrape manuel via VPN si IP-block ; fallback CSV manuel si NOAA down >7j. |
| Format PSL change | Très faible | Moyen | Tests unit avec fixtures de la doc PSL. Détection : mismatch parser → fail-loud → investigation. |
| Publication NOAA décalée (>5j) | Moyenne | Faible (rescrape manuel) | Cron J+20 a 5j de marge. Si NOAA publie J+25 → manual `gcloud run jobs execute cc-enso-scraper`. |
| Backfill value mismatch CSV R&D vs DB | Faible | Élevé (corruption silencieuse) | Option `--verify` au backfill : fail-loud si mismatch > tolerance. Pas de UPSERT sans check. |
| Migration mutualisée ENSO + FX conflict | Faible | Faible | Une seule migration crée la table avec toutes les colonnes. Si l'une des 2 USs ship en premier, l'autre n'a rien à faire côté DB. |
| Engine ne sait pas appliquer lag policy | Moyenne | Élevé (look-ahead bias) | Test E2E : pour le mois M-1, à la date J=M+10, le engine NE doit PAS encore voir la valeur (lag 14j non-écoulé). Couvert dans les tests engine, pas le scraper. |
| Backfill duplicate avec live scraper post-launch | Faible | Faible (UPSERT idempotent) | UPSERT sur `(date)` → re-run n'écrit que les nouvelles valeurs. |

---

## 10. Open questions / décisions à prendre

1. **Granularité de stockage ENSO** : 1er du mois (`YYYY-MM-01`) — confirmé par le code R&D. Validé.
2. **Faut-il stocker la `release_date` NOAA** (quand NOAA a publié) en plus de la `date` (mois couvert) ? → Recommandation : NON pour MVP, peut être ajouté si audit nécessaire. Le lag policy 14j est suffisant.
3. **Inclure Niño 1+2, Niño 3, Niño 4 indices** en plus de ONI + Niño 3.4 ? → NON, hors scope R&D Campaign 5 (seuls ONI + 3.4 sont consommés).
4. **Backfill 10y vs 75y disponible** : NOAA publie depuis 1948. R&D demande 10y. → Recommandation : **backfill 10y au launch** (suffisant pour rolling 60d-252d), avec option de remonter à 1948 si besoin futur (1 commande relance).
5. **Format de stockage pour `-99.99` (missing value)** : convertir en NULL en DB. Validé.

---

## 11. Séquence d'exécution (workplan)

Phasing pour livrer en 1.5 sprint (~1.5 semaine) :

### Sprint 1 (semaine 1) — Migration + scraper + tests

| Jour | Tâche |
|---|---|
| J1 | Migration Alembic `add_pl_external_indicator` (local + prod via bastion) |
| J1 | Squelette `backend/scripts/enso_scraper/` (port direct de [ingest_enso.py](../onboarding/ingest_enso.py)) |
| J2 | Tests unit parser PSL (fixtures fake response, edge cases) |
| J2 | `db_writer.py` UPSERT + tests |
| J3 | CLI `main.py` + integration test local |
| J4 | Backfill script one-shot + tests value-by-value |
| J5 | Code review + PR mergeable en isolation |

### Sprint 2 (mi-semaine 2) — Déploiement + backfill + validation

| Jour | Tâche |
|---|---|
| J6 | Cloud Run Job + Scheduler + Terraform |
| J6 | deploy.yml + CI green |
| J7 | Deploy preview + smoke test |
| J7 | Update `CLAUDE.md` |
| J8 | Activation cron prod + run backfill 10y (~30 minutes) |
| J8 | Validation value-by-value backfill ([§8.2](#82-tests-dintégration-local)) |
| J9+ | Window de validation 2 mois (passive monitoring jusqu'au prochain cycle NOAA) |

---

## Annexe A — Fichiers à créer / modifier

### Créer (nouveaux)
- `backend/scripts/enso_scraper/{__init__,config,parser,scraper,db_writer,main,backfill}.py` + `README.md`
- `backend/alembic/versions/<rev>_add_pl_external_indicator.py`
- `backend/tests/enso_scraper/{test_parser,test_db_writer,test_main,test_backfill}.py`

### Modifier (additif)
- `backend/app/models/pipeline.py` → ajouter `PlExternalIndicator` (cf. §4.2)
- `backend/pyproject.toml` → entry points `enso-scraper` + `enso-scraper-backfill`
- `.github/workflows/deploy.yml` → ligne `deploy_job cc-enso-scraper 512Mi "enso-scraper"`
- `infra/terraform/scheduler.tf` → entry `enso-scraper`
- `CLAUDE.md` → section "Scrapers" mise à jour
- `docs/onboarding/HEDI_DATA_MAP.md` → §3.5 ENSO/FX marqué RESOLVED

### Ne pas toucher (interdiction explicite)
- `backend/app/engine/` → la consommation ENSO se fait en compute-time, hors scope scraper
- `backend/scripts/press_review_agent/`, `barchart_scraper/`, `cftc_scraper/`, `ice_stocks_scraper/`, `meteo_agent/` → isolation
- `pl_contract_data_daily` → ENSO n'a aucune raison de toucher cette table

---

## Annexe B — Liens

- Plan déploiement complet : [CAMPAIGN_5_PROD_DEPLOYMENT.md](../onboarding/CAMPAIGN_5_PROD_DEPLOYMENT.md) §5.1
- Data map détaillée : [HEDI_DATA_MAP.md](../onboarding/HEDI_DATA_MAP.md) §1.3 + §4.1
- Code R&D source : [docs/onboarding/ingest_enso.py](../onboarding/ingest_enso.py)
- Merge policy R&D : [docs/onboarding/external_data.py](../onboarding/external_data.py) (lag 14j)
- CSV backfill : [docs/onboarding/ENSO/oni_monthly.csv](../onboarding/ENSO/oni_monthly.csv) + `nino34_monthly.csv`
- US sœur FX : [P1-scraper-fx.md](P1-scraper-fx.md) (migration mutualisée)
- Pipeline error handling : [.claude/rules/pipeline-error-handling.md](../../.claude/rules/pipeline-error-handling.md)
- North-star : [.claude/rules/north-star-alignment.md](../../.claude/rules/north-star-alignment.md) (rule #4 + #6)
- Pattern scraper existant : `backend/scripts/cftc_scraper/` (pure httpx, idempotent UPSERT)
- NOAA PSL homepage : https://psl.noaa.gov/data/correlation/
