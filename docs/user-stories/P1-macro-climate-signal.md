# Macro-Climate Signal Integration — Feature Spec

**Statut :** Partiellement réalisé (path différent de la spec)
**Date :** 2026-05-07 (spec) / 2026-05-26 (statut)
**Owner :** Hedi
**Slug :** `macro-climate-signal`
**Cible repo :** `docs/user-stories/P1-macro-climate-signal.md`

> **2026-05-26 — Statut actuel** : le **scraper ENSO** ([backend/scripts/enso_scraper/](../../backend/scripts/enso_scraper/)) est shippé et alimente `pl_external_indicator` avec ONI + Niño 3.4 (ingest_enso.py R&D code adapté). Il est consommé par 6 des 14 spécialistes Campaign 5 — pas par `press_review_agent` ni `daily-analysis`. La table `pl_climate_signal` proposée dans cette spec n'a PAS été créée : on a stocké les indices ENSO directement sur le pattern `pl_external_indicator` partagé avec FX. Le hook côté `daily-analysis` (Call #1 `macroeco_bonus`) ne lit pas explicitement les signaux climat — c'est intentionnel pour cette itération. Ré-évaluation post-launch Campaign 5 (~juillet 2026).

---

## 1. Contexte

Le 3-4 mai 2026, l'OMM puis NOAA ont signalé un renforcement du risque El Niño avec un impact attendu sur la campagne cocoa Afrique de l'Ouest sur un horizon 6-12 mois. Le marché a réagi avant que notre pipeline ne capte le signal.

**Ce qu'on a capté (a posteriori, via press review)** :

> J+1 (CocoaIntel) : *"Sur l'ensemble de la zone, le risque climatique s'intensifie : l'Organisation météorologique mondiale signale une probabilité grandissante d'un épisode El Niño, susceptible de réduire les rendements au cœur de la saison sèche sud-américaine, notamment en Équateur où les prévisions de mi-cycle ont déjà été révisées à la baisse."*

> J+2 (CocoaIntel, 4 mai) : *"Le risque El Niño se renforce, alimentant la crainte de perturbations généralisées, notamment en Équateur où le pronostic de mi-campagne a été révisé en baisse suite à des conditions climatiques défavorables."*

**Diagnostic des trous** :

1. `meteo_agent` (`backend/scripts/meteo_agent/`) — sources : Open-Meteo, scope : 6 villes Ghana/CI, horizon : J-1 à J+1. Aveugle par construction aux signaux globaux. Le system prompt ne mentionne ni ENSO ni El Niño.
2. `press_review_agent` (`backend/scripts/press_review_agent/config.py`) — 8 sources spécialisées + 8 RSS Google News. Aucune query "El Niño / ENSO / NOAA". Capté en J+1/J+2 par effet collatéral via CocoaIntel, après le mouvement de marché.
3. `daily-analysis` Call #1 (`backend/scripts/daily_analysis/prompts.py:17-102`) produit déjà un `macroeco_bonus` ∈ [-0.10, +0.10] injecté dans le composite. Le canal d'injection existe mais le contenu en amont est aveugle aux signaux climat globaux.

Les sources scientifiques officielles (NOAA CPC, NOAA OISST, IRI, BoM) publient typiquement **5 à 14 jours avant** que les desks et la presse financière ne reprennent. Capter ces signaux à la source = lead time exploitable.

---

## 2. Goals & non-goals

### Goals (cette itération)

- Capter les signaux macro-climat (ENSO + Atlantic Niño) dès publication par NOAA / IRI / Open-Meteo Climate API
- Persister les inputs bruts dans une table dédiée et auditable
- Produire une synthèse FR exploitable par le `daily-analysis` LLM Call #1
- Pondérer le `macroeco_bonus` existant en croisant signal scientifique et signal presse
- Documenter les autres familles macro identifiées (maladies, politique, financier) pour itérations futures

### Non-goals

- Pas de nouvelle gauge dans la power formula composite (Option 3 quantitative — différée jusqu'à 3-6 mois d'historique)
- Pas de nouvelle UI dashboard (badge climat ou carte dédiée — différé)
- Pas d'agent pour les autres familles macro (hors scope MVP)
- Pas de backtesting historique sur les épisodes ENSO passés (nice-to-have, hors scope)

