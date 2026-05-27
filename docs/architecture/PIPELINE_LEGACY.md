# Pipeline LEGACY — `cc-daily-analysis` + `cc-compass-brief`

> Architecture documentaire macro du pipeline historique de production de décisions de trading et du brief NotebookLM associé. Ce document décrit la **logique métier** et les **flux de données**, pas le code en détail. Pour le code, voir les fichiers référencés à la fin de chaque section.

> **Statut 2026-05-26** : pipeline OPÉRATIONNEL en parallèle de l'ensemble v1.0.0 (cf. [PIPELINE_ENSEMBLE.md](./PIPELINE_ENSEMBLE.md)). Continuera à tourner aussi longtemps que les utilisateurs en ont besoin et que la transition vers l'ensemble est sécurisée. Voir [docs/runbooks/brief-dual-track.md](../runbooks/brief-dual-track.md) pour le mode dual.

---

## 1 — Vue d'ensemble

### Question business à laquelle ce pipeline répond

> « Pour la prochaine session de trading du cocoa London, quelle est la **position recommandée** (OPEN / HEDGE / MONITOR), avec quel niveau de **confiance**, dans quelle **direction** anticipée du marché, et pourquoi ? »

### Stack et logique

- **Méthode** : LLM (gpt-4-turbo) prend la décision finale en deux appels successifs.
- **Engine déterministe** parallèle : un score composite calculé sur 6 z-scores rolling 252j × une power formula (`Σ coeff × sign(x) × |x|^exp`) produit un `final_indicator` et une `final_conclusion`. Le LLM voit ce score et peut le confirmer ou le nuancer.
- **Horizon décisionnel** : **T+1** — la décision est prise pour la session du lendemain, à réévaluer chaque jour.
- **Inputs** : 42 variables technicals (today + yesterday) + revue de presse + 100 jours d'historique météo + (optionnellement) les diagnostics de l'ensemble si présents.
- **Output** : 6 champs dans `pl_indicator_daily` row `algorithm_version_id = legacy` : `decision`, `confidence`, `direction`, `conclusion`, `eco`, `macroeco_bonus`.

### Forces et limites

**Forces** :
- Narrative riche, ton humain, bonne « sensibilité » macro
- 18 mois de production stable, comportement bien compris
- Robuste sur les marchés normaux : capture le contexte qualitatif

