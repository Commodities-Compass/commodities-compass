# Pipeline ENSEMBLE v1.0.0 — `cc-ensemble-compute` + `cc-ensemble-explainer` + `cc-compass-brief-ensemble`

> Architecture documentaire macro du pipeline ML moderne de production de décisions de trading et du brief ensemble associé. Décrit la **logique métier**, la **sémantique des 14 spécialistes**, le rôle du **soft-gate Bayésien** et du **Compass wrapper**, et comment cette stack produit un brief NotebookLM enrichi. Pas de code détaillé — pour le code, voir les références à la fin.

> **Statut 2026-05-26** : pipeline EN PRODUCTION quotidienne. Écrit les décisions sur la row ensemble de `pl_indicator_daily` (`algorithm_version_id = ensemble_v1_softgate_wrapper`). Le frontend dashboard sert déjà l'ensemble via `_resolve_algo_for_date()`. Le brief ensemble (avec narrative LLM enrichi) est en mode dual-track avec le brief legacy (cf. [PIPELINE_LEGACY.md](./PIPELINE_LEGACY.md)).

---

## 1 — Vue d'ensemble

### Question business à laquelle ce pipeline répond

> « Pour la fenêtre des 4-5 prochains trading days, quel **biais directionnel** (OPEN / HEDGE / MONITOR) sortent les **14 modèles ML spécialisés** vu les conditions de marché, et avec quel **niveau de consensus statistique** ? »

### Différence fondamentale avec le legacy

