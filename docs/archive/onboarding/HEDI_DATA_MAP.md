# HEDI_DATA_MAP — Données brutes nécessaires au déploiement Campaign 5

> **Périmètre** : strictement ce qu'il faut comme **raw data** en prod pour que `ensemble_v1_softgate_wrapper` (Campaign 5 Step 1, TPW-001) tourne en `cc-ensemble-compute` quotidien + `cc-ensemble-monthly-retrain` mensuel.
> **Complète** : [rnd-algo-integration.md](rnd-algo-integration.md) (architecture pipeline, contrat schéma) — qui ne détaille PAS les colonnes brutes à provisionner.
> **Source du périmètre** : [experiments/CAMPAIGN_5_PROD_DEPLOYMENT.md](experiments/CAMPAIGN_5_PROD_DEPLOYMENT.md) (§§3, 5, 6, 13).

---

## TL;DR — Ce qui doit être en prod pour que l'algo fonctionne

> **Mise à jour 2026-05-19** : Q1/Q2 résolues + Q4 (GCS) remplacé par `pl_model_artifact` (DB-stored) + Q6 (Db_Master) traité comme artefact frozen long-run.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  EXISTE DÉJÀ EN PROD — confirmé 2026-05-19                                  │
│    pl_contract_data_daily        OHLCV + IV + stocks_us + com_net_us         │
│    pl_derived_indicators         27 technicals                               │
│    pl_article_segment            ✅ écrit daily par press_review_agent       │
│                                    (write_theme_sentiments(), inline_v1)     │
│    ref_contract                  is_active flag pour résolution contrat       │
└─────────────────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────────────────┐
│  GAP PROD — à construire (USs prêtes 2026-05-19)                            │
│    pl_external_indicator         NEW table — ENSO + FX, agnostique           │
│    cc-enso-scraper               US P1-scraper-enso.md (NOAA monthly)        │
│    cc-fx-scraper                 US P1-scraper-fx.md (ECB SDMX daily)        │
│    pl_cot_eu_weekly              NEW table — ICE COT EU décomposition (MM)   │
│    cc-ice-cot-eu-scraper         US P1-scrapers-stock-cot-eu.md adaptée      │
│    pl_specialist_prediction      NEW table — 14 votes/jour                   │
│    pl_orchestrator_decision      NEW table — audit trail soft-gate + wrapper │
│    pl_model_artifact             NEW table — artefacts ML (replaces GCS)     │
│                                    (specialists × 14 + long-run × 4 frozen)  │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Volume total ajouté** :
- 4 nouvelles tables pipeline (~kilo-octets/jour pour predictions/decision, ~50-70 MB/mois pour artifacts BYTEA)
- 3 nouveaux scrapers (≤512 MiB chacun, pure httpx)
- **Pas de bucket GCS** (artifacts en DB, économie ops + 1 backup unique)
- 4 artefacts frozen long-run : `anomaly_veto`, `structural_priors`, `regime_clusters`, **`db_master_fundamentals`** (Q6 directive 2026-05-19)

---

## 1. Données brutes consommées par les 14 spécialistes

Chaque spécialiste a son propre `feature_panel` ; voici le mapping panel → colonnes brutes requises. Tous les spécialistes consomment OHLCV (`pl_contract_data_daily`) + technicals (`pl_derived_indicators`) en base. Les variantes ajoutent FX, ENSO, GARCH ou MAXIMAL.

Source : [methodology/optimizer/specialists.py](methodology/optimizer/specialists.py) (registry de 14) + [methodology/features.py](methodology/features.py) + [methodology/features_external.py](methodology/features_external.py) + [methodology/features_garch.py](methodology/features_garch.py) + [methodology/features_maximal.py](methodology/features_maximal.py).

### 1.1 Panel `baseline` (utilisé par 4 spécialistes : `exp_optim_002`, `exp_optim_006`, `xpol_W_TB_garch` base, etc.)

20 features, toutes dérivées des tables prod existantes :