**Limites** :
- 2 appels LLM ≈ $0.50/jour, latence ~30s, dépendance OpenAI uptime
- Pas de mesure quantitative de fitness (impossible de dire « ce LLM a 78% d'accuracy sur 30 jours »)
- Le LLM peut diverger de l'engine déterministe (parfois utilement, parfois pas)
- Horizon T+1 force une réévaluation quotidienne — pas adapté aux biais multi-jours

---

## 2 — Flux de données J-1 → J → Brief

### Diagramme global

```
┌─────────────────────────────────────────────────────────────────┐
│                       PHASE A — Market close (T)                │
│                       Weekdays only, 19:00-19:15 UTC            │
└─────────────────────────────────────────────────────────────────┘
   ▾
   ├ 18:30  cc-fx-scraper                  → pl_external_indicator (FX)
   ├ 19:00  cc-barchart-scraper            → pl_contract_data_daily (OHLCV+IV)
   ├ 19:05  cc-ice-stocks-scraper          → pl_contract_data_daily (STOCK US)
   ├ 19:05  cc-cftc-scraper                → pl_contract_data_daily (COM NET US)
   ├ 19:10  cc-barchart-stocks-eu-scraper  → pl_contract_data_daily (stock_eu)
   └ 19:15  cc-compute-indicators          → pl_derived_indicators (27 techs)
                                          + pl_indicator_daily (z-scores numerics)
                                                     ▾
┌─────────────────────────────────────────────────────────────────┐
│                  PHASE B — Eve of next session (T+next)         │
│                  Daily cron + is_eve_of_trading_day() gate      │
└─────────────────────────────────────────────────────────────────┘
   ▾
   ├ 19:00  cc-meteo-agent      → pl_weather_observation
   ├ 19:05  cc-press-review     → pl_fundamental_article (+ pl_article_segment)
   ├ 19:20  cc-daily-analysis   ▼
   │       LLM Call #1 (macro/weather)
   │         Inputs : MACRONEWS (press summary), METEOTODAY,
   │                  METEONEWS (100j d'historique meteo)
   │         Output : {macroeco_bonus ∈ [-0.10,+0.10], eco ≤30 mots}
   │       LLM Call #2 (decision)
   │         Inputs : 42 technicals (today+yesterday),
   │                  final_indicator (engine score),
   │                  (optionnel: ensemble decision wrapped)
   │         Output : {decision, confiance 1-5, direction, conclusion}
   │       Engine déterministe (parallèle)
   │         Output : final_indicator (numeric), final_conclusion (label)
   │       Writes pl_indicator_daily row LEGACY :
   │         eco, macroeco_bonus, macroeco_score, final_indicator,
   │         decision, confidence, direction, conclusion
   │
   └ 19:30  cc-compass-brief    ▼
           Lit pl_indicator_daily WHERE algorithm_version.is_active=TRUE
           Lit pl_contract_data_daily last 2 dates (yesterday + today)
           Lit pl_fundamental_article (latest is_active row)
           Lit pl_weather_observation (latest)
           Génère YYYYMMDD-CompassBrief.txt
           Upload sur Google Drive folder cocoa-briefs
                                                     ▾
                                  NotebookLM ingestion (overnight)
                                                     ▾
                          YYYYMMDD-CompassAudio.{wav|m4a|mp4} sur Drive
                                                     ▾
                          Frontend dashboard fetch /v1/dashboard/audio
                          Audio player en haut du dashboard
```

### Granularité de la décision

- **1 décision par session** (1 par jour de trading), pour le contrat actif (à ce jour : CAK26)
- Le contrat actif est résolu dynamiquement depuis `ref_contract.is_active=TRUE`
- Lors d'un roll de contrat, transition managée via `roll-contract` CLI + fallback cross-contract dans `daily-analysis`

---

## 3 — Détail de chaque étape

### 3.1 `cc-compute-indicators` (engine déterministe)

> Code : [backend/app/engine/](../../backend/app/engine/) (orchestrateur dans `pipeline.py`, runner dans `runner.py`)

#### Inputs
- `pl_contract_data_daily` pour le contrat actif sur 252+ jours (lookback rolling)
- `pl_algorithm_config` pour les paramètres de la version active

#### Logique en 3 étapes

**Step 1 — Indicators dérivés (27 colonnes)**
- Pivots (R3, R2, R1, S1, S2, S3, pivot)
- EMA (12, 26), MACD + signal
- RSI Wilder 14d
- Stochastic %K 14, %D
- ATR Wilder 14d
- Bollinger Bands (upper, lower, width)
- Ratios (close/pivot, volume/oi)
- Daily return

**Step 2 — Smoothing (5j SMA)** sur les scores bruts

**Step 3 — Normalisation rolling 252j z-score**
- 6 colonnes z-score : `rsi_norm`, `macd_norm`, `stoch_k_norm`, `atr_norm`, `close_pivot_norm`, `vol_oi_norm`
- Fenêtre glissante 252 jours (1 année trading), évite le look-ahead bias des full-history z-scores du legacy Google Sheets

**Step 4 — Composite via Power Formula**
- `final_indicator = k + Σ(coeff_i × sign(x_i) × |x_i|^exp_i)`
- Coefficients + exponents stockés dans `pl_algorithm_config` (config-as-data)
- Version v1.0.1 = version active aujourd'hui pour legacy

**Step 5 — Decision label**
- Seuils dans `pl_algorithm_config` :
  - `final_indicator > seuil_open` → OPEN
  - `final_indicator < seuil_hedge` → HEDGE
  - Sinon → MONITOR

#### Outputs
- `pl_derived_indicators` (1 row par date × contract)
- `pl_indicator_daily` (1 row par date × contract × algorithm_version_id) — uniquement les colonnes numerics, pas encore les LLM fields

#### Note importante
L'engine est appelé pour TOUTES les algorithm versions enabled (`compute_enabled=TRUE`). Aujourd'hui : version `legacy` v1.0.1 et version `ensemble_v1_softgate_wrapper` v1.0.0. L'engine remplit donc 2 rows par date.

### 3.2 `cc-daily-analysis` — LLM Call #1 (macro/weather analysis)

> Code : [backend/scripts/daily_analysis/db_analysis_engine.py](../../backend/scripts/daily_analysis/db_analysis_engine.py) + [prompts.py](../../backend/scripts/daily_analysis/prompts.py)

#### Inputs construits par `db_reader.py`
- **MACRONEWS** : `pl_fundamental_article.summary + impact_synthesis` (latest is_active row, fallback à `market_research`)
- **METEOTODAY** : `pl_weather_observation.summary + impact_assessment` (latest)
- **METEONEWS** : 100 derniers résumés meteo formatés `MM/YYYY-{summary}`

#### Prompt structure (français)
- System : « Tu es un analyste cocoa. Tu lis macro + météo et produit un score d'impact... »
- User : injection des 3 variables ci-dessus + instructions JSON strict

#### Output JSON
```json
{
  "date": "JJ/MM/AAAA",
  "macroeco_bonus": 0.04,   // ∈ [-0.10, +0.10]
  "eco": "Ghana production solide, mais Côte d'Ivoire en stress hydrique."  // ≤30 mots
}
```

#### Modèle et coût
- `gpt-4-turbo`, temperature 1.0, max_tokens 2048
- ~3000 tokens input + ~150 output ≈ $0.05 par call

#### Sémantique de `macroeco_bonus`
- Score qui s'ajoute au `final_indicator` calculé par l'engine
- Permet au LLM d'incliner légèrement la décision en faveur du macro
- Range volontairement borné `[-0.10, +0.10]` pour empêcher le LLM de prendre le contrôle total

### 3.3 `cc-daily-analysis` — Engine score composition

Une fois Call #1 fait, l'engine recompose le score :

```
macroeco_score   = 1.0 + macroeco_bonus    # ∈ [0.90, 1.10]
final_indicator  = compute_score(z-scores) + macroeco_bonus_contribution
final_conclusion = compute_decision(final_indicator)   # OPEN / HEDGE / MONITOR
```

C'est ce `final_conclusion` engine qui est ENSUITE passé en input au Call #2 LLM — qui peut le confirmer ou diverger.

### 3.4 `cc-daily-analysis` — LLM Call #2 (decision)

#### Inputs
- 42 variables technicals (today + yesterday)
- `final_indicator` numeric + `final_conclusion` label de l'engine
- **Optionnellement** : si une row existe dans `pl_orchestrator_decision` pour cette date, les diagnostics ensemble sont aussi injectés (auto-alignement, cf. db_analysis_engine.py:187-196)

#### Prompt structure
Deux variantes :
- `build_call2_prompt()` : legacy pure (87 lignes)
- `build_call2_prompt_ensemble()` : injecte les diagnostics ensemble + force le LLM à mirror la `decision_wrapped`

#### Output JSON
```json
{
  "decision": "OPEN",                       // OPEN | HEDGE | MONITOR
  "confiance": 4,                            // int 1-5
  "direction": "HAUSSIERE",                  // HAUSSIERE | BAISSIERE | NEUTRE
  "conclusion": "Le marché reste tendu...\nÀ SURVEILLER : ...\n..."  // texte avec 3 'À SURVEILLER'
}
```

#### Modèle et coût
- `gpt-4-turbo`, temperature 0.7, max_tokens 2048
- ~4000 tokens input + ~500 output ≈ $0.08 par call

### 3.5 `cc-daily-analysis` — Write to DB

```sql
UPDATE pl_indicator_daily
SET
  decision = :decision,          -- depuis Call #2 (OU decision_wrapped si ensemble aligné)
  confidence = :confiance,        -- depuis Call #2 (1-5)
  direction = :direction,         -- depuis Call #2
  conclusion = :conclusion,       -- depuis Call #2 (texte avec 3 alertes)
  eco = :eco,                     -- depuis Call #1
  macroeco_bonus = :bonus,        -- depuis Call #1
  macroeco_score = 1.0 + :bonus,
  final_indicator = :final_score  -- depuis engine
WHERE date = :date
  AND contract_id = :contract
  AND algorithm_version_id = :algo_id;  -- ← scope au legacy ou à l'ensemble selon flag
```

#### Le flag `--algorithm-version legacy`
En prod, `cc-daily-analysis` est lancé avec `--algorithm-version legacy` (cf. `deploy.yml:211`). Cela force l'UPDATE sur la row legacy, **garantit qu'il ne touchera jamais la row ensemble**. C'est le mécanisme d'isolation du dual-track côté legacy.

#### Le pipeline legacy est aussi appelé pour la row ENSEMBLE (refactor 2026-05-27)
Depuis le refactor PR #17, le job `cc-ensemble-explainer` (19:25 UTC) invoque le MÊME `DBAnalysisEngine.run()` **sans pinner `--algorithm-version`** → l'auto-align (db_analysis_engine.py:187-200) détecte la row ensemble dans `pl_orchestrator_decision` et écrit la narrative legacy-style (mêmes prompts `CALL_1_PROMPT` + `CALL_2_PROMPT_ENSEMBLE`, même format de conclusion `> ... • ... > A SURVEILLER AUJOURD'HUI: ...`) sur la row ensemble. Le code legacy est donc utilisé par les 2 tracks : pinné sur legacy via deploy.yml (cc-daily-analysis), et auto-aligné sur ensemble via cc-ensemble-explainer. Voir [PIPELINE_ENSEMBLE.md §7](./PIPELINE_ENSEMBLE.md) pour le détail.

### 3.6 `cc-compass-brief` — Brief generator + Drive upload

> Code : [backend/scripts/compass_brief/](../../backend/scripts/compass_brief/) (main, db_reader, brief_generator, drive_uploader)

#### Lecture DB
- `pl_contract_data_daily` last 2 distinct dates (yesterday + today) pour le contrat actif
- `pl_derived_indicators` (left join) — pivots, EMA, Bollinger, etc.
- `pl_indicator_daily` (z-scores + LLM fields) JOIN sur `algorithm_version.is_active=TRUE` — c'est cette clause qui détermine quelle version est lue
- `pl_fundamental_article` (latest is_active row)
- `pl_weather_observation` (latest)

#### Structure du fichier .txt produit

```
======================================================================
COMMODITIES COMPASS — DAILY BRIEF
Date : 26 mai 2026
======================================================================

======================================================================
DONNÉES DU 22 mai 2026 (VEILLE)
======================================================================

SIGNAL DU JOUR : <conclusion text>
Décision : HEDGE | Confiance : 3/5 | Direction : BAISSIERE

--- DONNÉES TECHNIQUES ---
CLOSE : 4,650.00    HIGH : 4,720.00    LOW : 4,600.00
VOLUME : 12,345    OI : 56,789    IV : 0.5534
RSI 14D : 45.2    MACD : -12.3    Signal MACD : -8.7
%K : 32.5    %D : 35.1    ATR : 105.4
PIVOT : 4,650    S1 : 4,580    R1 : 4,720
EMA9 : 4,665    EMA21 : 4,680
Bollinger : [4,510 — 4,790]
STOCK US : 2,345,678    COM NET US : -1,234

--- SCORES INDICATEURS ---
RSI : -0.41    MACD : -1.02    Stochastic : -0.55
ATR : 0.31    Close/Pivot : -0.15    Volume/OI : 0.08
Indicateur agrégé : -0.78    Score Macroéco : 0.96

--- ANALYSE MACROÉCONOMIQUE ---
<eco text — 30 mots LLM>

--- RECOMMANDATIONS DU JOUR ---
<conclusion text avec 3 lignes À SURVEILLER>

--- PRESS REVIEW ---
<press_summary — pris du dernier pl_fundamental_article>

--- MÉTÉO ---
<meteo_summary>
Impact : <meteo_impact>

======================================================================
DONNÉES DU 23 mai 2026 (AUJOURD'HUI)
======================================================================
[même structure répétée pour today]
```

#### Sources de chaque champ

| Champ brief | Source DB | Producteur |
|---|---|---|
| Header date | Calculé depuis target_date | cc-compass-brief |
| SIGNAL DU JOUR | `pl_indicator_daily.conclusion` | LLM Call #2 |
| Décision/Confiance/Direction | `pl_indicator_daily.{decision, confidence, direction}` | LLM Call #2 |
| OHLCV | `pl_contract_data_daily` | cc-barchart-scraper |
| Pivots/EMA/MACD/RSI | `pl_derived_indicators` | cc-compute-indicators |
| IV | `pl_contract_data_daily.implied_volatility` | cc-barchart-scraper |
| STOCK US / COM NET US | `pl_contract_data_daily.{stock_us, com_net_us}` | cc-ice-stocks-scraper, cc-cftc-scraper |
| Scores indicateurs (z-scores) | `pl_indicator_daily.{rsi_score, macd_score, ...}` | cc-compute-indicators (numerics) |
| Indicateur agrégé | `pl_indicator_daily.final_indicator` | engine (cc-daily-analysis) |
| Score Macroéco | `pl_indicator_daily.macroeco_score` | LLM Call #1 |
| ANALYSE MACROÉCONOMIQUE | `pl_indicator_daily.eco` | LLM Call #1 |
| RECOMMANDATIONS | `pl_indicator_daily.conclusion` | LLM Call #2 |
| PRESS REVIEW | `pl_fundamental_article.summary` | cc-press-review-agent |
| MÉTÉO | `pl_weather_observation.{summary, impact_assessment}` | cc-meteo-agent |

#### Upload Drive
- Filename : `YYYYMMDD-CompassBrief.txt` où **`YYYYMMDD` = session_date** (= `data_date`, la dernière session boursière complète). Note : le contenu cite `target_date` (display_date) comme date de publication, mais le filename est ancré sur la session — c'est ce qui permet à `audio_service.py` de retrouver l'audio quand le dashboard navigue par display_date.
- Folder : `GOOGLE_DRIVE_BRIEFS_FOLDER_ID` (env var, partagé avec brief ensemble)
- Idempotent : re-upload du même filename remplace la version précédente

#### Audio NotebookLM
- Hors scope de ce pipeline — NotebookLM consomme le .txt et produit l'audio en parallèle (workflow Google Drive automatique configuré par l'utilisateur)
- Filename audio attendu : `YYYYMMDD-CompassAudio.{wav|m4a|mp4}` (même `YYYYMMDD` que le brief, hérité par NotebookLM)
- Le backend FastAPI `audio_service.py` cherche ces filenames sur Drive en utilisant le session_date résolu via `_parse_and_validate_date` (display_date → session_date lookup dans `pl_contract_data_daily`)