| Dimension | Legacy LLM | Ensemble v1.0.0 |
|---|---|---|
| **Décideur final** | LLM gpt-4-turbo (Call #2) | 14 specialists ML → soft-gate Bayésien → wrapper |
| **Horizon** | T+1 (intra-session) | J+4-J+5 (fenêtre 5 jours) |
| **Fitness mesurable** | Non | Oui : `running_acc_5d`, `forward_return_6d`, YTD scoring |
| **Reproductibilité** | LLM stochastique | Modèles déterministes (sauf si LLM Explainer ajouté pour narrative) |
| **Audit trail** | Texte LLM (eco, conclusion) | 25 colonnes structurées (`pl_orchestrator_decision`) + 14 votes |
| **Inputs structurés** | 42 technicals + texte presse/météo | OHLCV chained 600d + 27 indicators + ENSO + FX + COT EU + sentiment features |
| **Coût LLM** | $0.13/jour (2 calls) | $0.001/jour (1 call narrative optionnel via Explainer) |
| **Robustesse aux pannes LLM** | Brief perdu si OpenAI down | Décision toujours produite (le LLM est optionnel pour la narrative seulement) |

### Stack

- **14 spécialistes ML** : LightGBM classifiers + GARCH volatility models entraînés mensuellement sur 12 ou 24 mois rolling. Chacun produit un vote OPEN/HEDGE/MONITOR.
- **Soft-gate Bayésien** : combine les 14 votes pondérés par leur accuracy historique + structural priors Bayésiens → produit `soft_gate_decision` + `net_score`.
- **Compass wrapper** : 4 détecteurs (running_acc, trend, dispersion, three_way) qui peuvent vetoer la décision soft-gate → `decision_wrapped` (la décision finale).
- **Diagnostics** : 25 colonnes auditables (`pl_orchestrator_decision`) qui expliquent POURQUOI la décision a été prise.
- `cc-ensemble-explainer` (refactor 2026-05-27) : thin wrapper qui invoque `DBAnalysisEngine` (le moteur legacy) **sans pinner sur `legacy`** → l'auto-align détecte la row ensemble dans `pl_orchestrator_decision`, injecte les diagnostics via `CALL_2_PROMPT_ENSEMBLE`, et écrit la narrative (eco / confidence / direction / conclusion long-form `> ... • ... > A SURVEILLER AUJOURD'HUI:`) sur la row ensemble. Aucun prompt custom — réutilisation totale du pipeline legacy.

### Forces et limites

**Forces** :
- Quantitative fitness measurable (running_acc, YTD)
- 14 angles indépendants (TB, FX, MAXIMAL, GARCH variants, ENSO, macro)
- Audit trail riche (25+ champs structurés)
- Multi-horizon (5d rolling)
- Pas de hallucination — c'est du déterministe ML
- Cost LLM : 2× `gpt-4-turbo`/jour côté legacy + 2× `gpt-4-turbo`/jour côté ensemble-explainer (qui partage le même engine) = ~$30/an supplémentaires pour la dual-track narrative. Trade-off pour la parité de format avec le brief legacy.

**Limites** :
- Sans le LLM Explainer, pas de narrative humaine — la décision est juste un label
- Nécessite retraining mensuel des 14 spécialistes (R&D côté)
- Dépendance aux artifacts BYTEA stockés dans `pl_model_artifact` (SHA-256 verified)
- Cold-start NaN sur `running_acc_5d` les 5 premiers jours après chaque retraining

---

## 2 — Architecture des 14 spécialistes

### Vue d'ensemble du panel

> Source d'autorité : [docs/onboarding/CAMPAIGN_5_PROD_DEPLOYMENT.md](../onboarding/CAMPAIGN_5_PROD_DEPLOYMENT.md) §2 + [docs/onboarding/HEDI_DATA_MAP.md](../onboarding/HEDI_DATA_MAP.md) §1

Les 14 spécialistes se répartissent en **2 clusters thématiques** + plusieurs **familles techniques** :

### 2.1 Cluster Winter (TB/FX-anchored, ~6 spécialistes)

Spécialisés sur la dimension **TermBack** (positionnement court terme + FX hedging proxy).

Exemples de noms :
- `exp_optim_002` — baseline TB
- `exp_optim_005` — TB + FX features
- `exp_optim_008` — TB + COT EU positioning
- `xpol_W_TB_garch` — TB avec volatility-conditional GARCH(1,1)

Concept business : « le marché cocoa London se lit d'abord à travers la structure de termback (front-month vs deferred) et la couverture FX GBP/USD. Quand TB se dilate et que FX hedging est cher, c'est un signal de stress. »

Window months : 12 (baseline) ou 24 (GARCH variants).

### 2.2 Cluster Spring (macro/ENSO-anchored, ~8 spécialistes)

Spécialisés sur les conditions **macro structurelles** (climat, sentiment, ENSO).

Exemples de noms :
- `exp_optim_011` — **top scorer Campaign 4-5** (ENSO + FX + macro)
- `xpol_S_macro_combined` — macro events depuis sentiment features
- `xpol_S_bear_garch_macro` — macro avec biais bearish + GARCH
- `macro_combined_spring` — combinaison sentiment + ENSO + COT

Concept business : « les marches multi-jours sur le cocoa sont structurés par les conditions climatiques (ENSO), le sentiment narratif (press review), et le positionning Managed Money (COT EU). Ce sont des forces lentes (half-life > 7 jours) mais persistantes. »

### 2.3 Familles techniques transverses

Chaque cluster a plusieurs variantes :

- **Baseline** : LightGBM classifier vanilla
- **`+garch`** : couplé à un modèle GARCH(1,1) qui pondère les features selon la volatility-régime
- **`+macro`** : ajoute des features de macro-event surprise (depuis `pl_article_segment` sentiment)
- **`+enso`** / **`+fx`** : ajoute les features climat / FX

Les 14 modèles couvrent ces combinaisons. La R&D les optimise via grid search mensuel.

### 2.4 Inputs partagés vs spécifiques

Tous les spécialistes lisent :
- 600 jours d'OHLCV chained (vue `v_contract_data_chained`)
- 27 indicators dérivés (de `pl_derived_indicators`)

Subsets selon le panel :
- Cluster Winter : ajoute `fx_dxy_proxy`, `fx_gbpusd`, COT EU `m_money_net` z-score
- Cluster Spring : ajoute `enso_oni_month`, `enso_nino34_anomaly`, MacroEventLayer signal
- Variants GARCH : ajoutent la volatility forecast 5d
- Variants Macro : ajoutent `macro_direction`, `macro_surprise`, `macro_half_life_days`

### 2.5 Pourquoi 14 et pas 1 « gros » modèle ?

**Diversification de hypothèses** : chaque spécialiste répond à une vue partielle du marché (TB vs macro, court vs long terme, volatility-conditional vs unconditional). Si un seul est trompé par un régime change, les autres compensent.

**Calibration Bayésienne** : le soft-gate orchestrateur peut pondérer les spécialistes selon leur perf récente. Un spécialiste qui sous-performe les 30 derniers jours voit son poids diminuer automatiquement.

**Audit trail** : on peut tracer la décision à la composition des 14 votes. « 11/14 spécialistes commits, dont 4 Winter + 5 Spring → consensus solide. »

---

## 3 — Le soft-gate Bayésien (orchestrateur)

> Code R&D : `backend/vendor/campaign5_ensemble_v1.0.0/` (le code R&D est vendored, jamais modifié in-place)

### Logique en 4 étapes

**Step 1 — Collecte des 14 votes**
Chaque spécialiste produit `(decision, confidence_score)` où confidence_score est la probabilité interne du modèle.

**Step 2 — Filtre des `committed` votes**
Un spécialiste qui a un confidence_score < seuil minimum est considéré comme « pas committed » → exclu de la combinaison. On note `n_committed_specialists` (typiquement 8-12 sur 14).

**Step 3 — Combinaison Bayésienne**
- `weight_i = perf_30d(specialist_i) × cluster_weight × Bayesian_prior`
- `net_score = Σ (weight_i × vote_i) / Σ weight_i` (vote_i mappé OPEN=+1, MONITOR=0, HEDGE=-1)
- `soft_gate_decision = arg_max_combined(weighted_votes)` mappé sur OPEN/HEDGE/MONITOR

**Step 4 — Application des structural priors**
Priors structurels (`prior_open`, `prior_hedge`, `prior_monitor`) qui reflètent la distribution historique des décisions sur des régimes similaires. Si `net_score` est ambigu, les priors tranchent.

### Outputs

`pl_orchestrator_decision` après soft-gate :
- `soft_gate_decision` : OPEN | HEDGE | MONITOR
- `net_score` : DECIMAL(15,6), interprétable comme « score combiné Bayésien »
- `weights_sum` : somme des poids des spécialistes committed
- `n_committed_specialists` : combien sur 14 ont participé
- `winter_vote_signed`, `spring_vote_signed` : agrégés par cluster (sum of OPEN=+1, HEDGE=-1)

---

## 4 — Le Compass wrapper (override Compass-side du R&D wrapper)

### Pourquoi un wrapper

Le soft-gate produit une décision, mais elle peut être trompée par des **régime transitions** (ENSO shift, anomaly, désaccord soutenu). Le wrapper est une couche de safety-net qui peut **vetoer** la décision soft-gate vers MONITOR si certaines conditions sont remplies.

### Les 4 détecteurs

> Code : [backend/scripts/ensemble_compute/compass_wrapper.py](../../backend/scripts/ensemble_compute/compass_wrapper.py)

| Détecteur | Fire condition | Sémantique |
|---|---|---|
| `fired_running_acc` | running_acc_5d récente < seuil (≈ 0.45) | Le gate a sous-performé les 5 derniers jours — méfiance |
| `fired_trend` | (off en v1.0.0) | Détecte un trend conflict entre clusters |
| `fired_dispersion` | n_committed_specialists trop bas + variance des votes élevée | Pas de consensus — soft-gate prend une décision sur peu de signal |
| `fired_three_way` | (off en v1.0.0) | Détecte un three-way disagreement (Winter≠Spring≠global) |

### Vendor R&D wrapper (par défaut)
**Logique** : OR pure → si UN détecteur fire, on vetoe la soft-gate decision → `decision_wrapped = MONITOR`.

### Compass override (notre version Compass-side)
**Pourquoi** : sur le backfill 2026, le vendor wrapper vetoait 73% des soft-gate commits, ce qui réduisait coverage à 17% (vs 49% atteignable). On a constaté que `fired_dispersion` SEUL (sans run_acc fire) sur des périodes où le gate venait de bien performer (`running_acc_5d ≥ 0.60`) était trop strict.

**Logique Compass** : « release » du `fired_dispersion` veto SI `running_acc_5d >= 0.60 OR NaN`. Concrètement :
- Si `fired_running_acc OR fired_trend OR fired_three_way` → veto maintenu → wrap to MONITOR
- Si SEUL `fired_dispersion` fire ET `running_acc_5d >= 0.60` → release → garder la soft-gate decision

**Threshold** : `compass_wrapper_dispersion_with_acc_threshold` stocké dans `pl_algorithm_config` (config-as-data). Aujourd'hui = 0.60. Tunable sans deploy.

### Outputs wrapper

- `decision_wrapped` : OPEN | HEDGE | MONITOR — c'est LA décision finale
- `wrapper_active` : TRUE si wrapped ≠ soft_gate (le wrapper a effectivement changé la décision)
- 4 booléens `fired_*` : pour audit, on garde la trace des détecteurs qui ont fired (même si le Compass override a relâché le veto)

### Result on backfill 2026

| Metric | Vendor wrapper | Compass wrapper |
|---|---|---|
| Coverage (WR / total) | 17% | **49%** |
| WR accuracy | 100% (mais cold-start NaN) | 76% |

→ Compass override booste la coverage tout en gardant une accuracy correcte.

---

## 5 — Diagnostics structurés produits (`pl_orchestrator_decision`)

> Tous nullable — fail-loud rule §0 #3 : `NULL ≠ computed 0.0`. Une diag NULL signifie « pas calculée pour cette date » (cold start, missing input, etc.).

| Colonne | Type | Sémantique | Comment l'utiliser dans un brief |
|---|---|---|---|
| `decision_wrapped` | str | Décision finale | C'est la position du jour |
| `soft_gate_decision` | str | Décision avant wrapper | Comparer avec wrapped → savoir si wrapper a corrigé |
| `wrapper_active` | bool | Wrapper a changé la décision ? | « Wrapper actif : Oui (soft-gate disait OPEN, wrapped MONITOR) » |
| `net_score` | Decimal | Score Bayésien combiné | Conviction quantitative |
| `n_committed_specialists` | int | Combien sur 14 ont voté | « 11/14 spécialistes commits » |
| `weights_sum` | Decimal | Somme des poids committed | Qualité du consensus |
| `running_acc_5d` | Decimal | Accuracy gate sur 5 derniers jours | « Le gate a 91% d'accuracy récent » |
| `realized_return_5d` | Decimal | Return réalisé 5d | Performance financière du gate récent |
| `fired_running_acc` | bool | Détecteur run_acc fired ? | Audit du wrapper |
| `fired_trend` | bool | Détecteur trend fired ? | Off en v1.0.0 |
| `fired_dispersion` | bool | Détecteur dispersion fired ? | « Désaccord spécialistes détecté » |
| `fired_three_way` | bool | Détecteur 3-way fired ? | Off en v1.0.0 |
| `macro_direction` | int (-1/0/+1) | Signal macro depuis sentiment | Indique le bias macro structurel |
| `macro_surprise` | Decimal | Surprise z-score | « Macro surprise +0.42σ » |
| `macro_half_life_days` | int | Combien de jours le signal va persister | Horizon du macro signal |
| `anomaly_score_z` | Decimal | IsolationForest score | « Régime anormal détecté » si > 2.5 |
| `prior_open/hedge/monitor` | Decimal | Bayesian structural priors | « En régime similaire, P(OPEN)=0.55 » |
| `winter_vote_signed` | int | Sum OPEN=+1/HEDGE=-1 cluster Winter | « Cluster Winter +3 (bullish) » |
| `spring_vote_signed` | int | Sum cluster Spring | « Cluster Spring -2 (bearish) » |

Ces 25 champs sont **TOUS exposés par l'endpoint `/v1/dashboard/ensemble-diagnostics`** et lus par le frontend (`useEnsembleDiagnostics()` hook).

---

## 6 — Frontend intégration (déjà active)

> Code : [backend/app/services/dashboard_service.py](../../backend/app/services/dashboard_service.py), [endpoints/dashboard.py](../../backend/app/api/api_v1/endpoints/dashboard.py)

### 6.1 Résolution de l'algorithm version

`_resolve_algo_for_date()` (lines 100-107) :
- Préfère `ensemble_v1_softgate_wrapper` si row existe pour `(date, contract_id)`
- Fallback à `legacy` sinon
- Cache 5min par tuple

→ **Tant que `cc-ensemble-compute` écrit, le dashboard sert ensemble**. Indépendant de `is_active` flag.

### 6.2 Endpoints qui exposent l'ensemble

| Endpoint | Champ ensemble exposé |
|---|---|
| `GET /v1/dashboard/position-status` | `decision`, `source_algorithm`, `running_acc_5d` |
| `GET /v1/dashboard/indicators-grid` | z-scores depuis l'algo résolu |
| `GET /v1/dashboard/recommendations` | `conclusion` parsée |
| `GET /v1/dashboard/ensemble-diagnostics?date=...` | **Tous les 25+ champs d'orchestrator** + 14 specialists |
| `GET /v1/dashboard/audio?version=ensemble` | Audio NotebookLM brief ensemble (dual-track) |

### 6.3 Composants frontend consommateurs

- `SignalHero` : affiche `running_acc_5d` dans le score panel (compass-formula computed)
- `DecisionExplainerCard` : utilise `useEnsembleDiagnostics()` pour expliquer la décision
- `LiveSignalStrip`, `MarketAnalysis` : utilisent `usePositionStatus()` qui include `source_algorithm`

### 6.4 YTD performance (déjà mixe ensemble + legacy)

`calculate_ytd_performance()` (dashboard_service.py:260-370) :
- Pour chaque date depuis début d'année : `COALESCE(ensemble.decision, legacy.decision)`
- Horizon J+4 (`YTD_EVAL_HORIZON_DAYS = 4`)
- Scoring : `+1.25` si OPEN bien direction, `+1.0` si HEDGE bien direction, `-2×` si contre-direction

→ Le YTD est **déjà ensemble-first**. Si ensemble n'a pas de row sur une date (cold start), fallback à legacy.

---

## 7 — Brief ensemble (dual-track avec legacy)

> Voir [docs/runbooks/brief-dual-track.md](../runbooks/brief-dual-track.md) pour les opérations détaillées

### Pourquoi un nouveau brief ?

Le brief legacy parle d'« aujourd'hui » (horizon T+1). L'ensemble parle d'une **fenêtre 4-5 jours** roulante avec persistence + triggers de réévaluation. C'est un changement de cadence narrative qui nécessite un nouveau template.

### Architecture en 2 jobs

```
19:18  cc-ensemble-compute     → row ensemble pl_indicator_daily + orchestrator + 14 specialists
19:25  cc-ensemble-explainer   → invoque DBAnalysisEngine (auto-align) → UPDATE row ensemble : eco + confidence + direction + conclusion long-form (2 LLM calls gpt-4-turbo)
19:35  cc-compass-brief-ensemble → Drive: YYYYMMDD-CompassBrief-Ensemble.txt
```

### Template du brief ensemble (7 sections)

> Code : [backend/scripts/compass_brief_ensemble/brief_generator.py](../../backend/scripts/compass_brief_ensemble/brief_generator.py)

```
═══ COMPASS DAILY BRIEF — Cocoa Outlook (Ensemble v1.0.0) ═══
Date : <target_date>
Horizon décisionnel : 4-5 trading days (J+4-J+5)

I — SIGNAL ENSEMBLE
   Position           : OPEN | HEDGE | MONITOR (decision_wrapped)
   Confiance          : 4/5 (LLM-judged contextuel)
   Direction          : haussière modérée
   Persistence        : biais maintenu depuis 3 jour(s)
   Triggers de réévaluation : anomaly_z > 2.5, dispersion fire, sentiment shift > 1.5σ

II — DÉCOMPOSITION 14 SPÉCIALISTES
   Cluster Winter (TB/FX)        : +3  ↗ bullish
   Cluster Spring (macro/ENSO)   : +2  ↗ bullish
   Specialists committed         : 11/14
   Désaccord notable             : xpol_W_TB_garch (vote HEDGE)
   Tableau détaillé              : <14 rows specialist_name | vote | window_months | cluster>

III — MACRO RADAR ENSEMBLE
   Macro direction               : +1 (depuis sentiment features)
   Surprise macro                : 0.420σ (half_life 4 jours)
   Anomaly score                 : 0.40 (normal)
   Prior structurel              : P(OPEN)=0.510 P(HEDGE)=0.210 P(MONITOR)=0.280
   Wrapper actif                 : non (soft-gate disait OPEN)
   Detectors fired               : run_acc=non dispersion=non trend=non 3way=non
   Running acc 5d (Compass)      : 0.9100 | Realized return 5d : 0.0212

IV — ÉCO & PRESS REVIEW (LECTURE HUMAINE)
   <eco narrative LLM ~150 mots croisant press_review + diagnostics ensemble>
   <press summary brut>

V — WEATHER WATCH
   <résumé meteo Côte d'Ivoire / Ghana, inchangé du legacy>

VI — CHIFFRES TECHNIQUES DERNIÈRE SESSION
   <bloc OHLCV+pivots+Bollinger>

VII — RECOMMANDATIONS OPÉRATIONNELLES
   <3 alertes "À SURVEILLER" en lien avec triggers ensemble>
```

### Différences sections avec brief legacy

| Section | Legacy | Ensemble | Source des données |
|---|---|---|---|
| I — Signal | yesterday + today | **persistence + triggers réévaluation** | `pl_orchestrator_decision` + lookback |
| II — Specialists | (absent) | **NOUVEAU** — 14 votes décomposés + clusters | 14× `pl_specialist_prediction` |
| III — Macro radar | (absent) | **NOUVEAU** — anomaly + priors + wrapper | `pl_orchestrator_decision` |
| IV — Éco narrative | LLM Call #1 | LLM Explainer (1 call, plus riche) | `pl_indicator_daily.eco` (enrichi) |
| V — Weather | identique | identique | `pl_weather_observation` |
| VI — Technicals | yesterday + today | dernière session uniquement | `pl_contract_data_daily` |
| VII — Recommendations | LLM Call #2 (3 alertes) | LLM Explainer (3 alertes liées aux triggers) | `pl_indicator_daily.conclusion` |

### LLM Explainer (wrapper sur DBAnalysisEngine, refactor 2026-05-27)

> Code : [backend/scripts/ensemble_explainer/main.py](../../backend/scripts/ensemble_explainer/main.py) (≤200 lignes, juste un thin wrapper)

Le job ne contient PLUS de prompt / parser / writer custom. Il :
1. Calcule `data_date = previous_session(target_date)` (semantic P2b).
2. Pre-flight : vérifie qu'une row ensemble existe dans `pl_indicator_daily` pour `data_date` (fail-loud `EnsembleRowMissingError` sinon).
3. Instancie `DBAnalysisEngine(session)` **sans `algorithm_version_name`** → l'auto-align kick in (db_analysis_engine.py:187-200).
4. L'engine fait 2 appels `gpt-4-turbo` avec les prompts legacy (`CALL_1_PROMPT` macro/weather + `CALL_2_PROMPT_ENSEMBLE` avec les 25 champs de diagnostics ensemble injectés) et écrit la narrative sur la row ensemble.

- **Modèle** : `gpt-4-turbo` × 2 calls/jour (~$0.13/jour) — partage exactement le pipeline du brief legacy.
- **La décision est IMMUTABLE** : `CALL_2_PROMPT_ENSEMBLE` force `decision = decision_wrapped`, le format JSON l'impose, et `db_analysis_engine.run()` ré-écrase si le LLM dérive (`_force_alignment_if_drifted`).
- **Format conclusion** : long-form legacy `> opening • bullets > A SURVEILLER AUJOURD'HUI: • alert1 • alert2 • alert3` — strictement identique au brief legacy, donc le parser frontend (`split3 + parseConclusion`) bucketise correctement les 3 tabs Recommandation / Supply & Momentum / Technical Outlook.

**Pourquoi cette refonte** : la version initiale (gpt-4o-mini + custom prompt court) produisait 388 chars + 1 « À SURVEILLER » inline → le frontend split3 ne trouvait rien à bucketiser → 2 tabs sur 3 vides. Voir [docs/runbooks/brief-rollback-procedure.md](../runbooks/brief-rollback-procedure.md) pour les scénarios opérationnels.

---

## 8 — Exemple complet de décision ensemble (annoté)

Date hypothétique : 2026-05-22 (vendredi, dernier trading day avant weekend).

### Inputs lus
- 600d OHLCV chained pour CAK26
- `pl_article_segment` 90d window, confidence ≥0.70 → MacroEventLayer signal direction=-1, surprise=+0.373σ
- 14 specialists infer chacun depuis leurs features

### Votes des 14 spécialistes

| Specialist | Cluster | Window | Vote | Note |
|---|---|---|---|---|
| `exp_optim_002` | Winter | 12m | HEDGE | TB baseline |
| `exp_optim_005` | Winter | 12m | HEDGE | TB + FX |
| `exp_optim_008` | Winter | 12m | MONITOR | TB + COT |
| `exp_optim_011` | Spring | 12m | HEDGE | Top scorer ENSO+FX+macro |
| `xpol_W_TB_garch` | Winter | 24m | HEDGE | TB + GARCH |
| `xpol_W_TB_garch_macro` | Winter | 24m | HEDGE | TB + GARCH + macro |
| `xpol_S_macro_combined` | Spring | 12m | HEDGE | Macro events |
| `macro_combined_spring` | Spring | 12m | MONITOR | Pas committed |
| `xpol_S_bear_garch_macro` | Spring | 24m | HEDGE | Spring bearish bias |
| ... (5 autres) | mix | 12-24m | HEDGE or MONITOR | |

→ Consensus : majorité HEDGE.

### Soft-gate output

```
soft_gate_decision      = HEDGE
net_score               = -0.2345
weights_sum             = 0.8234
n_committed_specialists = 11
winter_vote_signed      = -4 (4 HEDGE - 0 OPEN dans Winter committed)
spring_vote_signed      = -3 (3 HEDGE - 0 OPEN dans Spring committed)
```

### Wrapper diagnostics

```
fired_running_acc   = False (running_acc_5d récente = 0.78, sain)
fired_trend         = False (off in v1.0.0)
fired_dispersion    = False (11/14 committed = consensus suffisant)
fired_three_way     = False (off in v1.0.0)

→ Aucun détecteur fire
→ wrapper_active    = False
→ decision_wrapped  = HEDGE  (= soft_gate_decision)
```

### Autres diagnostics

```
running_acc_5d        = 0.7800
realized_return_5d    = -0.0124  (le gate a perdu un peu sur 5 jours)
anomaly_score_z       = 0.45    (régime normal)
macro_direction       = -1      (bearish depuis sentiment features)
macro_surprise        = 0.373σ
macro_half_life_days  = 5
prior_open            = 0.45
prior_hedge           = 0.32
prior_monitor         = 0.23
```

### LLM Explainer output (wrapper sur DBAnalysisEngine, gpt-4-turbo × 2 calls)

Exemple réel sur 2026-05-26 (HEDGE, 3 spécialistes engagés sur 14, conviction nette) :

```text
> 3 spécialistes sur 14 confirment la position HEDGE, conviction forte (net_score -1.000).
        • CLOSE aujourd'hui à 3153 contre 2860 hier, indiquant une hausse significative mais potentiellement éphémère.
        • VOLUME aujourd'hui à 7992, hier à 6867, montrant un engagement croissant des traders.
        • OPEN INTEREST a légèrement augmenté à 43182 aujourd'hui contre 42996 hier.
        • Le RSI est à 64.75, suggérant une surachat possible.
        • MACD à -35.90 aujourd'hui contre -61.09 hier, dynamique baissière qui s'atténue.
        • La volatilité implicite a diminué à 0.43 contre 0.45 — moins d'incertitude.
        • Le STOCK EU a augmenté de 189288 à 192176, ce qui pourrait indiquer une pression baissière.
> A SURVEILLER AUJOURD'HUI:
        • Baissier si CLOSE clôture sous SUPPORT 1 à 2900 — objectif S2 à 2700.
        • Haussier si CLOSE dépasse RESISTANCE 1 à 3291 — confirmation de tendance haussière.
        • Baissier si RSI passe sous 60 (actuellement à 64.75) — accélération de la pression vendeuse.
```

Et `eco` en parallèle (Call#1 macro/weather) :
```
"Anticipation d'augmentation de la production ivoirienne en 2025/26, mais sécheresse persistante au Ghana modère l'optimisme baissier."
```

JSON shape identique au brief legacy : `{decision, confiance, direction, conclusion}` côté Call#2 + `{macroeco_bonus, eco}` côté Call#1. Le validator strict de l'engine refuse toute conclusion contenant un mot opposé à la decision (e.g. « acheter » si HEDGE).

### Pl_indicator_daily ensemble row écrite

```sql
UPDATE pl_indicator_daily SET
  decision        = 'HEDGE'        -- depuis decision_wrapped (immutable)
  conclusion      = '<texte LLM>'  -- depuis Explainer
  eco             = '<eco LLM>'    -- depuis Explainer
  confidence      = 4              -- depuis Explainer
  direction       = 'BAISSIERE'    -- depuis Explainer
WHERE date='2026-05-22' AND contract_id=<CAK26> AND algorithm_version_id=<ensemble_id>;
```

### Brief Drive uploaded

`20260526-CompassBrief-Ensemble.txt` (target_date = next trading day, lundi férié → mardi 26) contient les 7 sections rendues depuis cette row + les 14 specialists.

---

## 9 — Forces et limites détaillées

### Forces

**Quantitative fitness measurable** : `running_acc_5d`, `realized_return_5d`, YTD scoring → on PEUT répondre « le gate a 78% d'accuracy sur 5 jours ». Impossible avec legacy LLM.

**14 angles indépendants** : si TB baseline est trompé par un régime shift, GARCH variants ou Spring cluster compensent. Robustesse statistique.

**Audit trail riche** : 25 champs structurés expliquent la décision. Reproductible bit-à-bit (modulo le LLM Explainer optionnel).

**Multi-horizon** : J+4-J+5 → on capture les biais structurels (ENSO, COT positioning) que T+1 LLM ne voit pas.

**Cost LLM** : la dual-track narrative (legacy + ensemble) coûte ~2× le legacy = ~$0.26/jour (4 calls gpt-4-turbo). Le refactor 2026-05-27 a abandonné l'option gpt-4o-mini ($0.001/jour) pour pouvoir réutiliser le prompt legacy verbatim et garantir la parité de format avec le frontend recommandation parser.

**Frontend déjà branché** : dashboard sert ensemble depuis migration `_resolve_algo_for_date()`. Le brief dual-track est le dernier morceau de transition.

### Limites

**Cold-start NaN** : `running_acc_5d` est NaN les 5 premiers jours après retraining mensuel (pas assez de votes ensemble pour computer accuracy). Compass override gère via `OR NaN` clause.

**Dépendance artifacts BYTEA** : 38 artifacts BYTEA stockés dans `pl_model_artifact` (SHA-256 verified). Si la table est corrompue → l'ensemble ne peut plus tourner. Mitigation : runbook `cc-ensemble-bootstrap-artifacts` pour re-seed.

**Retraining mensuel** : nécessite que la R&D livre une nouvelle version mensuelle. Process documenté dans `CAMPAIGN_5_PROD_DEPLOYMENT.md`.

**Pas de narrative native** : sans le LLM Explainer, la décision est juste un label. Le brief ensemble repose sur l'Explainer (= wrapper du pipeline legacy) pour la narrative audio-friendly.

**Hardcoded clusters dans brief_generator** : la classification specialist_name → Winter/Spring est heuristique via `_WINTER_TAGS`/`_SPRING_TAGS`. Si R&D renomme un spécialiste, on doit mettre à jour.

**LLM Explainer hallucinations possibles** : ~1 brief sur 100 pourrait avoir un détail factuellement faux. Validator strict bloque les contradictions mais pas les hallucinations subtiles.

**`compute_enabled` flag non respecté** : le code `cc-ensemble-compute` ignore `pl_algorithm_version.compute_enabled` — il tourne quoi qu'il arrive. À nettoyer ou à coder explicitement.

---

## 10 — Liens cross-référence vers le code

| Section doc | Fichier code |
|---|---|
| 2-3 specialists + soft-gate | [backend/vendor/campaign5_ensemble_v1.0.0/](../../backend/vendor/campaign5_ensemble_v1.0.0/) (R&D vendored, read-only) |
| 4 Compass wrapper | [backend/scripts/ensemble_compute/compass_wrapper.py](../../backend/scripts/ensemble_compute/compass_wrapper.py) |
| 5 Diagnostics schema | [backend/app/models/pipeline.py](../../backend/app/models/pipeline.py) (`PlOrchestratorDecision`, `PlSpecialistPrediction`) |
| 6 Frontend integration | [backend/app/services/dashboard_service.py](../../backend/app/services/dashboard_service.py), [endpoints/dashboard.py](../../backend/app/api/api_v1/endpoints/dashboard.py), [services/ensemble_diagnostics_service.py](../../backend/app/services/ensemble_diagnostics_service.py) |
| 7 Brief ensemble | [backend/scripts/ensemble_explainer/main.py](../../backend/scripts/ensemble_explainer/main.py) (wrapper sur DBAnalysisEngine), [backend/scripts/daily_analysis/db_analysis_engine.py](../../backend/scripts/daily_analysis/db_analysis_engine.py) (engine + auto-align), [backend/scripts/daily_analysis/prompts.py](../../backend/scripts/daily_analysis/prompts.py) (`CALL_2_PROMPT_ENSEMBLE`), [backend/scripts/compass_brief_ensemble/](../../backend/scripts/compass_brief_ensemble/) |
| Bootstrap artifacts | [backend/scripts/ensemble_bootstrap/main.py](../../backend/scripts/ensemble_bootstrap/main.py), [docs/runbooks/ensemble-failure-recovery.md](../runbooks/ensemble-failure-recovery.md) |

---

## 11 — Liens vers les autres docs architecture

- [ENSEMBLE_BRIDGE_FROM_LEGACY.md](./ENSEMBLE_BRIDGE_FROM_LEGACY.md) — **pont de lecture LEGACY → ENSEMBLE** : ce qui change, journée annotée, **carte des leviers tunables** (30 params `pl_algorithm_config` + LLM + env vars), 4 scénarios de décision avec dates réelles
- [PIPELINE_LEGACY.md](./PIPELINE_LEGACY.md) — pipeline LLM legacy qui tourne en parallèle (dual-track)
- [JOBS_AND_SCRAPERS.md](./JOBS_AND_SCRAPERS.md) — catalogue exhaustif des jobs/scrapers anciens et nouveaux
- [docs/runbooks/brief-dual-track.md](../runbooks/brief-dual-track.md) — opérations du brief ensemble
- Pour tuner les prompts ensemble : éditer `CALL_1_PROMPT` (macro/weather) et `CALL_2_PROMPT_ENSEMBLE` (decision avec diagnostics) dans [backend/scripts/daily_analysis/prompts.py](../../backend/scripts/daily_analysis/prompts.py) — ce sont les mêmes prompts que cc-daily-analysis legacy utilise, donc toute modification affecte les 2 tracks.
- [docs/runbooks/brief-ensemble-evolution.md](../runbooks/brief-ensemble-evolution.md) — comment ajouter des sections au brief
- [docs/runbooks/ensemble-failure-recovery.md](../runbooks/ensemble-failure-recovery.md) — récupération en cas de panne ensemble
- [docs/onboarding/CAMPAIGN_5_PROD_DEPLOYMENT.md](../onboarding/CAMPAIGN_5_PROD_DEPLOYMENT.md) — déploiement initial Campaign 5
- [docs/onboarding/HEDI_DATA_MAP.md](../onboarding/HEDI_DATA_MAP.md) — détail des features par spécialiste