| Groupe | Feature | Colonne brute | Table source prod | Normalisation |
|---|---|---|---|---|
| **spot** | `close_pivot_ratio` | `close_pivot_ratio` | `pl_derived_indicators` | rolling_zscore_250 |
| spot | `bollinger_width` | `bollinger_width` | `pl_derived_indicators` | rolling_zscore_250 |
| spot | `stochastic_d_14` | `stochastic_d_14` | `pl_derived_indicators` | none (déjà [0,100]) |
| spot | `rsi_14d` | `rsi_14d` | `pl_derived_indicators` | none (déjà [0,100]) |
| **momentum** | `macd` | `macd` | `pl_derived_indicators` | rolling_zscore_250 |
| momentum | `macd_signal` | `macd_signal` | `pl_derived_indicators` | rolling_zscore_250 |
| momentum | `macd_minus_signal` | `macd - macd_signal` | `pl_derived_indicators` | rolling_zscore_250 |
| momentum | `atr_14d` | `atr_14d` | `pl_derived_indicators` | rolling_zscore_250 |
| momentum | `daily_return` | `daily_return` | `pl_derived_indicators` | none |
| momentum | `volume_oi_ratio` | `volume_oi_ratio` | `pl_derived_indicators` | rolling_zscore_250 |
| **fundamental** | `cot_m_money_net_z_26w` | `cot_m_money_net_z_26w` | `pl_cot_eu_weekly` | none (pré-normalisé) |
| fundamental | `cot_prod_merc_net_z_26w` | `cot_prod_merc_net_z_26w` | `pl_cot_eu_weekly` | none |
| fundamental | `cot_m_money_net_pctile_26w` | `cot_m_money_net_pctile_26w` | `pl_cot_eu_weekly` | none |
| fundamental | `sent_all_production` | `sent_all_production` | `pl_article_segment` (pivot zone×thème) | rolling_zscore_250 |
| fundamental | `sent_all_chocolat` | `sent_all_chocolat` | `pl_article_segment` | rolling_zscore_250 |
| fundamental | `sent_afrique_ouest_production` | `sent_afrique_ouest_production` | `pl_article_segment` | rolling_zscore_250 |
| fundamental | `feves_share` | `feves_share` | Db_Master_* (Compass internal) | rolling_zscore_250 |
| fundamental | `processing_ratio` | `processing_ratio` | Db_Master_* (Compass internal) | rolling_zscore_250 |
| fundamental | `procurement_hhi` | `procurement_hhi` | Db_Master_* (Compass internal) | rolling_zscore_250 |
| fundamental | `top3_exporter_share` | `top3_exporter_share` | Db_Master_* (Compass internal) | rolling_zscore_250 |
| **regime** | `atr_pctrank_252` | `atr_14d` | `pl_derived_indicators` | pctrank_252 |

> ✅ **Résolu 2026-05-19** : les fondamentaux internes (`feves_share`, `processing_ratio`, `procurement_hhi`, `top3_exporter_share`) viennent des `Db_Master_Tax.xlsx + Db_Master_Achats.xlsx + Bilan Grainage.xlsx` (publication mensuelle, lag 2 mois). **Traités comme frozen long-run artifact dans `pl_model_artifact`** (§3.5 + §4.5), refresh ponctuel sur livraison XLS. Pas de scraper public, pas de table dédiée daily.

### 1.2 Panel `fx_focus` (utilisé par : `exp_optim_017_bear_4`, `exp_optim_017_bull_4`, `exp_optim_017_bull_7`, `xpol_S_bull_garch_fx`)

Baseline + 2 features FX (z-score 60 jours) :

| Feature | Colonne brute | Source | Normalisation |
|---|---|---|---|
| `fx_dxy_proxy_zscore_60d` | `fx_dxy_proxy` | `pl_external_indicator` (NEW) | zscore_60d (calculé in-engine) |
| `fx_gbpusd_zscore_60d` | `fx_gbpusd` | `pl_external_indicator` (NEW) | zscore_60d (calculé in-engine) |

### 1.3 Panel `fx_enso_focus` (utilisé par : `exp_optim_011` ★ top scorer, `exp_optim_017_bear_8`, `xpol_S_bear_garch_macro`, `xpol_W_TB_macro`)

Baseline + FX (×2) + ENSO (×2) :

| Feature | Colonne brute | Source | Normalisation |
|---|---|---|---|
| FX (×2) | idem panel fx_focus | `pl_external_indicator` | zscore_60d |
| `enso_oni` | `oni` | `pl_external_indicator.enso_oni_month` | none (publication mensuelle, ffill daily) |
| `enso_nino34_anomaly` | `nino34_anomaly` | `pl_external_indicator.enso_nino34_month` | none |

### 1.4 Panel `+garch` et variantes (`exp_optim_005`, `xpol_W_TB_garch`, `xpol_S_bull_garch_fx`, `xpol_S_bear_garch_macro`)

Baseline (+ FX et/ou ENSO selon variante) + résidu GARCH(1,1) :

| Feature | Colonne brute | Calcul | Source |
|---|---|---|---|
| `garch_resid_w500` | `daily_return` | GARCH(1,1) refit tous les 22 jours sur fenêtre 500j ([methodology/features_garch.py](methodology/features_garch.py)) | calculé in-engine, NE NÉCESSITE PAS de nouvelle source brute |

> ⚠️ Dépendance Python : `arch` (`pip install arch`). Confirmer dans `backend/Dockerfile.jobs`.

### 1.5 Panel `maximal` (utilisé par : `exp_optim_017_bull_8` uniquement)

Auto-génère ~91 FeatureSpecs sur **toutes** les colonnes numériques du dataset canonique enrichi (cocoa_rd_dataset + ENSO + FX merge). Source : [methodology/features_maximal.py](methodology/features_maximal.py).

**Pas de nouvelle source brute requise** : consomme ce qui existe déjà dans les tables (technicals + COT + sentiment + ENSO + FX + fondamentaux internes). Mais c'est le panel le plus exigeant en cohérence schéma — toute colonne manquante en prod casse ce spécialiste.

### 1.6 Tableau récapitulatif — qui consomme quoi

