# 06 — Data ingérées non consommées par ensemble v1.0.0

Inventaire factuel des sources de données disponibles en DB prod mais **non lues** par `cc-ensemble-compute`. Représente le potentiel d'expérimentation pour v1.1.0+.

Tout ce qui est listé ici est **déjà ingéré, validé, idempotent, et avec backfill historique disponible**. Aucune nouvelle infra à construire — il s'agit "uniquement" pour R&D de tester si ces signaux ajoutent de la valeur au pipeline existant.

## Méthodologie

J'ai grepé `backend/scripts/ensemble_compute/db_loader.py` pour identifier exactement quelles tables/colonnes sont lues par l'ensemble. Le reste = "ingéré pour rien" en v1.0.0 (mais utile pour la suite ou pour le legacy).

Tables lues par ensemble v1.0.0 :
1. `v_contract_data_chained` (VIEW sur `pl_contract_data_daily`)
2. `pl_derived_indicators` (joined on date+contract)
3. `pl_orchestrator_decision` (recent trailing)
4. `pl_specialist_prediction` (recent trailing)
5. `pl_article_segment` (90d window)
6. `pl_model_artifact` (38 BYTEA artifacts loaded once)
7. `pl_algorithm_config` (cluster_mapping + Compass threshold)
8. `pl_algorithm_version` (version_id + training_month resolution)

Tout le reste = candidat pour R&D experiments.

## Tables/colonnes inutilisées

### 1. `pl_cot_eu_weekly` — **Priorité 1 R&D**

**Statut** : table créée (migration `g1b2c3d4e5f6`, 2026-05-20), backfillée 12 ans (607 rows), **non lue par ensemble**.

**Données disponibles** : ICE Europe COT weekly positioning, depuis 2014-10-03 :
- `prod_merc_long`, `prod_merc_short`, `prod_merc_net` (Producer/Merchant — hedgers)
- **`m_money_long`, `m_money_short`, `m_money_net` (Managed Money — le signal R&D)**
- `other_rept_long`, `other_rept_short` (Other Reportables)
- `non_rept_long`, `non_rept_short` (Non-Reportable — small traders)
- `open_interest`

**Pourquoi inutilisée en v1.0.0** : Le pipeline ensemble v1.0.0 n'a pas de feature COT EU dans son feature set. Les 14 specialists ont été trained sans cette colonne.

**Potentiel R&D** : Le Managed Money net position est un sentiment indicator classique en commodities. R&D peut tester :
- Ajouter `m_money_net` comme feature dans le specialist training
- Tester si un nouveau specialist `xpol_W_TB_cot` ou `exp_optim_018_cot` performe mieux
- Combiner avec stocks EU pour signal "physical vs paper" divergence

**Cadence d'ingestion prod** : Daily UPSERT à 22:10 UTC (idempotent). Backfill historique disponible via `poetry run ice-cot-eu-scraper --year YYYY`.

### 2. `pl_contract_data_daily.stock_eu_bags60kg` — **Priorité 2 R&D**

**Statut** : colonne ajoutée (migration `h2c3d4e5f6g7`, 2026-05-20), backfill 18 mois (333 dates non-NULL), lue par `v_contract_data_chained` mais **non utilisée par les specialists** dans leur feature set.