---

## 4 — Exemple complet de brief legacy (annoté)

Voici un brief réel raccourci, avec annotation de chaque section :

```text
======================================================================
COMMODITIES COMPASS — DAILY BRIEF
Date : 26 mai 2026
======================================================================
        ⇧ Le HEADER : target_date = mardi 26 mai 2026 (next session après lundi 25 mai férié au Royaume-Uni)

======================================================================
DONNÉES DU 22 mai 2026 (VEILLE)
======================================================================
        ⇧ Brief contient yesterday + today. Ici "VEILLE" = vendredi 22 mai (dernier trading day avant le weekend long)

SIGNAL DU JOUR : Position MONITOR sur la fenêtre 26-29 mai 2026. Le marché cocoa
montre une consolidation après la baisse de la semaine. RSI neutre (45), MACD en
divergence négative mais ATR contracté = volatilité modérée.
        ⇧ pl_indicator_daily.conclusion (LLM Call #2)

Décision : MONITOR | Confiance : 3/5 | Direction : NEUTRE
        ⇧ pl_indicator_daily.{decision, confidence, direction} (LLM Call #2)

--- DONNÉES TECHNIQUES ---
CLOSE : 4,650.00    HIGH : 4,720.00    LOW : 4,600.00
        ⇧ pl_contract_data_daily (cc-barchart-scraper)
VOLUME : 12,345    OI : 56,789    IV : 0.5534
RSI 14D : 45.2    MACD : -12.3    Signal MACD : -8.7
        ⇧ pl_derived_indicators (cc-compute-indicators)
[...]

--- ANALYSE MACROÉCONOMIQUE ---
ENSO neutre, pas de stress hydrique Côte d'Ivoire. Stock EU en hausse +2%
mais demande chocolat Q1 record.
        ⇧ pl_indicator_daily.eco (LLM Call #1) — analyse macro+meteo en ≤30 mots

--- RECOMMANDATIONS DU JOUR ---
Maintenir MONITOR. Pas de catalyseur fort dans les prochains 48h.
À SURVEILLER : Sortie de la fourchette 4,600-4,720 (signal de reprise de tendance).
À SURVEILLER : Données ECA Q1 attendues le 16 juillet — anticipation possible.
À SURVEILLER : Météo Côte d'Ivoire (sécheresse Daloa surveillée).
        ⇧ pl_indicator_daily.conclusion (LLM Call #2) — narratif + 3 alertes "À SURVEILLER"

--- PRESS REVIEW ---
Cocoa London consolide après la baisse hebdomadaire. Les opérateurs surveillent
les sorties de stocks EU et les arrivages CIV en faible accélération.
        ⇧ pl_fundamental_article.summary (cc-press-review-agent — LLM indépendant)

--- MÉTÉO ---
Daloa : Conditions favorables. Pluies modérées (12mm/24h).
Soubré : Sec mais stable. Pas d'alerte stress hydrique.
Impact : Neutre sur production court terme. Surveillance Q2.
        ⇧ pl_weather_observation.{summary, impact_assessment} (cc-meteo-agent — LLM indépendant)

[répétition de la même structure pour today (23 mai)]
======================================================================
```