---

## 3. Cartographie des facteurs macro cocoa

Univers identifié des facteurs macro indépendants des technicals et de la météo locale, susceptibles de déclencher des mouvements type El Niño 2024.

| Famille | Impact 2023-25 | Indép. tech / local weather | Statut MVP |
|---|---|---|---|
| **Climat macro** (ENSO, Atlantic Niño, IOD, MJO, WAM) | Très fort | Oui | **Instrumenté** |
| Maladies / ravageurs (black pod, swollen shoot, mirides) | Très fort | Oui | Hors scope (itération future) |
| Politique pays producteur (EUDR, farmgate CCC/COCOBOD, taxes, stabilité) | Très fort | Oui | Hors scope (itération future) |
| Régime financier macro (DXY, GBP/USD, real rates) | Moyen | Limite (recoupe technicals) | Hors scope |
| Demande industrielle (grindings ICCO/NCA/ECA, earnings) | Moyen-Fort | Oui | Partiellement capté via press review (cf. `icco-grinding-alerts.md`) |
| Spec positioning (CFTC non-com, ETF flows) | Faible-Moyen | Recoupe OI | Partiellement capté (COM NET déjà ingéré) |

Cette table sert de roadmap. Chaque famille future suivra le même pattern d'architecture (table dédiée + agent indépendant + hook prompt daily-analysis).

---

## 4. Détail des signaux climat candidats

| Signal | Source | URL | Fréquence | Format | MVP |
|---|---|---|---|---|---|
| ONI (Oceanic Niño Index) | NOAA CPC | `https://origin.cpc.ncep.noaa.gov/products/analysis_monitoring/ensostuff/ONI_v5.php` | Mensuel | Texte tabulaire | Oui |
| Niño 3.4 SST anomaly hebdo | NOAA OISST v2.1 | `https://www.cpc.ncep.noaa.gov/data/indices/wksst9120.for` | Hebdomadaire | TXT colonnes fixes | Oui |
| ENSO Diagnostic Discussion | NOAA CPC | `https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml` | Mensuel (2e jeudi) | HTML | Oui |
| ENSO Probabilistic Forecast | NOAA CPC + IRI | `https://iri.columbia.edu/our-expertise/climate/forecasts/enso/current/` | Mensuel | HTML + image | Oui |
| Atlantic Niño / Cold Tongue SST | NOAA OISST | (même fichier wksst) | Hebdomadaire | TXT | Oui |
| Seasonal precip forecast belt cocoa (6 mois) | Open-Meteo Climate API | `https://climate-api.open-meteo.com/v1/climate?...` | Mensuel | JSON | Oui |
| BoM ENSO Wrap-Up + SOI | BoM Australia | `http://www.bom.gov.au/climate/enso/wrap-up/` | Bi-hebdo + quotidien | HTML | Backlog |
| IOD (Indian Ocean Dipole) | BoM | `http://www.bom.gov.au/climate/enso/indices.shtml` | Hebdo | HTML | Backlog |
| MJO phase + amplitude | NOAA CPC | `https://www.cpc.ncep.noaa.gov/products/precip/CWlink/MJO/mjo.shtml` | Quotidien | TXT | Backlog |
| WAM onset/retreat dates | AGRHYMET | (regional) | Saisonnier | — | Backlog |
| MEI v2 (Multivariate ENSO Index) | NOAA PSL | `https://psl.noaa.gov/enso/mei/data/meiv2.data` | Bi-mensuel | TXT | Backlog |
| CHIRPS rainfall anomaly West Africa | UCSB CHC | `https://data.chc.ucsb.edu/products/CHIRPS-2.0/africa_dekad/` | Décadaire (10j) | NetCDF | Backlog |

Le MVP couvre 6 sources : ONI, Niño 3.4 SST, ENSO Discussion NOAA, ENSO probabilités IRI, Atlantic Niño SST, Open-Meteo seasonal forecast. Le backlog reste documenté pour ajouts incrémentaux ultérieurs sans refonte de l'agent.

---