| Spécialiste | Cluster | Panel | OHLCV | Tech | COT EU | Sent. | Fundam. | FX | ENSO | GARCH | MAXIMAL |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `exp_optim_002` | winter | baseline | ✓ | ✓ | ✓ | ✓ | ✓ | | | | |
| `exp_optim_005` | winter | +garch | ✓ | ✓ | ✓ | ✓ | ✓ | | | ✓ | |
| `exp_optim_006` | winter | baseline | ✓ | ✓ | ✓ | ✓ | ✓ | | | | |
| `exp_optim_011` ★ | winter | fx_enso_focus | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | | |
| `xpol_W_TB_garch` | winter | +garch | ✓ | ✓ | ✓ | ✓ | ✓ | | | ✓ | |
| `xpol_W_TB_macro` | winter | fx_enso_focus | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | | |
| `exp_optim_017_bear_4` | spring | fx_focus | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | | | |
| `exp_optim_017_bear_8` | spring | fx_enso_focus | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | | |
| `exp_optim_017_bull_4` | spring | fx_focus | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | | | |
| `exp_optim_017_bull_5` | spring | baseline | ✓ | ✓ | ✓ | ✓ | ✓ | | | | |
| `exp_optim_017_bull_7` | spring | fx_focus | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | | | |
| `exp_optim_017_bull_8` | spring | maximal | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | | ✓ |
| `xpol_S_bull_garch_fx` | spring | +garch_fx_focus | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | | ✓ | |
| `xpol_S_bear_garch_macro` | spring | +garch_fx_enso_focus | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |

**Bilan** : 14/14 spécialistes lisent OHLCV + technicals + COT + sentiment + fondamentaux. **9/14 lisent FX** (NEW). **6/14 lisent ENSO** (NEW). **4/14 calculent GARCH** (dérivé in-engine de `daily_return`). **1/14 utilise MAXIMAL** (panel exhaustif sur tout le dataset).

---

## 2. Composants hors spécialistes — données consommées

### 2.1 MacroEventLayer ([methodology/macro_events/pipeline.py](methodology/macro_events/pipeline.py))

Consomme directement **`pl_article_segment`** (pas via les colonnes pivot du dataset canonique). Filtre `confidence >= 0.70`, agrège quotidien.

Colonnes nécessaires sur `pl_article_segment` :
- `article_date` (DATE)
- `confidence` (NUMERIC, [0,1])
- `sentiment_score` (NUMERIC, [-1,+1])

Sortie : `direction ∈ {-1, 0, +1}`, `surprise ∈ [0, 1]`, `half_life_days ∈ {1, 3, 7}`. Mémorisé dans `pl_orchestrator_decision.macro_direction/macro_surprise/macro_half_life_days`.

> ⚠️ **Q2 du déploiement** : confirmer que `pl_article_segment` est bien populé quotidiennement en prod (le R&D doc dit "computed daily but not yet wired into the composite. Will activate around Oct 2026"). Si vide → MacroEventLayer renvoie direction=0 partout → orchestrateur perd le facteur macro.

### 2.2 AnomalyVeto ([methodology/long_run/anomaly_veto.py](methodology/long_run/anomaly_veto.py))

Artefact gelé (refit annuel). Inputs au scoring quotidien : technicals + returns. Aucune nouvelle source brute. Sortie : `anomaly_score_z` écrit dans `pl_orchestrator_decision`.

### 2.3 StructuralPriors ([methodology/long_run/structural_priors.py](methodology/long_run/structural_priors.py))

Empirical Bayes table 12 buckets (regime × vol_12m_tercile × ret_12m_tercile). Inputs : returns + regime_id (HMM). Aucune nouvelle source brute.

### 2.4 RegimeSimilarity ([methodology/long_run/regime_similarity.py](methodology/long_run/regime_similarity.py))

K-means k=2 sur vecteurs d'état mensuels (returns, vol, drawdown, …). Aucune nouvelle source brute. Sortie : poids cluster {winter, spring} utilisés par le soft-gate.

---

## 3. Données brutes existantes en prod — à vérifier

### 3.1 `pl_contract_data_daily` ✓ (existe — section §3 R&D doc)

**Colonnes utilisées par Campaign 5** :
- Clés : `date`, `contract_id`, `display_date`
- OHLCV : `open`, `high`, `low`, `close`, `volume`, `oi`
- IV/Stocks/COT US : `implied_volatility`, `stock_us`, `com_net_us` *(non consommés directement par les spécialistes; lus par compute-indicators legacy qui peuple `pl_derived_indicators`)*

**Cadence** : daily, écrit à 19:00 UTC par `cc-barchart-scraper`. **Lag** : T-0 à 19:00 UTC (front-month-by-OI continuity via `runner.load_all_market_data()`).

### 3.2 `pl_derived_indicators` ✓ (existe)

**Colonnes consommées (12 sur 27 disponibles)** :
- Spot : `close_pivot_ratio`, `bollinger_width`, `stochastic_d_14`, `rsi_14d`
- Momentum : `macd`, `macd_signal`, `atr_14d`, `daily_return`, `volume_oi_ratio`
- Le panel `maximal` consomme aussi : `pivot`, `ema12`, `ema26`, `stochastic_k_14`, `atr`, `bollinger_upper`, `bollinger_lower`, `gain_14d`, `loss_14d`, `rs`

**Cadence** : daily, écrit à 19:15 UTC par `cc-compute-indicators`. **Le job ensemble (`cc-ensemble-compute`) tourne à 19:18 UTC — APRÈS — donc lecture safe.**

### 3.3 `pl_article_segment` ✅ RESOLVED (2026-05-19)

