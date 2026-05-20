# Scrapers Stock + COT EU — Compléter la boucle fondamentaux LCE

**Statut :** Proposed (non implémenté)
**Date :** 2026-05-19 (révisé)
**Owner :** TBD (Hedi)
**Slug :** `scrapers-stock-cot-eu`
**Cible repo :** `docs/user-stories/P1-scrapers-stock-cot-eu.md`
**Deadline :** P1 — 2 sprints (~2 semaines)

> **Révision 2026-05-19** : pivot de schéma pour le COT EU — au lieu d'ajouter `com_net_eu` comme colonne de `pl_contract_data_daily`, on crée une **table dédiée `pl_cot_eu_weekly`** avec la décomposition complète (Producer/Merchant + Managed Money + Other Reportables + Non-Reportable + OI). Aligné avec les besoins R&D Campaign 5 ([HEDI_DATA_MAP.md §3.4](../onboarding/HEDI_DATA_MAP.md#34-pl_cot_eu_weekly-à-confirmer)) qui consomme 3 features pré-normalisées dérivées de Managed Money et Producer/Merchant (z-scores 26w + percentiles). Les z-scores sont calculés en compute-time par l'engine, pas par le scraper (rule north-star "rolling normalization"). Stock EU reste sur `pl_contract_data_daily.stock_eu_bags60kg` (commodity-centric daily data).

---

## 1. Contexte

Julien (Optimizer V3) demande la **fermeture de la boucle fondamentaux côté Europe** dans le dataset prod Compass. Aujourd'hui `pl_contract_data_daily` est asymétrique :

| Donnée | US (NY / CFTC) | EU (London / ICE) |
|---|---|---|
| OHLCV cocoa | ❌ (CC sur NY, hors scope Compass — on track LCE) | ✅ `pl_contract_data_daily.{open,high,low,close,volume,oi,iv}` via `barchart_scraper` |
| Stocks certifiés | ✅ `pl_contract_data_daily.stock_us` via `ice_stocks_scraper` (XLS public ICE US) | ❌ Colonne `stock_eu_bags60kg` créée en DB mais **jamais alimentée** |
| COT commercial net | ✅ `pl_contract_data_daily.com_net_us` via `cftc_scraper` (CFTC.gov, public) | ❌ Aucune table, aucun scraper |