---

## 5 — Forces et limites détaillées

### Forces

**Robustesse** : 18 mois de production stable. Le pipeline a survécu à plusieurs rolls de contrat (CAK26 → CAN26), à la migration Google Sheets → PostgreSQL, à la migration Railway → Cloud Run, et au déploiement des P3 scrapers fundamentaux. Pas de régression majeure.

**Narrative humaine** : le ton du brief NotebookLM est lisible, naturel. Les utilisateurs lui font confiance comme une « lecture matinale ».

**Sensibilité macro/météo** : LLM Call #1 capture le contexte que les indicateurs purs ne voient pas (e.g. « l'ECA publie Q1 demain, attente du marché »). C'est un avantage structurel sur l'ensemble v1.0.0 actuel.

**Modularité** : 2 calls LLM indépendants, séparés par concept (macro vs decision). On peut changer l'un sans l'autre.

### Limites

**Coût** : 2 calls gpt-4-turbo × 250 jours/an ≈ $30/an. Pas énorme mais non-négligeable.

**Latence** : ~30s par call × 2 = ~60s total. La fenêtre 19:18-19:30 UTC en prod est serrée.

**Dépendance OpenAI uptime** : si OpenAI a un outage entre 19:00 et 19:30 UTC, le brief du jour est perdu. Pas de retry (rule fail-loud).