## 5. Architecture cible

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Cloud Scheduler (45 18 * * 1-5 UTC)                                     │
│   └─→ cc-macro-climate-agent (Cloud Run Job)                            │
│         ├─→ fetchers (NOAA, IRI, Open-Meteo)                            │
│         ├─→ synthesizer (gpt-4.1, 1 appel, JSON strict)                 │
│         └─→ db_writer (upsert pl_climate_signal)                        │
└─────────────────────────────────────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ pl_climate_signal (PostgreSQL)                                          │
│   inputs bruts par signal_type, source, horizon_months                  │
│   + llm_summary_fr consolidé                                            │
└─────────────────────────────────────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ cc-daily-analysis (existant, modifié)                                   │
│   db_reader.read_climate_signals(date) ──┐                              │
│                                           ▼                              │
│   prompts.py (Call #1, bloc CLIMATE_MACRO ajouté)                       │
│     → LLM produit macroeco_bonus (canal existant)                       │
│     → écrit pl_indicator_daily.macroeco_bonus + .eco                    │
└─────────────────────────────────────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Power formula composite (inchangée cette itération)                     │
│   macroeco est déjà 1 des 8 inputs, mieux nourri = meilleur signal      │
└─────────────────────────────────────────────────────────────────────────┘
```

Dual canal de validation : signal **scientifique** via `cc-macro-climate-agent` + signal **presse** via `cc-press-review-agent` augmenté. Le LLM Call #1 voit les deux et peut détecter les divergences.

---

## 6. Schéma DB

### Nouvelle table `pl_climate_signal`

Migration Alembic dans `backend/alembic/versions/<rev>_add_pl_climate_signal.py` :

```sql
CREATE TABLE pl_climate_signal (
    id BIGSERIAL PRIMARY KEY,
    date DATE NOT NULL,
    signal_type VARCHAR(50) NOT NULL,
        -- 'oni' | 'nino34_sst' | 'atlantic_nino_sst' |
        -- 'enso_phase' | 'enso_forecast_probs' | 'seasonal_precip_forecast'
    source VARCHAR(50) NOT NULL,
        -- 'noaa_cpc' | 'noaa_oisst' | 'iri' | 'open_meteo'
    numeric_value DOUBLE PRECISION,
        -- anomalie SST (°C), valeur ONI, etc. NULL si signal qualitatif
    phase VARCHAR(30),
        -- 'el_nino_strong' | 'el_nino_moderate' | 'el_nino_weak' |
        -- 'neutral' | 'la_nina_weak' | 'la_nina_moderate' | 'la_nina_strong'
    probability_payload JSONB,
        -- {'el_nino': 0.65, 'neutral': 0.30, 'la_nina': 0.05}
    horizon_months INT,
        -- 0 = nowcast, 3/6/9 = forecast horizons
    raw_summary TEXT,
        -- texte source (extrait HTML/PDF) pour traçabilité et reproductibilité
    llm_summary_fr TEXT,
        -- synthèse FR LLM-générée pour daily-analysis (uniquement sur 1 ligne par date)
    metadata JSONB,
        -- {url, retrieved_at, parser_version}
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE (date, signal_type, source, horizon_months)
);

CREATE INDEX ix_pl_climate_signal_date ON pl_climate_signal (date DESC);
CREATE INDEX ix_pl_climate_signal_type ON pl_climate_signal (signal_type, date DESC);
```

Modèle SQLAlchemy `PlClimateSignal` à ajouter dans `backend/app/models/pipeline.py` à côté de `PlWeatherObservation`. Pattern strictement identique au modèle existant (Mapped, server_default, etc.).

**Idempotence** : la contrainte UNIQUE permet un `INSERT ... ON CONFLICT (...) DO UPDATE`. Une source mensuelle re-vérifiée chaque jour ne crée pas de doublons mais peut rafraîchir `raw_summary` / `metadata`.

**Convention `llm_summary_fr`** : NULL sur les lignes "input bruts", rempli uniquement sur la ligne consolidée du jour (`signal_type='enso_phase'`, `source='noaa_cpc'`, `horizon_months=0`) → c'est la ligne lue par `daily-analysis`.

---

## 7. Agent : `backend/scripts/macro_climate_agent/`

### Arborescence

```
backend/scripts/macro_climate_agent/
├── __init__.py
├── main.py                        # entry point poetry script
├── config.py                      # sources URLs, prompt, settings Pydantic
├── fetchers/
│   ├── __init__.py
│   ├── noaa_oisst.py              # Niño 3.4 + Atlantic Niño SST anomalies (text file)
│   ├── noaa_cpc.py                # ONI tabulaire + ENSO Diagnostic Discussion HTML
│   ├── iri.py                     # IRI ENSO Quick Look HTML (probabilités)
│   └── open_meteo_climate.py      # Seasonal forecast 6 mois sur belt cocoa
├── synthesizer.py                 # 1 appel gpt-4.1 → JSON {phase, confidence, llm_summary_fr}
├── db_writer.py                   # upsert pl_climate_signal
└── tests/
    ├── fixtures/                  # snapshots HTML/text capturés (NOAA, IRI)
    ├── test_fetchers.py
    ├── test_synthesizer.py
    └── test_db_writer.py
```

### Patterns à réutiliser

- **Pydantic settings** : pattern de `backend/scripts/meteo_agent/config.py:1-50` pour les URLs, secrets, modèle LLM
- **OpenAI client + secrets** : pattern de `backend/scripts/meteo_agent/main.py` (variables d'env, gestion d'erreur)
- **Async session SQLAlchemy** : `backend/app/core/database.py` (sync engine pour les agents Cloud Run, comme les autres)
- **httpx async** : pattern de `backend/scripts/cftc_scraper/` et `backend/scripts/ice_stocks_scraper/` (toutes les sources NOAA/IRI/Open-Meteo sont des pages statiques ou fichiers texte → pas besoin de Playwright, image Docker plus légère possible mais on garde `Dockerfile.jobs` pour homogénéité)

### Schedule

Cloud Scheduler `45 18 * * 1-5` (18h45 UTC weekdays). Précède `barchart` (19h00) et `press_review` (19h05). Les sources NOAA / IRI publient en heure US, donc 18h45 UTC = ~14h45 EST = couvre les publications du matin US.

### Idempotence et fail-loud

- Upsert `ON CONFLICT (date, signal_type, source, horizon_months) DO UPDATE` → re-runs safe
- Sources mensuelles re-vérifiées quotidiennement, écriture conditionnée à un changement de `metadata.retrieved_at` ou `raw_summary` hash
- Chaque fetcher dans son try/except indépendant : un fetcher en panne n'empêche pas les autres d'écrire
- Fail-loud : tout fetcher en échec log ERROR + Sentry + le code de sortie agent reflète l'échec (non-zéro si ≥ 1 fetcher down) → relance manuelle requise (cf. `.claude/rules/pipeline-error-handling.md`)
- **Pas d'auto-retry, pas de fallback silencieux** entre sources

---

## 8. Hook dans `daily-analysis`

### Lecture des signaux climat

Ajouter à `backend/scripts/daily_analysis/db_reader.py` :

```python
def read_climate_signals(date: date, lookback_days: int = 30) -> dict:
    """
    Returns latest climate signals + 30-day evolution for daily-analysis Call #1.

    Output structure:
        {
          "current": {
            "phase": "el_nino_moderate",
            "confidence": 0.78,
            "oni": 1.2,
            "nino34_sst_anomaly": 1.4,
            "atlantic_nino_sst_anomaly": -0.3,
            "llm_summary_fr": "..."
          },
          "forecast": {
            "h3_probs": {"el_nino": 0.72, "neutral": 0.25, "la_nina": 0.03},
            "h6_probs": {...},
            "h9_probs": {...},
            "seasonal_precip_anomaly_belt_pct": -12.5
          },
          "evolution_30d": {
            "oni_change": +0.4,
            "nino34_change": +0.5,
            "phase_transition": "neutral → el_nino_weak → el_nino_moderate"
          }
        }
    """
```

### Modification du prompt Call #1

Dans `backend/scripts/daily_analysis/prompts.py:17-102`, ajouter un bloc structuré `CLIMATE_MACRO` en parallèle de `MACRONEWS` / `METEOTODAY` / `METEONEWS` :

```text
## CLIMATE_MACRO (signaux scientifiques officiels NOAA / IRI / Open-Meteo)

Phase ENSO actuelle : {phase} (confidence: {confidence})
ONI : {oni} | Niño 3.4 SST anomaly : {nino34} °C | Atlantic Niño SST anomaly : {atl_nino} °C
Forecast 3 mois : {h3_probs}
Forecast 6 mois : {h6_probs}
Précip seasonal forecast belt cocoa (6 mois) : {seasonal_precip_anomaly_pct} %
Évolution 30j : {evolution_30d}
Synthèse : {llm_summary_fr}

INSTRUCTIONS :
- Si phase ENSO active confirmée par sources scientifiques (NOAA / IRI), pas seulement
  par la presse (MACRONEWS), ET impact attendu négatif sur supply West Africa
  → augmenter macroeco_bonus (range typique +0.04 à +0.08 si El Niño confirmé fort).
- Distinguer signal scientifique (NOAA/IRI/BoM) de signal presse (déjà capté dans
  MACRONEWS) → éviter double comptage.
- Si signal scientifique CONTREDIT le signal presse → mentionner explicitement le doute
  dans `eco` et appliquer un macroeco_bonus modéré.
- Toujours mentionner explicitement le régime climatique dans `eco`.
```

**Pas de changement de schema** sur `pl_indicator_daily` à ce stade. Le `macroeco_bonus` reste l'unique canal d'injection vers le composite. La nouveauté : le LLM dispose d'un input scientifique structuré en plus du flux presse.

### Augmentation du press review (complément low-cost)

`backend/scripts/press_review_agent/config.py:85-192` — ajouter ~5 queries Google News RSS dédiées :

```python
{
  "name": "Climat ENSO",
  "queries": [
    "El Niño cocoa", "La Niña cocoa", "ENSO West Africa rainfall",
    "BoM ENSO outlook", "NOAA ENSO advisory"
  ]
}
```

`backend/scripts/press_review_agent/config.py:216-290` (system prompt) — ajouter une instruction :

> Toute mention d'ENSO / El Niño / La Niña / IOD / MJO = signal structurel à fort impact à reporter explicitement dans la synthèse `impact_synthesis`. Préciser source (OMM, NOAA, IRI, BoM, presse spécialisée) et horizon (mois).

Bénéfice : double canal indépendant. Le LLM Call #1 de `daily-analysis` peut croiser scientifique vs presse pour valider les signaux.

---

## 9. Opérationnel

### 9.1 Schedule (mise à jour pipeline complète)

```
18:45 UTC  cc-macro-climate-agent   → pl_climate_signal                (NEW)
19:00 UTC  cc-barchart-scraper      → pl_contract_data_daily (OHLCV+IV)
19:00 UTC  cc-meteo-agent           → pl_weather_observation
19:05 UTC  cc-ice-stocks-scraper    → pl_contract_data_daily (STOCK US)
19:05 UTC  cc-cftc-scraper          → pl_contract_data_daily (COM NET US)
19:05 UTC  cc-press-review-agent    → pl_fundamental_article            (PROMPT MODIFIÉ)
19:15 UTC  cc-compute-indicators    → pl_derived_indicators + pl_indicator_daily
19:20 UTC  cc-daily-analysis        → pl_indicator_daily                (PROMPT MODIFIÉ)
19:30 UTC  cc-compass-brief         → Google Drive
```

### 9.2 Déploiement

- `backend/Dockerfile.jobs` réutilisé (pas de Playwright nécessaire mais image partagée pour homogénéité)
- `infra/terraform/cloud_run_jobs.tf` — ajouter le job `cc-macro-climate-agent`
- `infra/terraform/cloud_scheduler.tf` — ajouter le scheduler associé
- `.github/workflows/deploy.yml` — ajouter `cc-macro-climate-agent` à la matrice de déploiement
- Service account : réutiliser celui des autres jobs (`cc-jobs-runner@cacaooo.iam`)
- Secrets : `OPENAI_API_KEY` (déjà présent), pas de nouveau secret requis
- Variables d'env : `MACRO_CLIMATE_LLM_MODEL=gpt-4.1` (configurable via GitHub Vars)

### 9.3 Monitoring

- Alerting Cloud Logging : alerte si > 1 fetcher fail sur 3 runs consécutifs (config dans `infra/terraform/monitoring.tf`)
- Sentry : tags `agent=macro_climate_agent`, `fetcher=<name>` pour filtrage rapide
- Dashboard interne (optionnel, hors MVP) : Looker Studio sur `pl_climate_signal` montrant l'évolution de Niño 3.4 SST + ONI + phase

### 9.4 Coût estimé

- Cloud Run Job : ~30 secondes d'exécution / jour, ~5 Mo RAM peak → coût ~négligeable (<$1/mois)
- LLM (gpt-4.1) : 1 appel / jour, ~3-5K tokens input + ~500 output → ~$0.10/jour, ~$25/mois
- Pas de coût de données externes (NOAA, IRI, Open-Meteo, BoM = gratuit, pas d'auth)

---

## 10. Roadmap (hors scope MVP)

### 10.1 Autres familles macro

Suivre le même pattern pour :

1. **Disease & pest signal** (`pl_disease_signal` + `cc-disease-monitor-agent`)
   - Sources : COCOBOD bulletins, ICCO Quarterly Bulletin, dérivé proxy météo (humidité > 85% + temp 25-30°C → black pod risk index)
   - Pas d'API publique idéale → mix scraping bulletins + dérivation depuis `pl_weather_observation`

2. **Producer policy signal** (`pl_policy_signal` + `cc-policy-watch-agent`)
   - Sources : sites officiels CCC (Côte d'Ivoire) + COCOBOD (Ghana) + EU EUDR registry + presse spécialisée
   - Très LLM-driven : extraction d'événements (hausse farmgate, nouvelle taxe, deadline EUDR)
   - Score qualitatif puis normalisation -1 à +1 par LLM

### 10.2 Intégration quantitative dans la power formula (Option 3)

Pré-requis : 3-6 mois d'historique `pl_climate_signal` accumulé.

1. Backtest corrélation Niño 3.4 / ONI vs retours cocoa (lag 0, 30j, 90j, 180j)
2. Sélectionner 1-2 signaux les plus prédictifs
3. Créer `app/engine/indicators/climate_macro.py` lisant `pl_climate_signal` → injection dans `pl_derived_indicators`
4. Ajouter au registre `app/engine/indicators/__init__.py:16-31`
5. Modifier `app/engine/composite.py` pour ajouter un 9e input `climate_macro` à la power formula
6. Nouvelle algo version `v1.0.2` dans `pl_algorithm_config` avec `climate_coeff`, `climate_exp`. Coexiste avec v1.0.1 (default), activable par contrat
7. `pl_signal_component` recevra une nouvelle ligne `indicator_name='climate_macro'` (pas de migration de schéma — la table accepte n'importe quel `indicator_name`)
8. Recompute global : `gcloud run jobs execute cc-compute-indicators --args="compute-indicators,--all-contracts,--all-versions,--full"`

### 10.3 UI

Options à arbitrer plus tard :
- Badge "Régime climatique : El Niño faible/modéré/fort" dans le `WeatherUpdateCard`
- Carte dédiée "Climat global" dans le dashboard
- Surcouche sur le `PriceChart` (overlay phase ENSO sur la timeline)

---

## 11. Critères d'acceptance

### MVP shipped quand :

- [ ] Migration `pl_climate_signal` appliquée en local et en GCP prod
- [ ] `cc-macro-climate-agent` déployé en Cloud Run Job, exécuté avec succès en prod ≥ 5 jours consécutifs
- [ ] `pl_climate_signal` contient ≥ 6 lignes par jour (1 par signal_type principal)
- [ ] Synthèse `llm_summary_fr` de la ligne consolidée du jour est présente et cohérente
- [ ] `daily-analysis` Call #1 lit le signal climat et le mentionne dans `eco` les jours où ENSO est non-neutre
- [ ] Le `macroeco_bonus` est sensiblement modifié (différence > 0.02 en valeur absolue) entre la version sans et avec la lecture climat sur ≥ 1 cas test backtest
- [ ] Les 5 queries RSS ENSO sont actives dans le press_review et capturent ≥ 1 article/semaine
- [ ] Document `docs/data-sources/macro-factors-catalog.md` mergé (catalogue des 6 familles)
- [ ] Tests unitaires fetchers + synthesizer + db_writer passent (coverage ≥ 80% pour le nouvel agent)
- [ ] Section "AI Agents" du `CLAUDE.md` documente le 5e agent

### Rejet si :

- Auto-retry / fallback silencieux ajouté à l'agent (viole `.claude/rules/pipeline-error-handling.md`)
- Schema de `pl_indicator_daily` modifié (hors scope, pour Phase 3)
- UI ajoutée (hors scope MVP)
- Codes contrats hardcodés (viole feedback memory `feedback_no_hardcoded_contracts.md`)

---

## 12. Plan de vérification

### 12.1 Tests unitaires

- `tests/test_fetchers.py` : un test par fetcher avec fixtures HTML/text capturées (snapshots NOAA, IRI, Open-Meteo)
- `tests/test_synthesizer.py` : mock OpenAI, valider que le JSON output respecte le schéma (phase enum, confidence float, llm_summary_fr str non vide)
- `tests/test_db_writer.py` : test idempotence upsert sur `(date, signal_type, source, horizon_months)` — re-run ne duplique pas, met à jour `metadata.retrieved_at`

### 12.2 Test d'intégration local

```bash
# 0. Migration
cd backend && poetry run alembic upgrade head

# 1. Dry-run de l'agent
poetry run macro-climate-agent --dry-run --verbose

# 2. Run effectif sur DB locale
poetry run macro-climate-agent --verbose

# 3. Vérifier ingestion
psql -h localhost -p 5433 -U postgres -d commodities_compass \
  -c "SELECT date, signal_type, source, phase, numeric_value, horizon_months
      FROM pl_climate_signal ORDER BY date DESC, signal_type LIMIT 30;"

# 4. Vérifier synthèse FR consolidée
psql -h localhost -p 5433 -U postgres -d commodities_compass \
  -c "SELECT date, llm_summary_fr FROM pl_climate_signal
      WHERE signal_type='enso_phase' AND source='noaa_cpc'
      ORDER BY date DESC LIMIT 3;"

# 5. Lancer daily-analysis avec le nouvel input
poetry run daily-analysis --dry-run

# 6. Vérifier que `eco` mentionne le régime climatique
```

### 12.3 Validation GCP (post-deploy)

- Trigger manuel : `gcloud run jobs execute cc-macro-climate-agent --region=europe-west9 --project=cacaooo`
- Vérifier rows écrites via bastion + psql : `SELECT * FROM pl_climate_signal ORDER BY date DESC LIMIT 20;`
- Re-run `cc-daily-analysis` et vérifier que la conclusion mentionne le climat global les jours pertinents
- Cloud Logging filter : `resource.type="cloud_run_job" AND resource.labels.job_name="cc-macro-climate-agent" AND severity>=ERROR`

### 12.4 Validation backtest historique (optionnel)

Sur un échantillon d'épisodes ENSO connus (El Niño 2023-24, La Niña 2020-22), backfiller `pl_climate_signal` à partir des archives NOAA et re-runner `daily-analysis` sur les dates correspondantes. Comparer `macroeco_bonus` avant/après et `eco` rationnel.

---

## 13. Open questions / décisions à prendre

| # | Question | Owner | Statut |
|---|---|---|---|
| 1 | Le seuil de confidence à partir duquel on considère une phase ENSO "active" : 0.6 ? 0.7 ? À calibrer | Tech lead | Open |
| 2 | Faut-il un Google News query supplémentaire pour "Atlantic Niño" ? Couverture presse moins claire que ENSO | Product | Open |
| 3 | Le synthesizer LLM doit-il avoir accès aux 30 derniers jours de signaux pour produire l'évolution, ou au snapshot du jour seulement ? | Tech lead | Open (préférence : 30 jours, plus de contexte pour qualifier l'évolution) |
| 4 | Une fois la Phase 3 activée, faut-il garder le `macroeco_bonus` en plus du `climate_macro` quantitatif, ou le `macroeco_bonus` ne couvre que les autres familles macro ? | Tech lead | Différé (Phase 3) |

---

## Annexe A — Fichiers à créer / modifier

### Créer

```
docs/user-stories/macro-climate-signal.md           (ce document, copié à la cible)
docs/data-sources/macro-factors-catalog.md          (catalogue des 6 familles, extrait section 3+4)
backend/alembic/versions/<rev>_add_pl_climate_signal.py
backend/scripts/macro_climate_agent/__init__.py
backend/scripts/macro_climate_agent/main.py
backend/scripts/macro_climate_agent/config.py
backend/scripts/macro_climate_agent/synthesizer.py
backend/scripts/macro_climate_agent/db_writer.py
backend/scripts/macro_climate_agent/fetchers/__init__.py
backend/scripts/macro_climate_agent/fetchers/noaa_oisst.py
backend/scripts/macro_climate_agent/fetchers/noaa_cpc.py
backend/scripts/macro_climate_agent/fetchers/iri.py
backend/scripts/macro_climate_agent/fetchers/open_meteo_climate.py
backend/scripts/macro_climate_agent/tests/test_fetchers.py
backend/scripts/macro_climate_agent/tests/test_synthesizer.py
backend/scripts/macro_climate_agent/tests/test_db_writer.py
backend/scripts/macro_climate_agent/tests/fixtures/  (HTML/text snapshots)
```

### Modifier

```
backend/app/models/pipeline.py                       (ajouter PlClimateSignal)
backend/pyproject.toml                               (poetry script macro-climate-agent)
backend/scripts/daily_analysis/db_reader.py          (read_climate_signals)
backend/scripts/daily_analysis/prompts.py            (Call #1 : bloc CLIMATE_MACRO)
backend/scripts/press_review_agent/config.py         (5 queries RSS + instruction prompt)
infra/terraform/cloud_run_jobs.tf                    (job cc-macro-climate-agent)
infra/terraform/cloud_scheduler.tf                   (scheduler 18:45 UTC)
infra/terraform/monitoring.tf                        (alerte fail consécutifs)
.github/workflows/deploy.yml                         (matrice de déploiement)
CLAUDE.md                                            (section AI Agents : 5e agent)
```

### Ne pas toucher (hors scope MVP)

```
backend/app/engine/composite.py                      (Phase 3 différée)
backend/app/engine/indicators/                       (Phase 3 différée)
pl_algorithm_config (DB)                             (Phase 3 différée)
frontend/src/components/dashboard/WeatherUpdateCard.tsx  (UI différée)
```

---

## Annexe B — Références externes

- NOAA Climate Prediction Center : <https://www.cpc.ncep.noaa.gov/>
- NOAA OISST v2.1 : <https://www.ncei.noaa.gov/products/optimum-interpolation-sst>
- IRI ENSO Forecast : <https://iri.columbia.edu/our-expertise/climate/forecasts/enso/>
- BoM ENSO Wrap-Up : <http://www.bom.gov.au/climate/enso/>
- Open-Meteo Climate API : <https://open-meteo.com/en/docs/climate-api>
- WMO Global Producer Status Bulletins : <https://wmo.int/>
- Cocoa & ENSO research : voir IPCC AR6 chap. cocoa (sensitivity studies) et études ICCO sur impact climatique sur West Africa supply

---

## Annexe C — Références internes (codebase)

- Pattern agent existant : `backend/scripts/meteo_agent/` (le plus proche structurellement)
- Pattern scraping HTTP simple : `backend/scripts/cftc_scraper/`, `backend/scripts/ice_stocks_scraper/`
- Pattern OpenAI synthesizer : `backend/scripts/press_review_agent/llm_provider.py`
- Pattern DB writer + idempotence : `backend/app/engine/db_writer.py`
- Modèle SQLAlchemy de référence : `backend/app/models/pipeline.py:274-288` (PlWeatherObservation)
- Daily analysis DB reader : `backend/scripts/daily_analysis/db_reader.py:255-290` (lecture meteonews actuelle)
- Daily analysis prompt Call #1 : `backend/scripts/daily_analysis/prompts.py:17-102`
- Press review config : `backend/scripts/press_review_agent/config.py:85-192` (RSS queries) et `:216-290` (system prompt)
- Composite formula : `backend/app/engine/composite.py:136-198`
- Règles projet pertinentes : `.claude/rules/pipeline-error-handling.md`, `.claude/rules/pipeline-continuity.md`, `.claude/rules/north-star-alignment.md`