**Données disponibles** : ICE Europe certified cocoa stocks, depuis 2024-11-12 (et jusqu'à 2012 sur Barchart si extended backfill).

**Pourquoi inutilisée en v1.0.0** : Specialists trained avant que cette colonne existe (2026-04-30 cutoff). Le feature `stock_us` est utilisé mais pas `stock_eu`.

**Potentiel R&D** : 
- Combiner `stock_eu_bags60kg` avec `stock_us` pour signal régional (EU dominant for cocoa price discovery)
- Tester la divergence stock_us vs stock_eu comme feature (ratio ou first-derivative)
- Étendre le backfill à 2012 (Barchart historical depth) si signal prometteur

**Cadence** : Daily 19:10 UTC (10 min après barchart-scraper). 333 dates actuelles, +1/jour ouvré.

### 3. `pl_external_indicator.fx_eurusd` / `fx_gbpeur` (raw)

**Statut** : colonnes audit-only, écrites par `cc-fx-scraper` mais **non lues directement** par les specialists.

**Pourquoi inutilisées en v1.0.0** : Les specialists utilisent les transformations dérivées :
- `fx_dxy_proxy = 1 / usd_per_eur` (proxy USD strength, used)
- `fx_gbpusd = usd_per_eur / gbp_per_eur` (used — directly consumed)

`fx_eurusd` est juste l'alias de `dxy_proxy`. `fx_gbpeur` est le raw passthrough audit (= `gbp_per_eur`).

**Potentiel R&D** : Probablement faible — ces colonnes sont déjà encodées dans `fx_dxy_proxy` / `fx_gbpusd`. Garder uniquement pour audit forensic ou si R&D veut reconstruire un signal avec un autre dénominateur (e.g., `gbp_per_usd`).

### 4. `pl_external_indicator.enso_oni_month` / `enso_nino34_anomaly` — **À vérifier**

**Statut** : colonnes écrites par `cc-enso-scraper` mensuel. **Probablement lues par les specialists** (les noms `xpol_S_bear_garch_macro` et `xpol_W_TB_macro` suggèrent qu'ils consomment macro features, dont possiblement ENSO).

**À vérifier dans R&D feature set** : `backend/vendor/campaign5_ensemble_v1.0.0/ensemble/features.py` ou `external_data.py` — voir si ENSO entre dans le specialist input.

**Hypothèse** : oui, utilisé en specialist features avec lag 14 jours (appliqué au compute-time per le scraper docstring).

**Potentiel R&D si pas utilisé** : ENSO est un signal climat fort pour cocoa (West Africa = 65% global production, sensible à El Niño/La Niña). Backfill 76 ans (1950-2026, 950+ months) — données très solides pour tester un specialist climate-aware (`xpol_W_climate` ou similar).

### 5. `pl_weather_observation` (entire table)

**Statut** : Écrit par `cc-meteo-agent` daily, **non lue par ensemble**.

**Données disponibles** :
- 6 localisations cocoa-growing (Daloa, San-Pédro, Soubré, Kumasi, Takoradi, Goaso)
- Per-location `summary, impact_assessment, diagnostics JSONB`
- LLM analysis via `gpt-4.1` en français
- Backfill : ~17 mois (~370 rows)

**Pourquoi inutilisée** : 
- Ensemble v1.0.0 utilise MacroEventLayer sur sentiment articles (`pl_article_segment`), pas weather
- Le legacy `cc-daily-analysis` LLM consomme weather pour son output `macroeco_*`

**Potentiel R&D** : Difficile à intégrer directement (text data) mais peut être structuré :
- Diagnostics JSONB déjà structurée (`per_location: normal/degraded/stress`)
- Aggréger en `n_locations_stress` per date → feature numérique
- Specialist `xpol_climate_weather` testable

### 6. `pl_seasonal_score`

**Statut** : Calculé par `cc-meteo-agent` (campaign-level scoring), **non lue par ensemble**.

**Données** : Score `0-5/5` par saison (winter / spring / summer / autumn) avec status `in_progress / done` per campaign cycle.

**Pourquoi inutilisée** : Pas dans le feature set R&D v1.0.0. Information utilisée par meteo-agent prompt pour mémoire saisonnière, pas par specialists.

**Potentiel R&D** : Marginal — agrégé trop coarse. Mieux d'utiliser raw `pl_weather_observation` directement.

### 7. `pl_sentiment_feature` — Shadow mode

**Statut** : Écrit par `cc-compute-sentiment-features` (cron silencieux), **non lue par ensemble**, **seuil d'activation n≥250 par theme pas encore atteint** (~October 2026 attendu).

**Données** : Rolling z-score 21d + delta 3d sur `pl_article_segment.sentiment_score` agrégé per (date, theme).

**Pourquoi inutilisée** : Le pipeline ensemble préfère le MacroEventLayer (lecture directe `pl_article_segment` 90d window). `pl_sentiment_feature` est une couche dérivée alternative qui pourrait remplacer ou augmenter MacroEventLayer.

**Potentiel R&D** : 
- À mesurer en Octobre 2026 quand seuil atteint
- Tester comme alternative signal vs MacroEventLayer (delta = momentum sentiment vs niveau)
- Peut donner un signal complémentaire ("variation sentiment" vs "niveau sentiment")

### 8. `pl_indicator_daily.macroeco_score / macroeco_bonus / eco / conclusion / confiance / direction`

**Statut** : Écrit par legacy `cc-daily-analysis` LLM, **non lu par ensemble**.

**Données** : Texte LLM-generated en français + scores numériques. Champs dashboard-facing pour l'audience humaine.

**Pourquoi inutilisé en v1.0.0** : Ce sont des outputs legacy concurrents. L'ensemble est censé éventuellement remplacer ces champs.

**Potentiel R&D** : Aucun pour le training. Mais pour la bascule live, le frontend dashboard devra savoir lire **soit** legacy macroeco_* (si is_active=legacy) **soit** ensemble decision_wrapped (si is_active=ensemble).

### 9. Specialists features non-trained

Certaines colonnes dans `pl_derived_indicators` ne sont peut-être pas dans le feature set des 14 specialists actuels (à vérifier dans `vendor/.../ensemble/features.py`). Possibles candidats :
- `bollinger_width` (déjà calculé mais peut-être pas utilisé)
- `volume_oi_ratio` (idem)
- `close_pivot_ratio` (idem)
- ATR variants (`atr` vs `atr_14d`)

**Potentiel R&D** : Inclure dans `features_maximal.py` pour Optuna search dans le prochain HPO.

### 10. Colonnes `pl_orchestrator_decision` non lues côté frontend

Tous les diagnostics dans cette table (winter_vote_signed, spring_vote_signed, anomaly_score_z, prior_open/hedge/monitor, weights_sum, n_committed_specialists, etc.) sont stockés mais **pas lus par le dashboard frontend** (qui lit juste `pl_indicator_daily.decision`).

**Potentiel** : Construire un panel "Compass Intelligence Desk Detail" qui expose ces diagnostics par jour pour transparence trader/CTO. Pas un priorité ML — un priorité UX.

## Tableau récapitulatif des potentiels

| # | Source non-utilisée | Priorité | Effort R&D | Volume data |
|---|---------------------|----------|------------|-------------|
| 1 | `pl_cot_eu_weekly` (Managed Money net) | **P1 — high signal expected** | Medium (new feature + new specialist train) | 12 ans backfill |
| 2 | `pl_contract_data_daily.stock_eu_bags60kg` | **P1 — physical signal** | Low (existing feature, just add column) | 18 mois backfill (extendable to 14 ans) |
| 3 | `pl_external_indicator.enso_*` (verify) | **P1 — vérifier d'abord si déjà utilisé** | Low (might already be in features) | 76 ans backfill |
| 4 | `pl_weather_observation.diagnostics` JSONB | P2 — needs structuring | High (text/json → numeric) | 17 mois backfill |
| 5 | `pl_sentiment_feature` (z-delta) | P2 — wait until n≥250 | Low (already computed, just add to features) | Activation Oct 2026 |
| 6 | `pl_seasonal_score` | P3 — coarse signal | Low | ~5 campaigns |
| 7 | `fx_eurusd / fx_gbpeur` raw | P3 — already encoded | Low | Same as fx_* |

## Sources non-ingérées mais probablement utiles (à recommander si R&D le valide)

Au-delà des tables existantes, voici des sources non-ingérées qui pourraient enrichir le feature set en v1.X :

| Source | Description | Cadence | Auth | Difficulty |
|--------|-------------|---------|------|------------|
| **VIX (CBOE)** | US volatility index (proxy for risk-off regime) | Daily | None (Yahoo Finance / FRED API) | Easy |
| **BCOM Cocoa subindex** | Bloomberg Commodity Cocoa (correlated with London cocoa) | Daily | Bloomberg license needed | Hard |
| **CPC Climate forecasts** | NOAA Climate Prediction Center forecasts (ENSO + precipitation) | Weekly | None (public) | Easy |
| **Shipping rates (Baltic Dry Index)** | Logistics signal for commodities | Daily | None (free APIs) | Medium |
| **Côte d'Ivoire / Ghana government data** | Cocoa export quotas, arrivals, gov price | Weekly | None (gov sites) | Medium (scraping) |
| **Twitter/Reddit cocoa sentiment** | Retail sentiment (noisy but high frequency) | Real-time | API limits | Hard |
| **OpenAI structured prompt sur GDELT** | Macro events GDELT v2 BigQuery (free) | Hourly | GCP credentials | Medium |

R&D peut prioriser après inspection des dépendances de signal.

## Conclusion

**3 sources P1 disponibles immédiatement** pour expé v1.1.0 :
1. `pl_cot_eu_weekly.m_money_net` (12 ans backfill)
2. `pl_contract_data_daily.stock_eu_bags60kg` (18 mois backfill, extendable)
3. `pl_external_indicator.enso_*` (vérifier si déjà dans features ; sinon 76 ans backfill dispo)

Aucune nouvelle infra Compass ne sera nécessaire pour ces 3 : il faut juste les ajouter au feature set R&D et retrainer les specialists.

Pour les sources non-ingérées (VIX, Baltic Dry, GDELT, etc.), une 4ème vague de scrapers Compass serait à construire si R&D les valide post-experiment.