**Pas de mesure quantitative de fitness** : impossible de répondre « le LLM a quelle accuracy sur 30 derniers jours ? ». Le suivi se fait à l'œil, par lecture qualitative.

**LLM peut hallucinations** : ~1 brief sur 50 contient un détail factuellement faux (chiffre mal lu, attribution incorrecte). Pas grave si l'utilisateur cross-check mais ça peut induire en erreur.

**Horizon T+1 forcé** : le LLM produit une décision pour « demain ». Si on veut un biais multi-jours (ce que l'ensemble fait), il faut un autre design.

**Couplage à `is_active=TRUE`** : le brief reader fait `JOIN pl_algorithm_version ON is_active=true` — fragile si 2 versions ont `is_active=TRUE` simultanément (tie-break non-déterministe).

---

## 6 — Liens cross-référence vers le code

| Section doc | Fichier code |
|---|---|
| 3.1 engine | [backend/app/engine/pipeline.py](../../backend/app/engine/pipeline.py), [runner.py](../../backend/app/engine/runner.py), [composite.py](../../backend/app/engine/composite.py) |
| 3.2-3.4 daily-analysis | [backend/scripts/daily_analysis/main.py](../../backend/scripts/daily_analysis/main.py), [db_analysis_engine.py](../../backend/scripts/daily_analysis/db_analysis_engine.py), [prompts.py](../../backend/scripts/daily_analysis/prompts.py), [db_reader.py](../../backend/scripts/daily_analysis/db_reader.py), [output_parser.py](../../backend/scripts/daily_analysis/output_parser.py) |
| 3.6 compass-brief | [backend/scripts/compass_brief/main.py](../../backend/scripts/compass_brief/main.py), [db_reader.py](../../backend/scripts/compass_brief/db_reader.py), [brief_generator.py](../../backend/scripts/compass_brief/brief_generator.py), [drive_uploader.py](../../backend/scripts/compass_brief/drive_uploader.py) |
| Frontend audio | [backend/app/services/audio_service.py](../../backend/app/services/audio_service.py), [backend/app/api/api_v1/endpoints/audio.py](../../backend/app/api/api_v1/endpoints/audio.py), [endpoints/dashboard.py](../../backend/app/api/api_v1/endpoints/dashboard.py) (`/audio` endpoint) |
| Schéma DB | [backend/app/models/pipeline.py](../../backend/app/models/pipeline.py) (`PlIndicatorDaily`, `PlContractDataDaily`, `PlDerivedIndicators`, `PlFundamentalArticle`, `PlWeatherObservation`) |

---

## 7 — Liens vers les autres docs architecture

- [PIPELINE_ENSEMBLE.md](./PIPELINE_ENSEMBLE.md) — le pipeline ensemble v1.0.0 qui tourne en parallèle aujourd'hui
- [JOBS_AND_SCRAPERS.md](./JOBS_AND_SCRAPERS.md) — catalogue exhaustif de tous les jobs/scrapers, anciens et nouveaux
- [docs/runbooks/brief-dual-track.md](../runbooks/brief-dual-track.md) — opérations du mode dual-track
- [docs/runbooks/pipeline-failure-recovery.md](../runbooks/pipeline-failure-recovery.md) — récupération en cas d'échec d'un job