**Colonnes consommées** :
- Directement par MacroEventLayer : `article_date`, `confidence`, `sentiment_score`
- Par les spécialistes via pivot wide (`sent_all_production`, `sent_all_chocolat`, `sent_afrique_ouest_production`) — il faut un view ou un job qui pivote `pl_article_segment` (zone × thème → colonnes daily) avant lecture par les spécialistes

**Cadence prod CONFIRMÉE** : écrit daily par `press_review_agent` (cron `5 19 * * 1-5`, OpenAI o4-mini production provider). Le writer est `backend/scripts/press_review_agent/db_writer.py:96-149` → `write_theme_sentiments()` qui insère pour chaque thème extracté par le LLM : `article_date`, `zone="all"`, `theme`, `sentiment_score`, `sentiment` label, `facts`, `confidence`, `llm_provider`, `llm_model`, `extraction_version="inline_v1"`.

**Volume** : ~4-8 rows/jour (1 par thème identifié dans la press review).

**Note importante** : le docstring du modèle `PlArticleSegment` dans `backend/app/models/pipeline.py` prétend "MODEL-ONLY — the extraction pipeline and API endpoints live on feat/pattern-extractor" — c'est **STALE**. Le branch `feat/pattern-extractor` n'a jamais été mergée ; l'extraction `inline_v1` se fait directement dans le prompt LLM du `press_review_agent` sur main. **À corriger** dans une PR doc séparée (cf. [P1-press-review-backfill-10y.md](../user-stories/P1-press-review-backfill-10y.md) qui prévoit un backfill 10y via GDELT).

**Backfill 10y planifié** : [P1-press-review-backfill-10y.md](../user-stories/P1-press-review-backfill-10y.md) — GDELT 2.0 + LLM o4-mini, ~$60, runtime ~20-30h. Si shipé avant le launch C5 → on a 2500+ jours de sentiment historique pour le warmup rolling 60d-252d des spécialistes (vs ~5 mois aujourd'hui d'accumulation naturelle).

### 3.4 `pl_cot_eu_weekly` (à construire — US prête)

**Statut 2026-05-19** : table inexistante en prod aujourd'hui. **NEW table** sera créée par l'US [P1-scrapers-stock-cot-eu.md](../user-stories/P1-scrapers-stock-cot-eu.md) (révisée 2026-05-19 pour pivoter du schéma "column on pl_contract_data_daily" → "table dédiée").

**Colonnes brutes scrapées** (cf. US §4.1 schema complet) :
- `release_date`, `report_date`, `contract_market` (default 'cocoa')
- Producer/Merchant : `prod_merc_long`, `prod_merc_short`, `prod_merc_net` (colonne générée Postgres)
- **Managed Money** (le signal R&D principal) : `m_money_long`, `m_money_short`, `m_money_net` (colonne générée)
- Other Reportables + Non-Reportable : `other_rept_long/short`, `non_rept_long/short`
- `open_interest` total pour normalisation %OI