Le contrat tradeable Compass est **CA\* (London cocoa #7, ICE Europe, GBP/tonne)**. Donc le COT pertinent est le **COT Europe (ICE)**, pas le COT US (CFTC). Le COT US reste utile comme proxy global mais n'est pas la mesure principale du positioning des managed money sur LCE.

Conséquence pour Optimizer :
- Indicator engine (`app/engine/`) calcule des z-scores sur `com_net_us` qui ne reflète pas le positioning London → le signal `com_net_norm` injecté dans le composite est **biaisé géographiquement**.
- Campaign 5 ensemble consomme **3 features dérivées de Managed Money + Producer/Merchant EU** (`cot_m_money_net_z_26w`, `cot_prod_merc_net_z_26w`, `cot_m_money_net_pctile_26w`) — non disponibles aujourd'hui.

**Décision schéma (2026-05-19)** : créer une table dédiée **`pl_cot_eu_weekly`** avec la décomposition complète COT EU plutôt qu'une seule colonne `com_net_eu` sur `pl_contract_data_daily`. Raisons :
- Le COT est **hebdomadaire** (publication vendredi pour mardi) — granularité différente de `pl_contract_data_daily` qui est daily
- Plusieurs catégories de positioning utilisées par R&D (au moins Managed Money + Producer/Merchant nets), pas juste le net commercial
- Évite le carry-forward daily du COT dans `pl_contract_data_daily` (anti-pattern : duplication, écritures redondantes)
- Aligné avec le pattern north-star "schema namespaces" (séparation par domaine : market data vs positioning data)
- Table multi-market ready (default `contract_market='cocoa'`, extensible)

**Sources fondamentales confirmées par Hedi (2026-05-19) :**
- Stock EU : `https://www.barchart.com/cmdty/data/fundamental/explore/IC345DRW.CS`
- COT Europe : `https://www.ice.com/report/122`

**Backfill historique** : Hedi possède déjà des données historiques (source TBD) qui pourront être chargées en post-shipping via une US séparée. **Hors scope de cette US** — la priorité est d'avoir des scrapers stables qui alimentent les sessions à venir.

**Pourquoi maintenant** : Optimizer V3 a livré son autonomie data ce weekend (S8). Le seul gap fondamental restant est cette asymétrie US/EU. C'est un blocage P1 pour V1.1 Optimizer (cible 2-3 semaines) **et bloquant pour le launch C5 ensemble**.

---

## 2. Goals & non-goals

### Goals (cette itération)
- Implémenter **2 nouveaux scrapers** Cloud Run Jobs alignés sur les patterns existants :
  - `cc-barchart-stocks-eu-scraper` → `pl_contract_data_daily.stock_eu_bags60kg` (daily, commodity-centric)
  - `cc-ice-cot-eu-scraper` → **`pl_cot_eu_weekly`** (NEW table dédiée, weekly, multi-category positioning)
- **Refactor parallèle** des 2 scrapers US existants (`ice_stocks_scraper`, `cftc_scraper`) pour aligner sur des helpers communs (`_shared/`) sans changement fonctionnel observable.
- Migration Alembic créant la table `pl_cot_eu_weekly` (additive, NULL-tolérant).
- Crons Cloud Scheduler alignés (19:05-19:10 UTC weekdays, après barchart-scraper qui crée la row de la session).
- Tests unit + intégration (TDD obligatoire, 80%+ coverage cf. `~/.claude/rules/common/testing.md`).
- Sentry alerting branché + fail-loud (cf. `.claude/rules/pipeline-error-handling.md`).
- **Window de validation 5 jours ouvrés** en prod avant déclaration "stable" (cf. §7).
- Doc mise à jour dans `CLAUDE.md` (section Scrapers).

### Non-goals
- **Pas de backfill historique** dans cette US. Hedi possède des données historiques qui seront chargées via une US follow-up (`P2-scrapers-eu-backfill.md` à créer après celle-ci). Cette US se concentre sur **les sessions à venir uniquement** (data J0 et au-delà).
- **Pas** de calcul de z-scores ou percentiles 26w dans le scraper. Ces features dérivées (`cot_m_money_net_z_26w`, `cot_prod_merc_net_z_26w`, `cot_m_money_net_pctile_26w`) sont **calculées en compute-time par l'engine ensemble** (matches le pattern rolling normalization, [.claude/rules/north-star-alignment.md](../../.claude/rules/north-star-alignment.md) rule #6). Le scraper écrit uniquement les valeurs **brutes** (long, short, net, OI).
- **Pas** de modification de la consommation downstream (indicator engine legacy, dashboard) dans cette US — `pl_cot_eu_weekly` est une nouvelle table qui sera consommée par l'engine ensemble C5 (PR séparée).
- **Pas** de migration / dépréciation de `com_net_us` — la colonne reste alimentée par CFTC sur `pl_contract_data_daily`, additive.
- **Pas** d'auto-retry sur les jobs (règle prod `pipeline-error-handling.md`).
- **Pas** de nouvelle UI dashboard.
- **Pas** de scraper pour COT US Cocoa Europe sur CFTC (qui n'existe pas — COT EU est publié par ICE, pas CFTC).
- **Pas** d'ajout de colonne `com_net_eu` à `pl_contract_data_daily` (anti-pattern : COT est weekly, pas daily ; table dédiée préférée).

---

## 3. Sources & cadence

### 3.1 Stock EU — Barchart cmdty

- **URL** : `https://www.barchart.com/cmdty/data/fundamental/explore/IC345DRW.CS`
- **Donnée** : Stocks certifiés ICE Europe cocoa
- **Format** : HTML server-rendered, **pas d'auth nécessaire** (spike 2026-05-20).
- **Cadence publication** : Daily (ouvré), confirmé par la page (`Frequency: Daily`).
- **Unité cible** : `bags60kg` — **natif** sur Barchart (`Unit: 60 Kg Bag`, `Multiplier: 1`). Pas de conversion.
- **Identifiant Barchart** : `IC345DRW.CS` (suffixe `.CS` = Cocoa Stocks). Historique depuis 2012-02-07.

**Spike result (2026-05-20)** : `curl -A "Mozilla/5.0..."` → HTTP 200, ~90 KB HTML, données en clair dans 2 tables `<table class="cmdty-quote-table">` :
- Table 1 = métadonnées (Most Recent Value/Date, Frequency, Unit, Multiplier, Prior Value/Date, First Value/Date)
- Table 2 = série historique 7 jours (`<th>MM-DD-YYYY</th><td>621,116</td>`)
- Format value : `621,116` (commas, integer, parser via `int(s.replace(",", ""))`)
- Format date : `MM-DD-YYYY`

**Décision tooling** : `httpx` + `BeautifulSoup` (deps déjà présentes). **Pas de Playwright** — image de container reste légère, scraper rapide.

**Risques d'implémentation** :
- Le HTML structure peut changer (Barchart pourrait renommer `cmdty-quote-table`) — fail-loud avec message clair si parse échoue.
- Rate limiting Barchart : User-Agent réaliste, 1 seule requête par run (low impact).

### 3.2 COT Europe — ICE report 122

- **URL** : `https://www.ice.com/report/122`
- **Donnée** : Commitments of Traders Europe — cocoa London. **Toutes les catégories de positioning** (pas seulement commercial net) :
  - **Producer/Merchant** (Long/Short) — couverture commerciale = position physique hedgée
  - **Managed Money** (Long/Short) — fonds spéculatifs (le signal R&D principal)
  - **Other Reportables** (Long/Short) — institutionnels divers
  - **Non-Reportable** (Long/Short) — petits traders agrégés
  - **Open Interest total** — pour normalisation %OI
- **Cadence publication** : hebdomadaire (vendredi soir pour snapshot mardi), équivalent du CFTC US Disaggregated TFF.
- **Format** : à explorer (HTML ? CSV ? PDF ?). Réutilisation possible de regex / httpx du `cftc_scraper` (pas de browser) si HTML/CSV.
- **Champs calculés** (colonnes générées Postgres, pas en compute) :
  - `prod_merc_net = prod_merc_long − prod_merc_short`
  - `m_money_net = m_money_long − m_money_short`

**Risques d'implémentation :**
- Format ICE peut être un PDF ou HTML mal structuré → parsing plus coûteux qu'un CSV CFTC. **Spike 0.5j** au début de l'US pour valider le format.
- Idempotence : la valeur est hebdo. Le scraper UPSERT sur `(release_date, contract_market)` — re-run sans changement = 0 modification. **Pas de carry-forward** (la table est weekly-keyed, l'engine fait le merge_asof daily).
- Si le format est PDF : ajouter `pdfplumber` aux deps `pyproject.toml`.

---

## 4. Migration DB

### 4.1 Nouvelle table `pl_cot_eu_weekly` (replaces `com_net_eu` column approach)

```python
# backend/alembic/versions/XXXX_add_pl_cot_eu_weekly.py
"""add pl_cot_eu_weekly table for ICE COT EU positioning

Revision ID: XXXX
Revises: <previous>
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
    if _has_table("pl_cot_eu_weekly"):
        return
    op.execute("""
        CREATE TABLE pl_cot_eu_weekly (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            release_date    DATE NOT NULL,          -- ICE publication date
            report_date     DATE NOT NULL,          -- the Tuesday the report covers
            contract_market VARCHAR(50) NOT NULL DEFAULT 'cocoa',
            -- Commercial: Producer / Merchant / Processor / User
            prod_merc_long  INTEGER,
            prod_merc_short INTEGER,
            prod_merc_net   INTEGER GENERATED ALWAYS AS (prod_merc_long - prod_merc_short) STORED,
            -- Non-commercial: Managed Money (the R&D signal)
            m_money_long    INTEGER,
            m_money_short   INTEGER,
            m_money_net     INTEGER GENERATED ALWAYS AS (m_money_long - m_money_short) STORED,
            -- Other Reportables
            other_rept_long INTEGER,
            other_rept_short INTEGER,
            -- Non-Reportable (small traders)
            non_rept_long   INTEGER,
            non_rept_short  INTEGER,
            -- Total OI for %OI normalization
            open_interest   INTEGER,
            created_at      TIMESTAMP NOT NULL DEFAULT now(),
            CONSTRAINT uq_cot_eu_weekly UNIQUE (release_date, contract_market)
        );
    """)
    op.create_index(
        "ix_cot_eu_weekly_report_date",
        "pl_cot_eu_weekly",
        ["report_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_cot_eu_weekly_report_date", table_name="pl_cot_eu_weekly")
    op.drop_table("pl_cot_eu_weekly")
```

**Notes** :
- Table NEW dédiée, **PAS** une colonne sur `pl_contract_data_daily` (revirement vs version initiale de cette US).
- `prod_merc_net` et `m_money_net` sont **colonnes générées** Postgres (`GENERATED ALWAYS AS ... STORED`) — pas de calcul côté code, intégrité garantie au niveau DB.
- Multi-market ready via `contract_market` (default `'cocoa'`, extensible à coffee/sugar plus tard sans nouvelle migration).
- Z-scores 26w + percentiles 26w **NE SONT PAS** stockés dans cette table — calculés en compute-time par l'engine ensemble (rule north-star "rolling normalization").
- Idempotent via `_has_table()` (cf. patterns existants dans `backend/alembic/versions/`).
- Index sur `report_date` (les queries downstream filtrent par `WHERE report_date <= :session_date` pour `merge_asof backward`).

### 4.2 Vérification colonne `stock_eu_bags60kg`

Cette colonne existe déjà sur `pl_contract_data_daily` selon le recap. Vérifier en début de US :
```bash
./.local/db-prod.sh exec "\d pl_contract_data_daily" | grep stock_eu_bags60kg
```
Si elle manque → l'ajouter dans une migration séparée (additive sur `pl_contract_data_daily`).

### 4.3 Modèles SQLAlchemy

Ajouter `PlCotEuWeekly` dans `backend/app/models/pipeline.py` :

```python
class PlCotEuWeekly(Base):
    """ICE COT Europe weekly positioning (cocoa London #7 + multi-market ready).

    Replaces the `com_net_eu` column approach (revision 2026-05-19). Weekly
    granularity, stored once per release, joined daily via merge_asof at
    engine compute-time. Z-scores 26w + percentiles computed downstream
    (rolling normalization rule).
    """
    __tablename__ = "pl_cot_eu_weekly"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    release_date: Mapped[date] = mapped_column(DATE, nullable=False)
    report_date: Mapped[date] = mapped_column(DATE, nullable=False)
    contract_market: Mapped[str] = mapped_column(
        VARCHAR(50), nullable=False, server_default="cocoa"
    )
    # Commercial
    prod_merc_long: Mapped[Optional[int]] = mapped_column(INTEGER)
    prod_merc_short: Mapped[Optional[int]] = mapped_column(INTEGER)
    # prod_merc_net is a GENERATED column (computed by Postgres, not by SQLAlchemy)
    prod_merc_net: Mapped[Optional[int]] = mapped_column(INTEGER, Computed("prod_merc_long - prod_merc_short", persisted=True))
    # Managed Money (the signal)
    m_money_long: Mapped[Optional[int]] = mapped_column(INTEGER)
    m_money_short: Mapped[Optional[int]] = mapped_column(INTEGER)
    m_money_net: Mapped[Optional[int]] = mapped_column(INTEGER, Computed("m_money_long - m_money_short", persisted=True))
    # Other Reportables + Non-Reportable
    other_rept_long: Mapped[Optional[int]] = mapped_column(INTEGER)
    other_rept_short: Mapped[Optional[int]] = mapped_column(INTEGER)
    non_rept_long: Mapped[Optional[int]] = mapped_column(INTEGER)
    non_rept_short: Mapped[Optional[int]] = mapped_column(INTEGER)
    # Total OI
    open_interest: Mapped[Optional[int]] = mapped_column(INTEGER)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("release_date", "contract_market", name="uq_cot_eu_weekly"),
        Index("ix_cot_eu_weekly_report_date", "report_date"),
    )
```

`PlContractDataDaily` reste **inchangé** côté COT (toujours `com_net_us` via CFTC scraper). Pas de `com_net_eu` column added.

---

## 5. Architecture cible

### 5.1 Arborescence

Refactor parallèle vers un namespace `fundamentals/` qui regroupe les 4 scrapers de fondamentaux (stocks + COT, US + EU). OHLCV reste séparé (`barchart_scraper/`) car il a une nature différente (donnée market, pas fondamentaux).

```
backend/scripts/fundamentals/
├── __init__.py
├── _shared/
│   ├── __init__.py
│   ├── http_client.py        # httpx wrapper (timeouts, headers, retry-policy DISABLED — fail-loud)
│   ├── date_utils.py         # business-day walkback, weekend → friday, display_date
│   ├── db_writer.py          # upsert pattern commun vers pl_contract_data_daily
│   ├── carry_forward.py      # logique COT (data hebdo → carry-forward sur sessions intermédiaires)
│   └── playwright_helpers.py # Playwright session (utilisé par barchart_stocks_eu)
│
├── ice_stocks_us/            # REFACTOR de backend/scripts/ice_stocks_scraper/
│   ├── __init__.py
│   ├── config.py
│   ├── scraper.py            # pure httpx, parse XLS, conversion bags→tonnes
│   ├── main.py               # @sentry_monitor, CLI args
│   └── README.md
│
├── cftc_us/                  # REFACTOR de backend/scripts/cftc_scraper/
│   ├── __init__.py
│   ├── config.py
│   ├── scraper.py            # pure httpx + regex sur ag_lf.htm
│   ├── main.py
│   └── README.md
│
├── barchart_stocks_eu/       # NOUVEAU
│   ├── __init__.py
│   ├── config.py
│   ├── scraper.py            # Playwright sur IC345DRW.CS
│   ├── main.py
│   └── README.md
│
└── ice_cot_eu/               # NOUVEAU
    ├── __init__.py
    ├── config.py
    ├── scraper.py            # httpx sur ice.com/report/122
    ├── main.py
    └── README.md
```

**Pourquoi cette structure :**
- **Cohésion par domaine** (fondamentaux vs market) — aligné avec `~/.claude/rules/common/coding-style.md` (organiser par feature/domaine, pas par type).
- **Helpers communs `_shared/`** = pas de duplication entre US/EU. Test centralisé.
- **1 scraper = 1 dossier** = isolation, suppressibilité, ownership clair.
- **Refactor sans changement fonctionnel** : les 2 US existants gardent leur comportement observable (mêmes CSV, mêmes lignes DB, mêmes crons), juste leur implémentation utilise les helpers `_shared/`.

### 5.2 Patterns à réutiliser

Strictement inspirés de l'existant pour ne pas réinventer :

| Pattern | Source | Notes |
|---|---|---|
| `@monitor(monitor_slug="…")` Sentry | `backend/scripts/cftc_scraper/main.py:29` | Wrapper de Sentry pour cron monitoring |
| `should_skip_non_trading_day(force=…)` | `backend/scripts/db.py` | Skip auto weekend + jours fériés UK (applicable au barchart_stocks_eu daily ; pas applicable au cot_eu hebdo) |
| `init_sentry("scraper-name")` | `app/core/sentry.py` | Init avant `@monitor` |
| `load_dotenv(...)` | `backend/scripts/*/main.py` | Charger .env avant Sentry |
| `argparse` `--dry-run`, `--force` | tous les scrapers existants | Convention CLI |
| Playwright `wait_until="load"` + fixed wait | `backend/scripts/barchart_scraper/scraper.py` | Networkidle ne fire jamais sur Barchart |
| Upsert sur `(date, contract_id)` (pl_contract_data_daily) | `backend/scripts/cftc_scraper/db_writer.py` | Update partiel — utilisé par `barchart_stocks_eu` (stock_eu_bags60kg) |
| Upsert sur `(release_date, contract_market)` (pl_cot_eu_weekly) | NEW pattern dans `ice_cot_eu/db_writer.py` | INSERT ON CONFLICT (release_date, contract_market) DO UPDATE SET ... — colonnes générées (`prod_merc_net`, `m_money_net`) sont auto-calculées par Postgres, ne pas les inclure dans SET |

### 5.3 Entry points pyproject

```toml
# backend/pyproject.toml — section [tool.poetry.scripts]
# Aliases existants (à modifier pour pointer vers la nouvelle arbo)
ice-stocks-scraper = "scripts.fundamentals.ice_stocks_us.main:main"
cftc-scraper       = "scripts.fundamentals.cftc_us.main:main"

# Nouveaux aliases
barchart-stocks-eu-scraper = "scripts.fundamentals.barchart_stocks_eu.main:main"
ice-cot-eu-scraper         = "scripts.fundamentals.ice_cot_eu.main:main"
```

Les noms CLI existants (`ice-stocks-scraper`, `cftc-scraper`) sont **préservés** pour ne pas casser les workflows Cloud Run (les Job specs référencent ces aliases).

---

## 6. Schedule + déploiement

### 6.1 Cron Cloud Scheduler

| Job | Cron (UTC) | Dépendance amont |
|---|---|---|
| `cc-barchart-scraper` (existant) | `0 19 * * 1-5` | — (crée la row de la session) |
| `cc-ice-stocks-scraper` (existant) | `5 19 * * 1-5` | barchart row exists |
| `cc-cftc-scraper` (existant) | `5 19 * * 1-5` | barchart row exists |
| `cc-barchart-stocks-eu-scraper` (**NOUVEAU**) | `10 19 * * 1-5` | barchart row exists |
| `cc-ice-cot-eu-scraper` (**NOUVEAU**) | `10 19 * * 1-5` | barchart row exists |
| `cc-compute-indicators` (existant) | `15 19 * * 1-5` | tous les scrapers fonda done |

Schedulers en `europe-west1` (Cloud Scheduler ne supporte pas `europe-west9`). `retryCount=0`.

### 6.2 Cloud Run Jobs

Same Dockerfile pattern que les existants :
- `backend/Dockerfile.jobs` (Playwright inclus) pour `barchart_stocks_eu` (suppose Playwright nécessaire — à confirmer en dev)
- `backend/Dockerfile` (sans Playwright, ~200MB) pour `ice_cot_eu` (pure httpx)

Config Cloud Run Job (cohérente avec `cftc_scraper`) :
- Region `europe-west9`
- 512Mi RAM, 1 CPU
- `--max-retries=0` (fail-loud)
- VPC connector existant (`cc-vpc-connector`)
- Secret Manager pour DB URL
- Workload Identity Federation (pas de SA key file)

### 6.3 CI/CD

Mise à jour `.github/workflows/deploy.yml` :
- Ajouter les 2 nouveaux Cloud Run Jobs dans la liste des `deploy:` steps
- Mettre à jour les imports paths pour les 2 US refactorés (`scripts.fundamentals.ice_stocks_us` vs `scripts.ice_stocks_scraper`)

### 6.4 Terraform

`infra/terraform/scrapers.tf` (ou équivalent) :
- 2 nouveaux `google_cloud_run_v2_job` + 2 nouveaux `google_cloud_scheduler_job`
- Vérifier que les SA existants ont les bons rôles (`roles/cloudsql.client`, accès Secret Manager)

---

## 7. Critères d'acceptance

### MVP shipped quand :

1. **Migrations appliquées en prod GCP** :
   - Table `pl_cot_eu_weekly` créée (avec colonnes générées `prod_merc_net`, `m_money_net`)
   - Colonne `pl_contract_data_daily.stock_eu_bags60kg` existante confirmée (ajoutée si manquante)
   - Migrations Alembic réversibles
2. **4 scrapers fonctionnels en prod** : 4 Cloud Run Jobs déployés, 4 Cloud Scheduler jobs configurés, exécutions automatiques 19:00-19:10 UTC weekdays.
3. **Window de validation 5 jours ouvrés consécutifs** sans erreur post-activation :
   - 5 exécutions automatiques successives en succès pour chaque nouveau scraper
   - 5 rows écrites avec `stock_eu_bags60kg IS NOT NULL` sur `pl_contract_data_daily`
   - Au moins 1 nouvelle row dans `pl_cot_eu_weekly` (la publication ICE COT EU est hebdo — typiquement vendredi pour mardi)
   - Aucune alerte Sentry sur la fenêtre
   - Vérification SQL :
     ```sql
     -- Stock EU sur pl_contract_data_daily
     SELECT date, stock_us, stock_eu_bags60kg, com_net_us
     FROM pl_contract_data_daily
     WHERE date >= CURRENT_DATE - 7 ORDER BY date DESC;

     -- COT EU sur la nouvelle table
     SELECT release_date, report_date,
            prod_merc_long, prod_merc_short, prod_merc_net,
            m_money_long, m_money_short, m_money_net,
            open_interest
     FROM pl_cot_eu_weekly
     WHERE release_date >= CURRENT_DATE - 14 ORDER BY release_date DESC;
     ```
4. **Refactor sans régression** : `ice-stocks-scraper` et `cftc-scraper` continuent d'écrire `stock_us` et `com_net_us` aux mêmes cadences, valeurs identiques bit-à-bit à l'avant-refactor sur les 5 derniers jours (diff CSV avant/après).
5. **Tests unit ≥ 80% coverage** sur `scripts/fundamentals/_shared/` + chacun des 4 scrapers.
6. **Tests d'intégration** : 1 test par scraper qui mocke la source HTTP, vérifie le parsing et l'upsert DB. Pour `ice_cot_eu` : vérifier en plus que les colonnes générées `prod_merc_net`, `m_money_net` sont auto-calculées correctement.
7. **Sentry monitor configuré** pour les 2 nouveaux jobs (`barchart-stocks-eu-scraper`, `ice-cot-eu-scraper`).
8. **Doc mise à jour** : section "Scrapers" de `CLAUDE.md` étendue avec les 2 nouveaux + nouvelle arbo, README.md par scraper.
9. **Hedi a uploadé un CSV de test** à Julien avec les 5 derniers jours `pl_contract_data_daily` + dump récent `pl_cot_eu_weekly` pour validation côté Optimizer / R&D (via `extract-prod-weekly.sh` mis à jour).
10. **Backfill US follow-up créée** : `docs/user-stories/P2-scrapers-eu-backfill.md` rédigée (squelette minimum), référençant les données historiques que Hedi détient. Le merge de cette US débloque la création du backfill.

### Rejet si :

- Un seul des 4 scrapers a un `try/except` qui swallow une erreur silencieusement (cf. `pipeline-error-handling.md`).
- Auto-retry / fallback provider implémenté nulle part (règle interdite).
- La colonne `com_net_us` est touchée (renommée, supprimée) — additive only.
- **Ajout d'une colonne `com_net_eu` à `pl_contract_data_daily`** (revirement de schéma : on utilise la table dédiée `pl_cot_eu_weekly`).
- Z-scores 26w ou percentiles calculés DANS le scraper (doit rester côté engine en compute-time).
- Le refactor introduit une dépendance circulaire ou casse un import existant.
- `stock_eu_bags60kg` est écrit en `tonnes` au lieu de `bags60kg` (cohérence sémantique avec le nom de colonne).
- Le composite signal change de valeur sur les rows existantes (= régression algo, hors scope).
- Tentative d'inclure du backfill dans cette US (= scope creep, doit aller en follow-up).

---

## 8. Plan de vérification

### 8.1 Tests unitaires

```bash
# Helpers communs
poetry run pytest backend/tests/fundamentals/test_shared_http_client.py
poetry run pytest backend/tests/fundamentals/test_shared_date_utils.py
poetry run pytest backend/tests/fundamentals/test_shared_db_writer.py
poetry run pytest backend/tests/fundamentals/test_shared_carry_forward.py

# Scrapers (1 fichier par scraper)
poetry run pytest backend/tests/fundamentals/test_ice_stocks_us.py
poetry run pytest backend/tests/fundamentals/test_cftc_us.py
poetry run pytest backend/tests/fundamentals/test_barchart_stocks_eu.py
poetry run pytest backend/tests/fundamentals/test_ice_cot_eu.py

# Coverage check
poetry run pytest --cov=scripts.fundamentals --cov-report=term-missing
```

### 8.2 Tests d'intégration local

```bash
# Pre-req: DB locale propre + .env configuré
pnpm db:up
poetry run alembic upgrade head

# Test 1: chaque scraper en dry-run
poetry run ice-stocks-scraper --dry-run --verbose
poetry run cftc-scraper --dry-run --verbose
poetry run barchart-stocks-eu-scraper --dry-run --verbose
poetry run ice-cot-eu-scraper --dry-run --verbose

# Test 2: scraper réel + verif DB
poetry run ice-stocks-scraper
poetry run cftc-scraper
poetry run barchart-stocks-eu-scraper
poetry run ice-cot-eu-scraper

# Stock US + Stock EU sur pl_contract_data_daily
psql -h localhost -p 5433 -U postgres -d commodities_compass -c "
  SELECT date, stock_us, stock_eu_bags60kg, com_net_us
  FROM pl_contract_data_daily
  WHERE date >= CURRENT_DATE - 7
  ORDER BY date DESC;
"

# COT EU sur la nouvelle table dédiée
psql -h localhost -p 5433 -U postgres -d commodities_compass -c "
  SELECT release_date, report_date,
         prod_merc_long, prod_merc_short, prod_merc_net,
         m_money_long, m_money_short, m_money_net,
         open_interest
  FROM pl_cot_eu_weekly
  WHERE release_date >= CURRENT_DATE - 14
  ORDER BY release_date DESC;
"

# Idempotence : re-run ne crée pas de doublons
poetry run ice-cot-eu-scraper
poetry run ice-cot-eu-scraper  # 2e run
psql -c "SELECT count(*) FROM pl_cot_eu_weekly WHERE release_date = (SELECT MAX(release_date) FROM pl_cot_eu_weekly);"
# attendu : 1 row par release_date
```

### 8.3 Diff avant/après refactor

Pour garantir zéro régression sur les 2 scrapers US existants :

```bash
# Avant le refactor : extract 5 derniers jours
git checkout main
poetry run ice-stocks-scraper --dry-run > /tmp/before-stocks.log
poetry run cftc-scraper --dry-run > /tmp/before-cftc.log

# Après le refactor (branche feature)
git checkout feat/scrapers-fundamentals-eu
poetry run ice-stocks-scraper --dry-run > /tmp/after-stocks.log
poetry run cftc-scraper --dry-run > /tmp/after-cftc.log

diff /tmp/before-stocks.log /tmp/after-stocks.log   # doit être vide ou cosmétique
diff /tmp/before-cftc.log /tmp/after-cftc.log
```

### 8.4 Window de validation 5 jours ouvrés (prod)

C'est le critère qui consacre la stabilité. Sur la fenêtre J+1 → J+5 post-activation :

```bash
# Jour J+1 à J+5 : check quotidien le lendemain matin
./.local/db-prod.sh up

# Stock EU (daily granularity) — should be 5/5 has_stock_eu
./.local/db-prod.sh exec "
  WITH last_5 AS (
    SELECT date, stock_us, stock_eu_bags60kg, com_net_us
    FROM pl_contract_data_daily
    WHERE date >= CURRENT_DATE - 7
    ORDER BY date DESC
    LIMIT 5
  )
  SELECT
    date,
    stock_us IS NOT NULL AS has_stock_us,
    stock_eu_bags60kg IS NOT NULL AS has_stock_eu,
    com_net_us IS NOT NULL AS has_cot_us_legacy
  FROM last_5;
"

# COT EU (weekly granularity) — at least 1 fresh row over the window
./.local/db-prod.sh exec "
  SELECT release_date, report_date, m_money_net, prod_merc_net
  FROM pl_cot_eu_weekly
  WHERE release_date >= CURRENT_DATE - 14
  ORDER BY release_date DESC;
"

./.local/db-prod.sh down

# Critère :
#  - Stock EU : 5/5 lignes avec has_stock_eu = TRUE
#  - COT EU : ≥ 1 row publiée sur la fenêtre (typiquement vendredi)
# Sinon → investigation Sentry + Cloud Logging avant d'agréger validation.
```

Parallèlement, monitoring Sentry sur les 5 jours :

```bash
gcloud logging read 'resource.type=cloud_run_job AND resource.labels.job_name=("cc-barchart-stocks-eu-scraper" OR "cc-ice-cot-eu-scraper") AND severity>=WARNING' \
  --limit 50 --project=cacaooo --freshness=5d
```

Aucune ligne attendue.

### 8.5 Validation côté Julien

Envoyer un extract de 5 jours incluant les nouvelles colonnes :
```bash
./.local/extract-prod-weekly.sh 50
# Le CSV contiendra stock_eu_bags60kg une fois la US shipped (pl_contract_data_daily).
# IMPORTANT : ajouter cette colonne au SELECT du script extract-prod-weekly.sh dans la même PR.
# Pour COT EU : générer un second extract depuis pl_cot_eu_weekly (e.g., ./.local/extract-cot-eu-weekly.sh)
```

Julien confirme par retour que :
- Les valeurs `stock_eu_bags60kg` sont cohérentes avec ce qu'il observe ailleurs (Barchart manuel ou autres sources de cross-check)
- Les valeurs `m_money_net` et `prod_merc_net` dans `pl_cot_eu_weekly` correspondent à ce qu'il attend pour le COT EU (ordre de grandeur du COT US adapté à la taille du marché LCE, signes Producer/Merchant typiquement net SHORT, Managed Money typiquement net LONG en régime bull cocoa)

---

## 9. Risques & mitigation

| Risque | Probabilité | Impact | Mitigation |
|---|---|---|---|
| Barchart cmdty page nécessite login / session | Moyenne | Élevé (bloque scraper EU stocks) | Spike de 0.5j en début de US pour explorer l'auth Barchart. Plan B : utiliser une autre source (LiveCharts, ICE direct si disponible). |
| ICE report 122 publié en PDF | Faible | Moyen (parsing coûteux) | Investigation source upfront. Si PDF : ajouter `pdfplumber` aux deps. |
| Refactor casse la prod | Faible | Élevé | Diff test (§8.3) obligatoire avant merge. PR review systématique. Déploiement progressif : helpers `_shared/` d'abord, scrapers refactorés un par un. |
| `stock_eu_bags60kg` sémantique unit mismatch | Moyenne | Moyen (data corruption) | Vérif manuelle en début de US : la colonne existe-t-elle vraiment en prod ? Quelle unité dans le scraper Barchart cible ? Conversion explicite + commentaire dans le code. |
| Cadence COT EU différente de CFTC US (jour de publication) | Élevée | Faible | Carry-forward dans `_shared/carry_forward.py` (pattern identique au CFTC). |
| ICE rate-limit ou bloque le scraping | Faible | Élevé | User-Agent réaliste + délai entre requêtes. Si bloqué : Plan B = scraper alternatif (ex: investiguer si Barchart a aussi le COT EU). |
| Window de validation interrompue par UK holiday | Moyenne | Faible | Les 5 jours sont 5 jours **ouvrés LCE** (skip auto via `should_skip_non_trading_day`). Si jour férié dans la fenêtre → on étend. |

---

## 10. Open questions / décisions à prendre

1. **Stock EU unité source** : Barchart publie en `bags60kg` directement ou en `tonnes` ? → à confirmer au premier scrape exploratoire. Si tonnes → conversion `tonnes / 0.06` côté scraper (commentaire obligatoire dans le code).
2. **ICE report 122 format** : HTML / CSV / PDF ? → à confirmer avant d'estimer la complexité du parsing. Spike 0.5j prévu.
3. **Refactor scope** : on déplace aussi `backend/scripts/barchart_scraper/` (OHLCV) dans `fundamentals/` ou il reste séparé ? → **Recommandation : reste séparé** (OHLCV est market data, pas fondamentaux). À valider avec Hedi.
4. **Cadence du job COT EU** : ✅ **RESOLVED (2026-05-19)** — daily run `5 19 * * 1-5` avec UPSERT idempotent sur `(release_date, contract_market)`. Pas de carry-forward dans le scraper (la table est weekly-keyed, l'engine fait le `merge_asof backward` daily en compute-time). Le scraper run tous les jours mais ne crée une nouvelle row que les jours où ICE publie un nouveau report.
5. **Schéma COT EU** : ✅ **RESOLVED (2026-05-19)** — table dédiée `pl_cot_eu_weekly` (pas une colonne sur `pl_contract_data_daily`). Décomposition complète Managed Money + Producer/Merchant + Other Reportables + Non-Reportable + OI. Cf. §4.1.
6. **Tests d'intégration GCP** : on ajoute un step CI qui exécute les scrapers contre une DB de staging ? → Hors scope MVP (pattern non existant aujourd'hui).
7. **Sources backfill historique** : où sont les données que Hedi possède ? Format (CSV / Parquet / Excel / source publique re-scrapable) ? → À documenter dans la US follow-up `P2-scrapers-eu-backfill.md`, **pas dans cette US**.
8. **`extract-prod-weekly.sh`** : on met à jour le SELECT pour inclure `stock_eu_bags60kg` dans la même PR ou en post-PR ? Pour COT EU : il faut un second extract `extract-cot-eu-weekly.sh` ou bien étendre `extract-prod-weekly.sh` avec un JOIN sur `pl_cot_eu_weekly` ? → **Recommandation : 2 scripts séparés** (granularités différentes : daily vs weekly).
9. **Calcul des z-scores 26w + percentiles côté engine** : où exactement (`backend/app/engine/ensemble/features_*.py` côté C5, ou un job intermédiaire daily ?) → Sera décidé dans l'US ensemble compute (`cc-ensemble-compute`). Hors scope de cette US.

---

## 11. Séquence d'exécution (workplan)

Phasing pour livrer en 2 sprints (~2 semaines) :

### Sprint 1 (semaine 1) — Plomberie + refactor

| Jour | Tâche |
|---|---|
| J1 | Spike exploratoire (0.5j) : auth Barchart cmdty + format ICE report 122 |
| J1 | Migration Alembic `pl_cot_eu_weekly` (local + prod via bastion) + check `stock_eu_bags60kg` column |
| J2 | Helpers `_shared/` (http_client, date_utils, db_writer, playwright_helpers) + tests unit. Pas de `carry_forward.py` (rendu obsolète par le pivot table dédiée). |
| J3 | Refactor `ice_stocks_scraper` → `fundamentals/ice_stocks_us/` + diff test |
| J4 | Refactor `cftc_scraper` → `fundamentals/cftc_us/` + diff test |
| J5 | Code review + PR refactor (mergeable en isolation, sans les 2 nouveaux scrapers) |

### Sprint 2 (semaine 2) — Nouveaux scrapers + validation

| Jour | Tâche |
|---|---|
| J6 | Scraper `barchart_stocks_eu` (impl + tests) |
| J7 | Scraper `ice_cot_eu` (impl + tests) |
| J8 | Cloud Run Job + Scheduler + Terraform pour les 2 nouveaux scrapers |
| J9 | Deploy preview + smoke test |
| J9 | Update `CLAUDE.md` + `extract-prod-weekly.sh` |
| J10 | Activation crons prod + démarrage window de validation 5 jours |
| J10 | Création US follow-up backfill (`P2-scrapers-eu-backfill.md`) |
| J11-J15 | Monitoring window 5 jours ouvrés, troubleshoot si besoin |
| J15 | Communication Julien : CSV étendu + accusé "stable" |

---

## 12. US follow-up : backfill

Une fois cette US shipped + validée (5 jours window OK), créer :

**`docs/user-stories/P2-scrapers-eu-backfill.md`** — Backfill historique `stock_eu_bags60kg` + `pl_cot_eu_weekly`

Scope estimé :
- Module local one-shot dans `backend/scripts/backfills/eu_fundamentals/`
- Lecture des données historiques que Hedi possède (format à documenter)
- 2 cibles distinctes :
  - Stock EU → UPSERT dans `pl_contract_data_daily` par `(date, contract_id)` avec flag `is_backfill` (pattern de `P1-press-review-backfill-10y.md`)
  - COT EU → INSERT dans `pl_cot_eu_weekly` par `(release_date, contract_market)`. Pas de flag `is_backfill` nécessaire (table greenfield, toutes les rows backfillées sont les seules existantes au moment du backfill).
- Recompute des features aval sur la fenêtre backfillée (z-scores 26w côté engine ensemble)
- Validation : pas de régression sur les features déjà calculées post-J0 (post-cette-US)

**À NE PAS faire avant le merge de cette US-ci** — l'enjeu est de stabiliser le pipeline forward d'abord, comme demandé par Hedi (2026-05-19).

---

## Annexe A — Fichiers à créer / modifier

### Créer (nouveaux)
- `backend/scripts/fundamentals/__init__.py`
- `backend/scripts/fundamentals/_shared/__init__.py`
- `backend/scripts/fundamentals/_shared/http_client.py`
- `backend/scripts/fundamentals/_shared/date_utils.py`
- `backend/scripts/fundamentals/_shared/db_writer.py`
- `backend/scripts/fundamentals/_shared/playwright_helpers.py`
- `backend/scripts/fundamentals/barchart_stocks_eu/{__init__,config,scraper,main}.py` + `README.md`
- `backend/scripts/fundamentals/ice_cot_eu/{__init__,config,scraper,parser,main}.py` + `README.md` (parser.py spécifique pour le format ICE)
- `backend/alembic/versions/XXXX_add_pl_cot_eu_weekly.py`
- `backend/app/models/pipeline.py` → ajouter classe `PlCotEuWeekly` (§4.3)
- `backend/tests/fundamentals/test_shared_*.py` (3-4 fichiers, sans `test_shared_carry_forward.py` obsolète)
- `backend/tests/fundamentals/test_barchart_stocks_eu.py`
- `backend/tests/fundamentals/test_ice_cot_eu.py`
- `.local/extract-cot-eu-weekly.sh` (nouveau script pour exporter `pl_cot_eu_weekly` vers Julien)
- `docs/user-stories/P2-scrapers-eu-backfill.md` (squelette US follow-up, à la fin de cette US)

### Modifier (refactor)
- `backend/scripts/ice_stocks_scraper/` → déplacer vers `backend/scripts/fundamentals/ice_stocks_us/` + adopter les helpers `_shared/`
- `backend/scripts/cftc_scraper/` → déplacer vers `backend/scripts/fundamentals/cftc_us/` + adopter les helpers `_shared/`
- `backend/tests/test_ice_stocks_scraper.py` → `backend/tests/fundamentals/test_ice_stocks_us.py`
- `backend/tests/test_cftc_scraper.py` → `backend/tests/fundamentals/test_cftc_us.py`
- `backend/pyproject.toml` → 2 nouveaux entry points + paths refactorés des 2 anciens
- `.github/workflows/deploy.yml` → 2 nouveaux Cloud Run Jobs + 2 nouveaux Schedulers, paths refactorés
- `infra/terraform/scheduler.tf` → 2 nouvelles entries (`barchart-stocks-eu-scraper`, `ice-cot-eu-scraper`)
- `CLAUDE.md` → section "Scrapers" mise à jour avec les 4 scrapers fondamentaux + nouvelle arbo `fundamentals/` + mention table `pl_cot_eu_weekly`
- `.local/extract-prod-weekly.sh` → SELECT mis à jour pour inclure `stock_eu_bags60kg` (COT EU séparé dans son propre script)
- `docs/onboarding/HEDI_DATA_MAP.md` → §3.4 marquer COT EU RESOLVED, pointer vers cette US

### Supprimer (post-merge)
- `backend/scripts/ice_stocks_scraper/` (vide après le mv)
- `backend/scripts/cftc_scraper/` (vide après le mv)

---

## Annexe B — Liens

- Recap weekend Julien 2026-05-17 : `RECAP_WEEKEND_2026-05-17.md`
- Counter-proposal snapshot R&D : `docs/Rnd_Project/RESPONSE_AGENT_PROD_RND_SNAPSHOT_2026-05-19.md`
- Note Hedi 16/05 (en partie OBE) : `NOTE_HEDI_2026-05-16.md`
- Brief original Optimizer Bridge : `BRIEF_PROD_OPTIMIZER_BRIDGE_2026-05-17.md`
- Pipeline error handling rule : `.claude/rules/pipeline-error-handling.md`
- Pipeline continuity rule : `.claude/rules/pipeline-continuity.md`
- North Star alignment : `.claude/rules/north-star-alignment.md`
- Patterns existants : `backend/scripts/ice_stocks_scraper/`, `backend/scripts/cftc_scraper/`, `backend/scripts/barchart_scraper/`
- Runbook contract roll (pour contexte du contract-centric model) : `docs/runbooks/contract-roll-procedure.md`
- US follow-up backfill (à créer en J10) : `docs/user-stories/P2-scrapers-eu-backfill.md`