**Features dérivées consommées par les spécialistes** (calculées en compute-time par l'engine, **pas par le scraper**) :
- `cot_m_money_net_z_26w` = rolling z-score 26 semaines sur `m_money_net`
- `cot_prod_merc_net_z_26w` = rolling z-score 26 semaines sur `prod_merc_net`
- `cot_m_money_net_pctile_26w` = percentile 26 semaines sur `m_money_net`

**Rationale** : z-scores 26w + percentiles relèvent du pattern "rolling normalization" (rule north-star #6) — calculés en compute-time par l'engine, pas stockés en DB (évite duplication + look-ahead-bias).

**Source ICE** : `https://www.ice.com/report/122` (à parser, format HTML/CSV/PDF à confirmer en spike).

**Backfill historique** : géré dans une US follow-up `P2-scrapers-eu-backfill.md` (créée après le merge de cette US, comme stipulé par Hedi 2026-05-19).

### 3.5 Db_Master fondamentaux internes — ✅ RESOLVED (2026-05-19, Hedi directive)

`feves_share`, `processing_ratio`, `procurement_hhi`, `top3_exporter_share` viennent des XLS internes Compass (`Db_Master_Tax.xlsx`, `Db_Master_Achats.xlsx`, `Bilan grainage moyen 2012-2026.xlsx`).

**Décision Hedi 2026-05-19** : **Option D — Frozen long-run artifact dans `pl_model_artifact`**, traitement identique à `anomaly_veto.pkl`, `structural_priors.json`, `regime_clusters.json` (cf. [CAMPAIGN_5_PROD_DEPLOYMENT.md §2.2](CAMPAIGN_5_PROD_DEPLOYMENT.md#22-frozen-long-run-components-re-used-as-is)).

Concrètement :
- Au launch (bootstrap §7.4) : opérateur génère un pickle du lookup table `month_date → {feves_share, processing_ratio, procurement_hhi, top3_exporter_share}` à partir des XLS actuels, l'INSERT dans `pl_model_artifact` avec `artifact_type='db_master_fundamentals'`, `period_label='snapshot-2026-05-19'`
- L'engine `cc-ensemble-compute` lit ce blob au démarrage et `merge_asof backward` sur `month_date` à compute-time pour attacher les 4 features au panel baseline
- Refresh ponctuel : lorsque Hedi reçoit un nouveau XLS interne → re-run `ensemble-bootstrap-artifacts --artifact-type db_master_fundamentals --period-label snapshot-YYYY-MM-DD --source-xls /path/to/new_Db_Master.xlsx`. Nouvelle row INSERT'ée, l'engine prend la dernière par `created_at DESC`.

**Pourquoi cette option (vs A/B/C archivées)** :
- ✅ Pas de scraper public à maintenir (les data sont internes Compass, non-scrapables)
- ✅ Pas de table dédiée daily inutile (les XLS sont mensuels avec lag 2 mois — la frozen lookup table suffit)
- ✅ Aligné north-star "config + artifacts as data"
- ✅ Refresh ponctuel = 1 commande, pas de cron à maintenir

**Implication training** : ⚠️ **Question ouverte à valider Sprint 1** : les 14 specialists ont-ils été entraînés AVEC ces 4 features ? Si oui → l'engine doit fournir ces features à l'inférence (frozen artifact fournit la valeur la plus récente disponible). Si non → no-op, ces features peuvent rester NULL et l'imputer prend le relais. À demander à Julien.

**Annexe : options A/B/C écartées** (pour traçabilité historique) :
- ~~A) Ingest mensuel via nouveau scraper Cloud Run → `pl_fundamentals_monthly` puis join_asof en compute-time~~ — rejeté : pas de source publique scrapable
- ~~B) Colonnes additionnelles sur `pl_contract_data_daily` populées par un job mensuel~~ — rejeté : duplique daily une valeur mensuelle (anti-pattern)
- ~~C) Joindre via le RD dataset si on génère un snapshot CSV/Parquet régulier en prod~~ — rejeté : couplage avec le repo R&D externe

### 3.6 `ref_contract` ✓ (existe)

Utilisé pour `resolve_active_code()` / `resolve_active_contract_id()` → rule #2 (jamais hardcoder le code de contrat). Lu au démarrage du job `cc-ensemble-compute`.

---

## 4. Données brutes à ajouter en prod (GAP)

### 4.1 ENSO (NOAA, monthly)

**Table cible** : `pl_external_indicator` (NEW, §4.3 du plan déploiement).

| Colonne | Type | Source | Cadence |
|---|---|---|---|
| `enso_oni_month` | NUMERIC(8,4) | NOAA CPC ONI (`https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt`) | mensuel, publication mi-mois pour le mois précédent |
| `enso_nino34_month` | NUMERIC(8,4) | NOAA Niño 3.4 SST anomaly | idem |

**Lag policy** : `enso_publication_lag_days = 14` jours ([methodology/external_data.py:55](methodology/external_data.py)) — la valeur du mois M est utilisable à partir de M+1, jour 15. Ffill daily entre publications.

**Backfill requis** : 10 ans (2016-01 → today). Source locale snapshot : [data/external_data/ENSO/oni_monthly.csv](data/external_data/ENSO/oni_monthly.csv) + [data/external_data/ENSO/nino34_monthly.csv](data/external_data/ENSO/nino34_monthly.csv) (déjà préparés sur la branche Hedi-local-draft).

**Scraper prod à créer** : `backend/scripts/enso_scraper/` (§5.1 du plan). Cloud Run Job `cc-enso-scraper`, 512Mi, cron `0 22 20 * 1-5` (20 du mois à 22:00 UTC).

### 4.2 FX (ECB SDMX, daily)

**Table cible** : `pl_external_indicator` (mêmes lignes, colonnes additionnelles).

| Colonne | Type | Source ECB SDMX 2.1 | Cadence |
|---|---|---|---|
| `fx_dxy_proxy` | NUMERIC(15,6) | calculé depuis USD/EUR (`D.USD.EUR.SP00.A`) | daily |
| `fx_gbpusd` | NUMERIC(15,6) | dérivé (GBP/EUR × USD/EUR) | daily |
| `fx_eurusd` | NUMERIC(15,6) | inverse USD/EUR | daily |
| `fx_gbpeur` | NUMERIC(15,6) | `D.GBP.EUR.SP00.A` | daily |

**Note** : `methodology/features_external.py` ne consomme que `fx_dxy_proxy` + `fx_gbpusd` (les 2 autres sont là pour audit/futures features). Le passe-plat features_external applique `_zscore_60d` in-engine.

**Backfill requis** : 10 ans. Source locale : [data/external_data/FX/dxy_proxy_daily.csv](data/external_data/FX/dxy_proxy_daily.csv) + [data/external_data/FX/gbpusd_daily.csv](data/external_data/FX/gbpusd_daily.csv).

**Scraper prod à créer** : `backend/scripts/fx_scraper/` (§5.2 du plan). Cloud Run Job `cc-fx-scraper`, 512Mi, cron `30 18 * * 1-5` (daily 18:30 UTC, avant compute à 19:18).

### 4.3 Fondamentaux internes Compass (Db_Master) — ✅ RESOLVED (Option D)

> **Décision 2026-05-19** : Db_Master traité comme **frozen long-run artifact dans `pl_model_artifact`**. Cf. §3.5 + [CAMPAIGN_5_PROD_DEPLOYMENT.md §2.2 + §7](CAMPAIGN_5_PROD_DEPLOYMENT.md#22-frozen-long-run-components-re-used-as-is).

**Workflow** :
1. **Bootstrap initial** : `ensemble-bootstrap-artifacts --artifact-type db_master_fundamentals --period-label snapshot-2026-05-19 --source-xls /path/to/Db_Master_*.xlsx`. Pickle un lookup table `month_date → {feves_share, processing_ratio, procurement_hhi, top3_exporter_share}` et INSERT row dans `pl_model_artifact`.
2. **Engine compute-time** : `cc-ensemble-compute` charge le pickle au démarrage, fait `merge_asof backward` sur `month_date` pour attacher les 4 features au panel baseline daily.
3. **Refresh ponctuel** : sur livraison d'un nouveau XLS Compass → re-run la commande avec `--period-label snapshot-YYYY-MM-DD`. Nouvelle row INSERT'ée, l'engine prend la dernière par `created_at DESC`.

**Sources XLS internes** : [data/external_data/Db_Master_Tax.xlsx](data/external_data/Db_Master_Tax.xlsx) + [data/external_data/Db_Master_Achats.xlsx](data/external_data/Db_Master_Achats.xlsx) + [data/external_data/01 04 26 _Bilan grainage moyen 2012 2013 _2025 2026.xlsx](data/external_data/01 04 26 _Bilan grainage moyen 2012 2013 _2025 2026.xlsx). **Sources métier internes, pas des scrapers publics** — d'où le pattern frozen artifact + bootstrap manuel.

**Pas de table `pl_fundamentals_monthly`** : pas créée (option A archivée). Le lookup table vit en blob BYTEA dans `pl_model_artifact`.

### 4.4 Tables d'output (audit + décision) — NEW

| Table | Clé | Cadence d'écriture | Volume estimé |
|---|---|---|---|
| `pl_specialist_prediction` | (date, contract_id, algorithm_version_id, specialist_name) | 14 lignes/jour | ~3640 lignes/an |
| `pl_orchestrator_decision` | (date, contract_id, algorithm_version_id) | 1 ligne/jour | ~260 lignes/an |
| `pl_external_indicator` | (date) | 1 ligne/jour | ~260 lignes/an |
| `pl_indicator_daily` (ligne ensemble) | (date, contract_id, algorithm_version_id) | 1 ligne/jour | ~260 lignes/an |

Total nouveau ~4400 lignes/an = négligeable côté DB.

### 4.5 `pl_model_artifact` — artefacts modèles (NEW, replaces GCS)

> **Décision 2026-05-19** : remplace l'option GCS bucket initiale par une table DB. Aligné north-star + simpler ops. Cf. [CAMPAIGN_5_PROD_DEPLOYMENT.md §4.5 + §7](CAMPAIGN_5_PROD_DEPLOYMENT.md#45-pl_model_artifact-new-2026-05-19--db-stored-ml-artifacts-replaces-gcs) pour le schéma complet + loader contract.

Logiquement :
```
pl_model_artifact (DB-stored, BYTEA blobs)
├─ Specialists (monthly retrain, 14 rows/mois)
│   artifact_type='specialist'
│   artifact_name='exp_optim_<id>' × 14
│   period_label='YYYY-MM'
│   fit_metadata JSONB : n_train, class_balance, git_sha
│
└─ Long-run frozen (yearly refit + Db_Master ponctuel, 4 rows/an)
    artifact_type IN ('anomaly_veto', 'structural_priors', 'regime_clusters', 'db_master_fundamentals')
    period_label='yearly-YYYY' ou 'snapshot-YYYY-MM-DD'
```

**Volume** :
- Specialists : 14 × 3-5 MB = ~50-70 MB/mois (LightGBM/RF pickled)
- Long-run : 3-4 × 5-20 MB = ~30-80 MB/an
- **Total** : ~700 MB/an → trivial pour PostgreSQL TOAST

**Auth** : same DB user que tous les autres jobs (pas de WIF additionnelle). SHA-256 audité au load (§7.2 loader contract).

**Bootstrap initial** : `poetry run ensemble-bootstrap-artifacts --algorithm-version ensemble_v1_softgate_wrapper@1.0.0 --rd-output-dir /path/to/RnD/output/` (cf. CAMPAIGN_5 §7.4).

---

## 5. Lag policy et ordonnancement pipeline

Cohérent avec [methodology/external_data.py](methodology/external_data.py) et §6.3 du plan déploiement.

| Source | Lag publication | Politique join |
|---|---|---|
| OHLCV (`pl_contract_data_daily`) | T-0 19:00 UTC | direct (front-month-by-OI) |
| Technicals (`pl_derived_indicators`) | T-0 19:15 UTC | direct |
| Sentiment (`pl_article_segment`) | T-0 19:05 UTC | direct + pivot zone×thème |
| COT EU (`pl_cot_eu_weekly`) | T+3 cal days (release vendredi pour mardi) | `merge_asof backward`, tolerance=14 j |
| ENSO (NOAA) | M+15 j (mi-mois pour mois précédent) | `merge_asof backward` + ffill daily |
| FX (ECB) | T-0 16:00 CET | direct, daily |
| Db_Master (interne) | M+2 mois | `merge_asof backward` sur month_date |

**Ordre cron 19:00 UTC** (§6.3) :
```
19:00  cc-barchart-scraper           → pl_contract_data_daily
19:00  cc-meteo-agent                → pl_weather_observation
19:05  cc-ice-stocks-scraper         → pl_contract_data_daily.stock_us
19:05  cc-cftc-scraper               → pl_contract_data_daily.com_net_us
19:05  cc-press-review-agent         → pl_fundamental_article (+ pl_article_segment ?)
19:15  cc-compute-indicators         → pl_derived_indicators
18:30  cc-fx-scraper                 → pl_external_indicator.fx_*       (NEW)
19:18  cc-ensemble-compute           → pl_specialist_prediction +       (NEW)
                                        pl_orchestrator_decision +
                                        pl_indicator_daily (ensemble row)
19:20  cc-daily-analysis             → pl_indicator_daily.decision (legacy only — vérifier Q3)
19:30  cc-compass-brief              → Drive .txt
```

Hors cron quotidien :
- `cc-enso-scraper` : `0 22 20 * 1-5` (20 du mois 22:00 UTC)
- `cc-ensemble-monthly-retrain` : `0 17 1-3 * 1-5` (jour 1-3 du mois 17:00 UTC)
- ~~`cc-fundamentals-ingest`~~ : **non créé** (option A archivée). Db_Master refresh = manual `ensemble-bootstrap-artifacts` sur livraison XLS, pas un cron.

---

## 6. Backfills à exécuter le jour J (avant `is_active=TRUE`)

Plan déploiement Day 4 (§9) :

1. **Backfill `pl_external_indicator`** — 10 ans ENSO + FX. Source : CSV locaux [data/external_data/ENSO/](data/external_data/ENSO/) + [data/external_data/FX/](data/external_data/FX/). Valider value-by-value contre R&D CSV.
2. **Backfill `pl_cot_eu_weekly`** si absent — 10 ans depuis ICE Europe COT.
3. **Bootstrap Db_Master frozen artifact** — `ensemble-bootstrap-artifacts --artifact-type db_master_fundamentals --period-label snapshot-2026-05-19 --source-xls /path/to/Db_Master_*.xlsx`. 1 row INSERT'ée dans `pl_model_artifact`. Pas de "backfill 10y" séparé : la frozen lookup table contient déjà l'historique XLS interne.
4. **Bootstrap GCS** — uploader manuellement les 14 specialist artifacts R&D-trained + 3 long-run artifacts pour le mois de launch + générer le manifest.
5. **Pre-seed `pl_orchestrator_decision`** (§8.2 du plan) — 5 lignes trailing depuis [output/exp_optim_025/wrapped_decisions.csv](output/exp_optim_025/wrapped_decisions.csv), bind contract_id via front-month-by-OI au prod DB. Sinon le wrapper detector A (running_acc) est aveugle pendant 5 jours.

---

## 7. Points à valider avec Hedi (les 8 Q du plan §3)

> **Mise à jour 2026-05-19** : Q1, Q2, Q3, Q4, Q6 résolues. Q5, Q7, Q8 pending Sprint 1.

- **Q1 ENSO/FX scrapers** : ✅ **RESOLVED** — confirmé qu'aucun feed ENSO/FX n'existe en prod. USs prêtes : [P1-scraper-enso.md](../user-stories/P1-scraper-enso.md) + [P1-scraper-fx.md](../user-stories/P1-scraper-fx.md). Code R&D en snapshot dans `docs/onboarding/ingest_{enso,fx}.py` + CSV backfill 10-12y dans `docs/onboarding/{ENSO,FX}/`.
- **Q2 `pl_article_segment` freshness** : ✅ **RESOLVED** — écrit daily par `press_review_agent/db_writer.py:write_theme_sentiments()` (cron `5 19 * * 1-5`, ~4-8 rows/jour). Le docstring du modèle "MODEL-ONLY" est STALE (à corriger dans une PR doc). [P1-press-review-backfill-10y.md](../user-stories/P1-press-review-backfill-10y.md) prévoit le backfill 10y GDELT avant le launch C5.
- **Q3 daily-analysis targeting** : ✅ **RESOLVED** — code scope déjà `WHERE is_active = TRUE LIMIT 1` ([db_analysis_engine.py:238-241](../../backend/scripts/daily_analysis/db_analysis_engine.py#L238-L241)), MAIS day-1 promotion de l'ensemble en `is_active=TRUE` → conflict. **Mitigation** : [P2-daily-analysis-version-flag.md](../user-stories/P2-daily-analysis-version-flag.md) ajoute `--algorithm-version legacy` pinné dans deploy.yml. Bloquant pour le launch.
- **Q4 GCS bucket** : ✅ **RESOLVED** — **REMPLACÉ par DB table `pl_model_artifact`** (cf. §4.5 + [CAMPAIGN_5 §7](CAMPAIGN_5_PROD_DEPLOYMENT.md#7--artifact-management-strategy-db-stored-no-gcs)). Aligné north-star + simpler ops. No bucket to provision, no WIF write.
- **Q5 DataFrame size** : ⏳ **PENDING Sprint 1** — vérifier que `runner.load_all_market_data()` donne la même série temporelle que le R&D pipeline (front-month-by-OI continuity 2016 → today). Action : compare row-by-row via [extract_rd_dataset.py](extract_rd_dataset.py) côté R&D vs prod sync.
- **Q6 Db_Master fundamentals** : ✅ **RESOLVED** — frozen long-run artifact dans `pl_model_artifact`, refit ponctuel sur livraison XLS (cf. §3.5 + [CAMPAIGN_5 §2.2](CAMPAIGN_5_PROD_DEPLOYMENT.md#22-frozen-long-run-components-re-used-as-is)).
- **Q7 Compute envelope** : ⏳ **PENDING Sprint 1** — bench 14 inferences (~10ms) + wrapper (~50ms) + load 18 artifacts depuis DB BYTEA + write rows. Target : 1Gi + ~2min OK. À mesurer en local avant deploy.
- **Q8 Reproducibility** : ⏳ **PENDING Sprint 1** — diff `backend/Dockerfile.jobs` deps vs R&D venv. Critical : `numpy 1.26.4`, scikit-learn, lightgbm, `arch` (pour GARCH) versions identiques. Sinon → divergence silencieuse des inférences.

---

## 8. Récapitulatif — pour l'algo soit fonctionnel en prod, il faut

### A. Vérifier l'existant
1. `pl_contract_data_daily` (OHLCV + IV + stock_us + com_net_us) → écrit
2. `pl_derived_indicators` (27 cols) → écrit
3. `pl_article_segment` (Q2) → confirmation freshness + colonnes `article_date/confidence/sentiment_score`
4. `pl_cot_eu_weekly` → existence à vérifier
5. `ref_contract.is_active` → résolution active contract

### B. Construire (PATH C)
6. Table `pl_external_indicator` + scraper `cc-enso-scraper` (NOAA monthly)
7. Table `pl_external_indicator` (mêmes lignes) + scraper `cc-fx-scraper` (ECB daily)
8. Pivot/vue `pl_article_segment` → colonnes `sent_<zone>_<theme>` pour consommation par features fundamental
9. Frozen artifact Db_Master via `pl_model_artifact` (NEW table) + bootstrap manuel `ensemble-bootstrap-artifacts` (cf. §4.3)
10. Tables `pl_specialist_prediction` + `pl_orchestrator_decision`
11. ~~Bucket GCS~~ → **table `pl_model_artifact`** : artifacts ML en DB BYTEA (cf. §4.5, [CAMPAIGN_5 §4.5 + §7](CAMPAIGN_5_PROD_DEPLOYMENT.md))

### C. Backfills à J-1
12. ENSO 10y, FX 10y, COT EU 10y, fondamentaux 10y
13. Bootstrap GCS (14 specialist artifacts + 3 long-run frozen)
14. Pre-seed `pl_orchestrator_decision` 5 derniers jours (depuis CSV R&D)

### D. Modules à porter R&D → prod (référence §2.5 + §13 du plan)
- 14 spécialistes registry, soft_gate, transition_wrapper, monthly_retrainer
- long_run (anomaly_veto, structural_priors, regime_similarity)
- macro_events pipeline
- features_external, features_garch, features_maximal
- targets / targets_calibrated / targets_triple_barrier
- training_utils/anti_bias

### E. Schéma — INSERT version + config rows (§4.4)
- `pl_algorithm_version` row `ensemble_v1_softgate_wrapper` v1.0.0 `is_active=TRUE`
- 14 `pl_algorithm_config` rows pour soft-gate + wrapper params + cluster mapping + artifact URIs

---

## 9. Fichiers de référence — où regarder

| Sujet | Path |
|---|---|
| Plan déploiement complet | [experiments/CAMPAIGN_5_PROD_DEPLOYMENT.md](experiments/CAMPAIGN_5_PROD_DEPLOYMENT.md) |
| Architecture vision | [experiments/CAMPAIGN_4_ARCHITECTURE_VISION.md](experiments/CAMPAIGN_4_ARCHITECTURE_VISION.md) |
| Pipeline R&D framework | [methodology/framework-spec.md](methodology/framework-spec.md) |
| Pipeline prod (architecture) | [rnd-algo-integration.md](rnd-algo-integration.md) |
| Feature specs (baseline) | [methodology/features.py](methodology/features.py) |
| Feature specs (FX + ENSO) | [methodology/features_external.py](methodology/features_external.py) |
| Feature specs (GARCH) | [methodology/features_garch.py](methodology/features_garch.py) |
| Feature specs (MAXIMAL) | [methodology/features_maximal.py](methodology/features_maximal.py) |
| Registry 14 spécialistes | [methodology/optimizer/specialists.py](methodology/optimizer/specialists.py) |
| Merge ENSO/FX (lag policy) | [methodology/external_data.py](methodology/external_data.py) |
| MacroEventLayer | [methodology/macro_events/pipeline.py](methodology/macro_events/pipeline.py) |
| Soft-gate orchestrator | [methodology/orchestrator/soft_gate.py](methodology/orchestrator/soft_gate.py) |
| Transition wrapper | [methodology/orchestrator/transition_wrapper.py](methodology/orchestrator/transition_wrapper.py) |
| Monthly retrainer | [methodology/retrain/monthly_retrainer.py](methodology/retrain/monthly_retrainer.py) |
| ENSO data snapshot | [data/external_data/ENSO/](data/external_data/ENSO/) |
| FX data snapshot | [data/external_data/FX/](data/external_data/FX/) |
| Fondamentaux internes | [data/external_data/Db_Master_Tax.xlsx](data/external_data/Db_Master_Tax.xlsx) + Achats + Bilan |
