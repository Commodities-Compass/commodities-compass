# ENSEMBLE — Bridge depuis le pipeline LEGACY

> **À qui s'adresse ce document.** Tu connais déjà le pipeline LEGACY (`cc-daily-analysis` + `cc-compass-brief`) — un LLM lit 42 technicals, presse et météo, sort une décision T+1, et un brief NotebookLM est généré. Ce document explique **ce qui change avec ENSEMBLE v1.0.0** et te donne **la carte des leviers** qu'on peut tourner au quotidien. Mix lecteur technique et business : la prose est accessible, les détails code sont en annexes.
>
> **Pré-requis de lecture** : avoir parcouru au moins le §1 de [PIPELINE_LEGACY.md](./PIPELINE_LEGACY.md). Pour le détail exhaustif, ce doc renvoie vers [PIPELINE_ENSEMBLE.md](./PIPELINE_ENSEMBLE.md) — il ne le remplace pas, il fait le pont.
>
> **Statut 2026-05-27.** Les deux pipelines tournent en parallèle (dual-track briefs). Dashboard et audio basculent progressivement vers ENSEMBLE. La transition n'a pas de date butoir — elle sera complète quand les utilisateurs auront validé en confiance.

---

## 1 — La même question, deux façons d'y répondre

### 1.1 La question business commune

> « Étant donné les conditions actuelles du marché cocoa Londres, quelle position recommander, dans quelle direction, avec quelle conviction, et pourquoi ? »

LEGACY et ENSEMBLE répondent à la même question. Ils n'ont juste pas la même **stack de raisonnement** ni le même **horizon temporel**.

### 1.2 Ce que répond LEGACY (rappel express)

Un LLM `gpt-4-turbo` fait deux appels : (1) un score macro/météo (`macroeco_bonus ∈ [-0.10, +0.10]`), (2) une décision T+1 (`OPEN/HEDGE/MONITOR` + confiance 1-5 + direction + narratif). Un moteur déterministe parallèle calcule un `final_indicator` à partir de 6 z-scores rolling 252j et d'une power formula, et passe ce score en input au LLM. Le LLM décide. Audit qualitatif uniquement.

### 1.3 Ce que répond ENSEMBLE

**14 spécialistes propriétaires** entraînés en machine learning sur 10 ans de cocoa votent indépendamment OPEN / HEDGE / MONITOR. Un **soft-gate Bayésien** agrège les voix engagées avec des poids structurels (macro, anomaly, priors). Un **wrapper** à 2 détecteurs actifs peut vetoer la décision si la confiance récente est faible ou si le panel est en désaccord — un override Compass relâche le veto dispersion-seul quand l'accuracy 5j est bonne. Le LLM legacy est conservé **uniquement pour produire la narrative humaine** (eco + conclusion) — il ne décide plus rien.

### 1.4 Diff en 1 coup d'œil

| Dimension | LEGACY | ENSEMBLE v1.0.0 |
|---|---|---|
| **Qui décide** | Un LLM `gpt-4-turbo` (Call #2) | 14 modèles ML → soft-gate Bayésien → wrapper |
| **Horizon métier** | T+1 (la prochaine session) | J+4-J+5 (fenêtre 5 jours, biais persistant) |
| **Mesurabilité de la qualité** | Non — pas de métrique récurrente | **Oui** — `running_acc_5d`, `realized_return_5d`, YTD score Compass |
| **Audit trail** | 4 champs texte LLM | **25 champs structurés** dans `pl_orchestrator_decision` + 14 votes dans `pl_specialist_prediction` |
| **Reproductibilité** | LLM stochastique (T+1 différent à chaque retry) | Modèles déterministes (modulo LLM narrative) |
| **Inputs structurés** | 42 technicals + texte presse/météo (~3-4 K tokens) | 600j OHLCV chained + 27 indicators + ENSO + FX + COT + sentiment features |
| **Coût LLM/jour** | $0.13 (2 calls) | $0.13 (2 calls, mêmes prompts, dual-track) |
| **Robustesse OpenAI down** | Brief perdu si outage 19:00-19:30 UTC | Décision toujours produite ; seule la narrative est perdue |
| **Cold start** | Aucun | 5 jours après chaque retraining mensuel, `running_acc_5d` est NaN |
| **Performance prod Jan-Mai 2026** | non mesurée | 92.5% hit-rate @ J+4 / 48.96% coverage / 98.62% YTD Compass |

> **À retenir.** ENSEMBLE n'est pas « plus intelligent » que LEGACY. Il est **mesurable**, **plus diversifié dans ses hypothèses**, et **opère sur un horizon différent**. LEGACY garde l'avantage du contexte qualitatif (un LLM lit la presse comme un humain). C'est pour ça que les deux tournent en parallèle.

---

## 2 — La nouvelle architecture en 1 diagramme

### 2.1 Schéma unifié — qui produit quoi, et quand

```
┌──────────────── Phase A — Marché clos (T, weekdays 18:30-19:15 UTC) ────────────────┐
│                                                                                     │
│   18:30  cc-fx-scraper          → pl_external_indicator (FX ECB)                    │
│   19:00  cc-barchart-scraper    → pl_contract_data_daily (OHLCV+IV)                 │
│   19:05  cc-ice-stocks-scraper  → pl_contract_data_daily.stock_us                   │
│   19:05  cc-cftc-scraper        → pl_contract_data_daily.com_net_us                 │
│   19:10  cc-barchart-stocks-eu  → pl_contract_data_daily.stock_eu_bags60kg          │
│   19:15  cc-compute-indicators  → pl_derived_indicators (27)                        │
│                                  + pl_indicator_daily (z-scores numerics, 2 rows)   │
│                                                                                     │
└──────────────────────────────────┬──────────────────────────────────────────────────┘
                                   │
   ┌───────────────────────────────┴───────────────────────────────┐
   │                                                               │
   ▼ LEGACY track                                                  ▼ ENSEMBLE track
                                                                   │
   19:00 cc-meteo-agent ────┐                                      │
   19:05 cc-press-review ───┤                                      │
                            │                                      │
   19:20 cc-daily-analysis  │ LLM Call#1 (macro/weather)           │ 19:18 cc-ensemble-compute
        --algo legacy       │ LLM Call#2 (decision T+1)            │   ┌─ lit 600j OHLCV chained
        │                   │   ↓                                  │   │  + features macro
        │                   │ UPDATE pl_indicator_daily            │   │  + 38 artifacts BYTEA
        │                   │   row LEGACY                         │   │
        │                   │   (decision, confidence, direction,  │   ├─ 14 spécialistes votent
        │                   │    eco, conclusion, final_indicator) │   ├─ soft-gate Bayésien
        │                   │                                      │   │  → soft_gate_decision
        │                   │                                      │   ├─ wrapper Compass
        │                   │                                      │   │  → decision_wrapped
        │                   │                                      │   ▼
        │                   │                                      │ INSERT
        │                   │                                      │ • 14× pl_specialist_prediction
        │                   │                                      │ • 1× pl_orchestrator_decision
        │                   │                                      │ • 1× pl_indicator_daily (ensemble row)
        │                   │                                      │
        │                   │                                      │ 19:25 cc-ensemble-explainer
        │                   │                                      │   ┌─ ★ POINT NON-OBVIOUS ★
        │                   │  ┌───────────────────────────────────┼───┤  invoque DBAnalysisEngine
        │                   │  │ Même code, même prompts,          │   │  SANS pinner sur legacy
        │                   │  │ même LLM gpt-4-turbo              │   │  → auto-align détecte la row
        │                   │  │ → narrative legacy-style sur les  │   │    ensemble dans
        │                   │  │   2 rows pl_indicator_daily       │   │    pl_orchestrator_decision
        │                   │  │                                   │   │  → UPDATE row ENSEMBLE :
        │                   │  └───────────────────────────────────┼───┤    eco + confidence
        │                   │                                      │   │    + direction + conclusion
        ▼                   ▼                                      │   │  (decision IMMUTABLE
   19:30 cc-compass-brief   pl_indicator_daily LEGACY row ready    │   │   = decision_wrapped)
        │                                                          ▼   ▼
        ▼                                                       19:35 cc-compass-brief-ensemble
   YYYYMMDD-CompassBrief.txt        Drive       YYYYMMDD-CompassBrief-Ensemble.txt
        │                                                              │
        └──────────────────── NotebookLM ──────────────────────────────┘
                                   │
                                   ▼
                          2 audios (legacy + ensemble)
                                   │
                                   ▼
                          Frontend dashboard
                          • _resolve_algo_for_date() → ensemble si row existe
                          • /v1/dashboard/audio?version=ensemble (override)
                          • BRIEF_DEFAULT_VERSION env var pilote le default
```

### 2.2 Le point non-obvious : ENSEMBLE réutilise le moteur LLM de LEGACY

Avant le refactor 2026-05-27, le job `cc-ensemble-explainer` avait son propre prompt court (`gpt-4o-mini`, ~388 chars de sortie) et son propre parser. Résultat : narrative trop pauvre, format incompatible avec le frontend recommandation parser, 2 onglets sur 3 vides.

**Depuis le refactor**, `cc-ensemble-explainer` est un **thin wrapper de ~200 lignes** ([backend/scripts/ensemble_explainer/main.py](../../backend/scripts/ensemble_explainer/main.py)) qui invoque [`DBAnalysisEngine.run()`](../../backend/scripts/daily_analysis/db_analysis_engine.py) — exactement le moteur du legacy — **sans pinner `algorithm_version_name`**. L'auto-align dans `db_analysis_engine.py:187-200` détecte la row ensemble présente dans `pl_orchestrator_decision`, injecte les 25 champs de diagnostics via [`CALL_2_PROMPT_ENSEMBLE`](../../backend/scripts/daily_analysis/prompts.py), et écrit la narrative sur la row ensemble. Le LLM ne peut **pas** changer la décision : `_force_alignment_if_drifted` ré-écrase si jamais il dérive du `decision_wrapped`.

**Conséquence opérationnelle** : un seul code à maintenir pour les deux narratives. Quand tu modifies `CALL_2_PROMPT_ENSEMBLE`, les deux briefs en bénéficient. Voir annexe D pour le détail mécanique.

---

## 3 — Une journée dans la vie d'une décision ENSEMBLE

Date prise comme exemple : **mardi 26 mai 2026** (session réelle, données issues de la prod via bastion IAP read-only). Le brief en sortie : [tmp/20260527-CompassBrief-Ensemble-rework.txt](../../tmp/20260527-CompassBrief-Ensemble-rework.txt).

### 3.1 18:30 UTC — Les inputs structurés arrivent

Le scraper `cc-fx-scraper` pousse les FX (DXY proxy, GBP/USD) sur `pl_external_indicator`. Les autres scrapers (Barchart, ICE, CFTC, Stocks EU) feront leur travail dans la demi-heure qui suit. Tout cela alimente la même table `pl_contract_data_daily` que LEGACY connaît déjà.

### 3.2 19:15 — Le moteur déterministe calcule (commun aux deux tracks)

`cc-compute-indicators` lit 252+ jours d'OHLCV, calcule les 27 indicators dérivés, applique smoothing 5j + z-score rolling 252j, et écrit **deux rows** dans `pl_indicator_daily` (une par algorithm_version `enabled`) : la row LEGACY et la row ENSEMBLE. À ce stade ce sont les **mêmes z-scores** des deux côtés — seul le composite `final_indicator` diffère (puisque les params power-formula peuvent différer par version).

### 3.3 19:18 — Les 14 spécialistes votent (extrait section II du brief)

`cc-ensemble-compute` charge les 38 artifacts ML (BYTEA, SHA-256 vérifié) depuis `pl_model_artifact`, fait inférer chaque spécialiste, et écrit 14 rows dans `pl_specialist_prediction`. Pour le 26 mai :

| Vote | Spécialiste (libellé business) | Cluster | Pourquoi il s'engage |
|---|---|---|---|
| HEDGE | Sentinelle baissière FX | Spring | Mouvement GBP/USD baissier |
| HEDGE | Stratège haussier FX | Spring | Vote rare → poids signalant |
| HEDGE | Lecteur de tendance contextualisé macro | Winter | ENSO + FX renforcent le baissier technique |
| (silencieux) | 11 autres spécialistes | — | Signal jugé trop faible |

Seulement **3/14 engagés** — c'est peu. Mais quand les 3 vont dans le même sens (HEDGE), le net_score est tranché : **-1.000**.

### 3.4 19:18 (suite) — Soft-gate Bayésien agrège

Le soft-gate pondère les 3 votes engagés par leur perf récente × macro × anomaly × priors. Output sur `pl_orchestrator_decision` :

```
soft_gate_decision       = HEDGE
net_score                = -1.000          ← consensus dur
weights_sum              = (computed)
n_committed_specialists  = 3
winter_vote_signed       = -1              (1 Winter HEDGE)
spring_vote_signed       = -2              (2 Spring HEDGE)
anomaly_score_z          = 1.68            (élevé mais < 2.5 clip)
prior_open               = 0.510
prior_hedge               = 0.486
prior_monitor             = 0.005          ← prior structure quasi-nul
```

### 3.5 19:18 (fin) — Wrapper Compass

Les 4 détecteurs sont évalués. En prod, **seuls 2 sont actifs** (cf. config-as-data §6) :

```
fired_running_acc   = False  (running_acc_5d = NaN — cold start retraining, default-allow)
fired_dispersion    = False  (3 committed mais consensus clair, pas de désaccord)
fired_trend         = (off en v1.0.0, détecteur B désactivé)
fired_three_way     = (off en v1.0.0, détecteur D désactivé)

→ Aucun détecteur fire
→ wrapper_active     = False
→ decision_wrapped   = HEDGE  (= soft_gate_decision)
```

### 3.6 19:25 — cc-ensemble-explainer enrichit la narrative

Le job invoque `DBAnalysisEngine.run()` sans pinner. L'auto-align voit la row ensemble dans `pl_orchestrator_decision`, route vers `CALL_2_PROMPT_ENSEMBLE` qui injecte les 25 champs de diagnostics dans le prompt. Sortie LLM → UPDATE sur la row ENSEMBLE de `pl_indicator_daily` :

```
decision     = 'HEDGE'        (immutable, pinné sur decision_wrapped)
confidence   = 3.00           (jugée par le LLM relecteur)
direction    = 'BAISSIERE'
eco          = "Anticipation d'augmentation de la production ivoirienne en 2025/26,
                mais sécheresse au Ghana menace la production locale."
conclusion   = "> 3 spécialistes sur 14 confirment la position HEDGE, conviction
                forte (net_score -1.000).
                  • CLOSE aujourd'hui à 3153 contre 2860 hier…
                  • RSI à 64.75, suggérant une surachat possible…
                > A SURVEILLER AUJOURD'HUI:
                  • Baissier si CLOSE clôture sous SUPPORT 1 à 2900…
                  • Haussier si CLOSE dépasse RESISTANCE 1 à 3291…
                  • Baissier si RSI passe sous 60…"
```

Format strictement identique au brief LEGACY (`> opening • bullets > A SURVEILLER AUJOURD'HUI: • alert1 • alert2 • alert3`) — c'est ce qui permet au parser frontend (`split3 + parseConclusion`) de bucketiser correctement les 3 onglets Recommandation / Supply & Momentum / Technical Outlook.

### 3.7 19:35 — Le brief ensemble est uploadé sur Drive

`cc-compass-brief-ensemble` lit la row ENSEMBLE + les 14 specialists + l'orchestrator + press/meteo, applique les 7 formatters de [brief_generator.py](../../backend/scripts/compass_brief_ensemble/brief_generator.py), et upload `20260527-CompassBrief-Ensemble.txt` (filename ancré sur `session_date` = 2026-05-26, display_date = 2026-05-27).

### 3.8 Overnight — NotebookLM produit l'audio

NotebookLM ingère le `.txt`, applique le [prompt podcast v2](../runbooks/podcast-prompt-ensemble.md) (vocabulaire « spécialistes propriétaires », jamais « experts IA »), produit `20260527-CompassAudio-Ensemble.{wav,m4a,mp4}` sur Drive.

### 3.9 J — Le frontend route automatiquement

À l'ouverture du dashboard le 2026-05-27 :
- `_resolve_algo_for_date('2026-05-26')` voit qu'une row ensemble existe → bascule en mode ensemble pour tous les endpoints (`/position-status`, `/indicators-grid`, `/recommendations`, `/chart-data`, `/ensemble-diagnostics`).
- `/v1/dashboard/audio` lit `BRIEF_DEFAULT_VERSION` (`legacy` par défaut aujourd'hui), ou le `?version=ensemble` query param, et sert l'audio correspondant.
- `useEnsembleDiagnostics()` hook expose les 25 champs de l'orchestrateur dans `DecisionExplainerCard`.

> **Si le pipeline ENSEMBLE crashe.** `cc-ensemble-compute` fail-loud à 19:18 → pas de row ensemble dans `pl_orchestrator_decision`. Conséquence en chaîne : `cc-ensemble-explainer` fail (`EnsembleRowMissingError`), `cc-compass-brief-ensemble` fail. Le dashboard fallback automatiquement vers la row LEGACY via `_resolve_algo_for_date()`. L'audio reste legacy. **Aucune panne utilisateur visible** — c'est l'avantage du dual-track. Procédure de relance : [ensemble-failure-recovery.md](../runbooks/ensemble-failure-recovery.md).

---

## 4 — Les 14 spécialistes — qui décide quoi

### 4.1 La table de référence (business + technique)

Source de vérité éditoriale : [backend/scripts/compass_brief_ensemble/specialist_catalog.py](../../backend/scripts/compass_brief_ensemble/specialist_catalog.py). Code R&D : [docs/runbooks/podcast-prompt-ensemble.md](../runbooks/podcast-prompt-ensemble.md). Cluster mapping en prod : `pl_algorithm_config` (14 rows `cluster_*`).

| Tech ID (R&D) | Code | Libellé business | Cluster | Horizon | Biais | Ce qu'il surveille |
|---|---|---|---|---|---|---|
| exp_optim_002 | W1 | Lecteur de tendance — référence | Winter | 6j | neutre | Triple-Barrière calibrée sur 10 ans cocoa — pilier technique du panel |
| exp_optim_005 | W2 | Lecteur de tendance volatilité-conditionnel | Winter | 6j | neutre | Variante de W1 + modèle de volatilité ; vote plus quand le marché s'agite |
| exp_optim_006 | W3 | Spécialiste cycle long — 3 semaines | Winter | **22j** | neutre | Seul modèle long-horizon ; détecte les retournements lents |
| exp_optim_011 | W4 | Stratège macro global | Winter | 6j | neutre | ENSO + livre/dollar — le top scorer Campaign 4-5 |
| xpol_W_TB_garch | X1 | Lecteur de tendance + ajustement volatilité | Winter | 6j | neutre | TB + GARCH ; double-filtre quand les deux convergent |
| xpol_W_TB_macro | X2 | Lecteur de tendance contextualisé macro | Winter | 6j | neutre | TB + ENSO + FX ; signal quand macro renforce la dynamique technique |
| exp_optim_017_bear_4 | S1 | Sentinelle baissière FX | Spring | 6j | **bearish** | FX-driven, vote rare à l'achat — quand elle parle, c'est pour couvrir |
| exp_optim_017_bear_8 | S2 | Sentinelle baissière macro + FX | Spring | 6j | **bearish** | S1 + ENSO ; n'engage que si FX et stress hydrique se cumulent |
| exp_optim_017_bull_5 | S3 | Stratège haussier baseline (logistique) | Spring | 6j | **bullish** | Approche logistique pure, tranchée |
| exp_optim_017_bull_7 | S4 | Stratège haussier FX renforcé | Spring | 6j | **bullish** | Variante très offensive — poids triple sur les phases de hausse |
| exp_optim_017_bull_8 | S5 | Stratège haussier multi-facteur | Spring | 6j | **bullish** | ~50 dimensions techniques + fondamentales — voix sur signaux mixtes |
| exp_optim_017_bull_4 | S6 | Stratège haussier FX | Spring | 6j | **bullish** | Lit principalement GBP/USD ; vote rare à la couverture |
| xpol_S_bull_garch_fx | X3 | Stratège haussier volatilité-conditionnel FX | Spring | 6j | **bullish** | Biais haussier + GARCH + FX ; tire sur phases haussières peu volatiles |
| xpol_S_bear_garch_macro | X4 | Sentinelle baissière complète | Spring | 6j | **bearish** | Toutes les défenses du panel — voix la plus prudente |

### 4.2 Pourquoi 14 et pas un seul gros modèle

**Diversification d'hypothèses.** Chaque spécialiste répond à une vue partielle du marché — tendance technique pure, FX-driven, volatilité-conditionnel, biais directionnel assumé. Si un seul est trompé par un changement de régime, les autres compensent.

**Calibration dynamique.** Le soft-gate peut pondérer les spécialistes selon leur perf récente. Un spécialiste qui sous-performe 30 jours voit son poids diminuer automatiquement — sans retraining.

**Audit traçable.** Une décision peut se décomposer en : « 11/14 engagés, dont 4 Winter + 5 Spring → consensus solide » ou « 3/14, dont 3 dans le même sens → consensus rare mais clair ». LEGACY ne sait pas faire ça.

### 4.3 Comment le soft-gate les pondère (en une phrase)

`net_score = Σ(perf_30d(s) × cluster_weight × Bayesian_prior × vote(s)) / Σ weights` avec `vote ∈ {-1, 0, +1}` (HEDGE/MONITOR/OPEN). Décision = `arg_max` projeté sur OPEN/HEDGE/MONITOR via les priors structurels et le seuil `commit_threshold = 0.2493`. Détail : annexe A.

### 4.4 Le wrapper Compass — 4 détecteurs, 2 actifs

| Détecteur | Code config | État prod | Quand il fire | Effet |
|---|---|---|---|---|
| Running accuracy | `wrapper_use_running_acc = 1` | **ACTIF** | `running_acc_5d < τ_run` (τ=0.5931, fenêtre 3j) | Force MONITOR |
| Trend conflict | `wrapper_use_trend_conflict = 0` | inactif | (jamais en v1.0.0) | — |
| Cluster dispersion | `wrapper_use_cluster_dispersion = 1` | **ACTIF** | `n_committed_per_cluster < 2` OU clusters opposés | Force MONITOR sauf override |
| Three-way disagreement | `wrapper_use_three_way_disagreement = 0` | inactif | (jamais en v1.0.0) | — |

**Override Compass (la valeur ajoutée vs vendor R&D).** Si **seul** `fired_dispersion` est vrai ET `running_acc_5d ≥ 0.60` (ou NaN), on **relâche** le veto. Threshold tunable : `compass_wrapper_dispersion_with_acc_threshold = 0.60`. Empiriquement sur backfill 2026 : coverage 17% → 49%, accuracy WR 100% → 76%. Code : [compass_wrapper.py](../../backend/scripts/ensemble_compute/compass_wrapper.py). Détail backfill : annexe B.

---

## 5 — Les 4 scénarios de décision (avec dates réelles)

Données issues de `pl_orchestrator_decision` en prod (bastion IAP, read-only, 2026-05-27).

### 5.1 Happy path — consensus, wrapper inactif

**Date : 2026-04-30** — `decision_wrapped = OPEN`

```
soft_gate_decision  = OPEN
decision_wrapped    = OPEN          ← aucun retournement par le wrapper
wrapper_active      = False
net_score           = +1.000
n_committed         = 8/14
winter_vote_signed  = 0             (Winter partagé)
spring_vote_signed  = -6            (Spring dominante — mais bullish-tilted)
running_acc_5d      = 1.000         (le gate a fait 5/5 sur 5j)
anomaly_score_z     = 0.66          (régime normal)
fired_running_acc   = False
fired_dispersion    = False
```

**Lecture business.** 8 voix engagées, le gate a été 5/5 sur les 5 jours précédents. Le panel est cohérent, le wrapper n'intervient pas. Décision finale = `OPEN`. Le brief lira « 8 spécialistes sur 14 confirment la position OPEN, conviction forte ».

### 5.2 Veto wrapper — running_acc effondrée

**Date : 2026-05-14** — `decision_wrapped = MONITOR` (le wrapper a corrigé)

```
soft_gate_decision  = OPEN          ← le soft-gate voulait commit
decision_wrapped    = MONITOR       ← ★ wrapper a vetoé
wrapper_active      = True
net_score           = +1.000        (signal clair côté soft-gate)
n_committed         = 6/14
running_acc_5d      = 0.000         (le gate a perdu 5 fois sur 5j !)
fired_running_acc   = True          ← détecteur A fire
fired_dispersion    = False
```

**Lecture business.** Le soft-gate veut OPEN mais il vient d'enchaîner 5 erreurs consécutives sur les 5 jours précédents. Le wrapper considère que sa confiance est érodée et bascule en MONITOR. C'est le **filet de sécurité** — il préfère ne rien faire que d'engager du capital sur un gate récemment cassé. Le brief lira « MONITOR » et le LLM relecteur expliquera la perte récente.

**Sur la même date, LEGACY a écrit OPEN/BAISSIERE** (direction incohérente avec la décision — bug LLM connu). C'est exactement le type de divergence qui motive le dual-track : ENSEMBLE refuse de commit, LEGACY se contredit. L'utilisateur voit ENSEMBLE par défaut.

### 5.3 Compass override — dispersion seule, run_acc bonne

**Date : 2026-05-01** — `decision_wrapped = HEDGE` (override Compass a relâché le veto)

```
soft_gate_decision  = HEDGE
decision_wrapped    = HEDGE         ← override release : veto NON appliqué
wrapper_active      = False         (false car la décision n'a pas changé)
net_score           = -0.440
n_committed         = 8/14
running_acc_5d      = 1.000         (gate 5/5 récent — TOP confiance)
fired_running_acc   = False
fired_dispersion    = True          ← détecteur C fire SEUL
```

**Lecture business.** Le détecteur dispersion s'est activé (panel divisé), MAIS le gate a fait 5/5 sur 5 jours. Le vendor R&D aurait downgradé en MONITOR (OR pure des détecteurs) — Compass relâche le veto parce que la dispersion solo ne suffit pas quand `running_acc_5d ≥ 0.60`. Décision finale = HEDGE. C'est ce mécanisme qui a remonté la coverage de 17% à 49% sur le backfill 2026.

**Comment ça serait apparu sans l'override Compass.** Le brief aurait dit MONITOR. L'utilisateur n'aurait pas couvert ce jour-là, et la chute du 2 mai aurait été non-protégée.

### 5.4 Cold-start NaN — `running_acc_5d` indisponible

**Date : 2026-05-22** — `decision_wrapped = HEDGE` (default-allow sur NaN)

```
soft_gate_decision  = HEDGE
decision_wrapped    = HEDGE
wrapper_active      = False
net_score           = -1.000
n_committed         = 6/14
running_acc_5d      = NaN           ← pas assez d'historique post-retraining
fired_running_acc   = False         ← NaN → default-allow (ne fire pas)
fired_dispersion    = False
```

**Lecture business.** 5 jours après un retraining mensuel, on n'a pas encore 5 commits évaluables pour calculer `running_acc_5d`. Plutôt que de bloquer tout, le wrapper considère NaN comme « pas de raison de douter » et laisse passer. Le détecteur dispersion reste opérationnel (il n'utilise pas `running_acc_5d`).

**Tunable.** Le comportement « default-allow sur NaN » est volontaire (rule §0 de PIPELINE_ENSEMBLE : NULL ≠ 0.0). On pourrait le changer en « default-deny » via un patch dans `compass_wrapper.py` — décision business : on préfère commit avec moins de filet que ne rien commit du tout pendant 5 jours/mois.

---

## 6 — La carte des leviers (CHEATSHEET)

> **Lecture rapide.** Une ligne = un bouton. Colonnes : nom · localisation · valeur prod 2026-05-27 · range raisonnable · impact attendu · qui peut changer · comment.

### 6.1 Leviers PIPELINE (bascule legacy ↔ ensemble)

| Levier | Localisation | Valeur prod | Range / actions | Impact | Owner | Runbook |
|---|---|---|---|---|---|---|
| `is_active` | `pl_algorithm_version` | legacy=TRUE / ensemble=FALSE | flip atomique via migration | Lecture engine + lecture compass-brief LEGACY | Hedi | [migrations-prod-via-main-only.md](../../.claude/rules/migrations-prod-via-main-only.md) |
| `compute_enabled` | `pl_algorithm_version` | legacy=TRUE / ensemble=FALSE / power10years=TRUE | flip via migration | Active `cc-ensemble-compute` (sans, KeyError 'k' à l'init) | Hedi | (mémoire `project_c5_ensemble_compute_enabled_state`) |
| `BRIEF_DEFAULT_VERSION` | Cloud Run env var (backend service) | `"legacy"` | `"legacy"` ou `"ensemble"` | Pilote `/v1/dashboard/audio` par défaut (utilisateur sans `?version=`) | Hedi | [brief-dual-track.md](../runbooks/brief-dual-track.md) |
| `?version=ensemble` | query param frontend | n/a | présent / absent | Override per-request (l'utilisateur a le choix) | Frontend dev | — |

### 6.2 Leviers DÉCISION (soft-gate + wrapper) — `pl_algorithm_config`

> Source : 30 rows pour `ensemble_v1_softgate_wrapper` v1.0.0 dans `pl_algorithm_config`. Tunables sans deploy (UPDATE direct via migration Alembic).

| Paramètre | Valeur prod | Range typique | Impact attendu | Note |
|---|---|---|---|---|
| `alpha_macro` | 1.4770 | [0.5, 2.5] | Pondère le facteur macro dans `net_score` | Réglé par SG-001 Fold B |
| `alpha_prior` | 0.1664 | [0.05, 0.5] | Pondère les priors structurels | |
| `alpha_anomaly` | 0.7219 | [0.3, 1.5] | Pondère le veto anomaly | Polarité AV-001 positive |
| `commit_threshold` | 0.2493 | [0.15, 0.4] | Seuil sur |net_score| pour commit (sinon MONITOR) | Plus haut = moins de coverage, plus de WR accuracy |
| `anomaly_clip_abs` | 2.5 | [1.5, 4.0] | Clip sur la magnitude de l'anomaly z-score | |
| **`wrapper_use_running_acc`** | **1 (ACTIF)** | {0, 1} | Active/désactive détecteur A | OFF = pas de veto basé sur perf récente |
| `wrapper_tau_run` | 0.5931 | [0.40, 0.70] | Seuil de l'accuracy en-dessous duquel A fire | Plus haut = plus strict |
| `wrapper_running_window` | 3 | {3, 5, 7} | Fenêtre (en trading days) de l'accuracy roulante | |
| `wrapper_min_running_n` | 2 | {1, 2, 3} | Min de commits évaluables dans la fenêtre pour calculer running_acc | |
| **`wrapper_use_cluster_dispersion`** | **1 (ACTIF)** | {0, 1} | Active/désactive détecteur C | |
| `wrapper_min_cluster_n` | 2 | {1, 2, 3} | Min de commits engagés par cluster pour calculer la dispersion | |
| `wrapper_use_trend_conflict` | 0 (inactif) | {0, 1} | Réservé v1.1.0+ | `wrapper_tau_trend=0.03`, `window=7` stockés pour reprod |
| `wrapper_use_three_way_disagreement` | 0 (inactif) | {0, 1} | Réservé v1.1.0+ | |
| **`compass_wrapper_dispersion_with_acc_threshold`** | **0.60** | [0.50, 0.75] | Override Compass : relâche le veto dispersion-seul si `running_acc_5d ≥ ce seuil` | **Le levier le plus impactant sur la coverage** |
| `cluster_<specialist_name>` | winter / spring | renommage | Réassigner un spécialiste à un cluster | 14 rows, à toucher seulement si R&D le demande |

### 6.3 Leviers NARRATIVE (LLM)

| Levier | Localisation | Valeur prod | Range / actions | Impact | Owner |
|---|---|---|---|---|---|
| LLM model Call#1 + Call#2 | [db_analysis_engine.py](../../backend/scripts/daily_analysis/db_analysis_engine.py) (constant) | `gpt-4-turbo` | `gpt-4o` / `gpt-4-turbo` / `gpt-4.5` | Qualité narrative + coût + latence | Hedi |
| Temperature Call#1 | `db_analysis_engine.py` | 1.0 | [0.5, 1.2] | Créativité de l'analyse macro | Hedi |
| Temperature Call#2 | `db_analysis_engine.py` | 0.7 | [0.3, 0.9] | Conviction du LLM relecteur | Hedi |
| Max tokens Call#1 + Call#2 | `db_analysis_engine.py` | 2048 | [1024, 4096] | Longueur max sortie | Hedi |
| `CALL_1_PROMPT` | [prompts.py](../../backend/scripts/daily_analysis/prompts.py) | (texte FR) | refonte | Style + format eco + macroeco_bonus range | Hedi |
| `CALL_2_PROMPT` (legacy pur) | `prompts.py` | (texte FR) | refonte | Style + format conclusion LEGACY | Hedi |
| **`CALL_2_PROMPT_ENSEMBLE`** | `prompts.py` | (texte FR avec 25 diag fields) | refonte | **Le prompt qui produit la narrative ensemble. Refonte = impact sur les 2 tracks (puisque code partagé).** | Hedi |
| Validator strict | `output_parser.py` | actif | toggle | Refuse les conclusions qui contiennent un mot opposé à la decision | Hedi |

### 6.4 Leviers BRIEF + PODCAST

| Levier | Localisation | Valeur prod | Range / actions | Impact | Owner |
|---|---|---|---|---|---|
| 7 sections brief ensemble | [brief_generator.py](../../backend/scripts/compass_brief_ensemble/brief_generator.py) | 7 formatters Python | + sections (Detail Quoting, Stocks, COT…) | Enrichissement brief, sans toucher au LLM | Hedi | [brief-ensemble-evolution.md](../runbooks/brief-ensemble-evolution.md) |
| Specialist catalog (libellés business) | [specialist_catalog.py](../../backend/scripts/compass_brief_ensemble/specialist_catalog.py) | 14 profils | rename + update description | Brief + podcast vocabulaire | Hedi |
| Podcast prompt NotebookLM | [podcast-prompt-ensemble.md](../runbooks/podcast-prompt-ensemble.md) | v2 (2026-05-27) | itérations | Format audio + tonalité + structure 10 sections | Hedi |
| Cluster tags brief (`_WINTER_TAGS`/`_SPRING_TAGS`) | `brief_generator.py` | heuristique sur `specialist_name` | mapping explicite via `specialist_catalog` | Robustesse aux renames R&D | Hedi |

### 6.5 Pour résumer en 1 carte : **« je veux changer X, je tape où ? »**

- **Switcher l'audio dashboard ensemble par défaut** → `BRIEF_DEFAULT_VERSION=ensemble` via `gcloud run services update backend --update-env-vars`. Voir [brief-dual-track.md](../runbooks/brief-dual-track.md).
- **Activer cc-ensemble-compute en cron** → migration : downgrade `m7h8i9j0k1l2` (passe `compute_enabled` à TRUE) + activer le scheduler. **À faire via main only**, cf. rule.
- **Relâcher davantage le wrapper (plus de coverage)** → `UPDATE pl_algorithm_config SET value='0.65' WHERE parameter_name='compass_wrapper_dispersion_with_acc_threshold'`. À tester en backtest avant.
- **Activer le détecteur trend** → migration sur `wrapper_use_trend_conflict = 1`. Conséquence : le wrapper devient plus strict. Probable baisse de coverage.
- **Changer la tonalité du brief ensemble** → éditer `CALL_2_PROMPT_ENSEMBLE` dans `prompts.py`. **Impact sur les 2 tracks** (legacy + ensemble) — penser à valider le brief legacy après.
- **Renommer un spécialiste** → `pl_algorithm_config` (row `cluster_<old>` → `cluster_<new>`) + `specialist_catalog.py` (rename `name=`) + table du runbook podcast.
- **Ajouter une section au brief ensemble** → un nouveau formatter dans `brief_generator.py` + un nouveau DB read dans `db_reader.py`. Aucun changement LLM. Voir [brief-ensemble-evolution.md](../runbooks/brief-ensemble-evolution.md).

---

## 7 — L'évolution opérationnelle (cycle de vie)

### 7.1 Daily — dual-track running

Chaque jour de session, on génère **2 briefs et 2 audios** :
- `YYYYMMDD-CompassBrief.txt` + audio legacy
- `YYYYMMDD-CompassBrief-Ensemble.txt` + audio ensemble

Le frontend en sert un seul à l'utilisateur (selon `BRIEF_DEFAULT_VERSION` + override `?version=`). Coût LLM total : ~$0.26/jour (2 × 2 calls gpt-4-turbo). Voir [brief-dual-track.md](../runbooks/brief-dual-track.md).

### 7.2 Mensuel — retraining des 14 spécialistes (à venir)

Documenté dans [CAMPAIGN_5_PROD_DEPLOYMENT.md](../archive/onboarding/CAMPAIGN_5_PROD_DEPLOYMENT.md) §7 mais **pas encore déployé en prod**. Le job `cc-ensemble-monthly-retrain` est référencé mais le scheduler n'est pas encore actif. Tant qu'il ne tourne pas, les artifacts BYTEA sont **frozen** (livraison du 2026-04-30). Conséquence : les spécialistes ne s'adaptent pas aux régimes shifts, et `running_acc_5d` n'est pas remis à NaN.

**Quand on l'activera**, attendre 5 jours de NaN running_acc → wrapper en mode default-allow → puis convergence vers le nouveau running_acc.

### 7.3 Trimestriel — re-tuning du threshold wrapper

Pas de process formel aujourd'hui — c'est l'angle mort le plus important. Le `compass_wrapper_dispersion_with_acc_threshold = 0.60` a été calé sur backfill 2026-01-01 → 2026-05-15 ; il devrait être ré-évalué chaque trimestre sur les nouvelles données prod. **À instaurer** : un job de calibration + une PR vers `pl_algorithm_config` après revue Hedi + R&D.

### 7.4 Sur-demande — ajouts, modifications

- **Ajouter une section brief** → cf. 6.5 + runbook
- **Activer un détecteur trend/3way** → cf. 6.5 + migration
- **Ajouter un nouveau spécialiste** → R&D livre un nouvel artifact + Alembic migration pour `pl_algorithm_config.cluster_*` + update `specialist_catalog.py` + update runbook podcast
- **Changer le LLM (gpt-4-turbo → gpt-4.5)** → édit `db_analysis_engine.py` + relire les 2 briefs pour valider la régression

---

## 8 — Forces et limites (comparatif)

| Dimension | LEGACY | ENSEMBLE |
|---|---|---|
| **Robustesse** | 18 mois de prod stable, roll de contrat OK, bien compris | Stack jeune (mai 2026), dépend de 38 artifacts BYTEA, retraining mensuel pas encore actif |
| **Narrative humaine** | Excellente — un LLM lit la presse comme un humain | Bonne (via legacy code partagé) mais sans le ressenti contextuel du LEGACY pur |
| **Sensibilité macro/météo** | LLM Call#1 capture le contexte qualitatif | Capturé via features structurées (sentiment, ENSO, FX) + LLM relecteur sur eco |
| **Mesurabilité fitness** | Aucune — pas de métrique récurrente | `running_acc_5d`, `realized_return_5d`, YTD Compass score, 25 champs diag |
| **Audit trail décisionnel** | 4 champs texte | 14 votes + 25 diag + decomp Winter/Spring |
| **Coût LLM /jour** | $0.13 (2 calls gpt-4-turbo) | $0.13 (mêmes prompts, code partagé) |
| **Latence pipeline** | ~30s × 2 = 60s | 14 spécialistes (~5s) + soft-gate (~2s) + wrapper (~1s) + LLM (~60s) = 70s |
| **Robustesse OpenAI down** | Brief perdu (rule fail-loud) | Décision toujours là, seule la narrative manque |
| **Robustesse Cloud SQL down** | Pas de brief | Pas de brief |
| **Hallucinations LLM** | ~1/50 briefs avec un détail factuellement faux | Mêmes hallucinations (même code) — mais la décision est immutable, donc même si le LLM hallucine, la position est correcte |
| **Multi-horizon** | T+1 forcé | J+4-J+5 — capture les biais structurels que T+1 ne voit pas |
| **Cold start** | Aucun | 5 jours NaN running_acc après chaque retraining mensuel |
| **Dépendance R&D** | Aucune (LLM générique) | Forte — nouveau pack mensuel attendu |

**Conclusion comparée.** ENSEMBLE est meilleur pour la **mesurabilité, l'audit et l'horizon multi-jours**. LEGACY garde l'avantage de la **simplicité opérationnelle, du ton humain et de l'absence de dépendance R&D**. Le dual-track n'est pas un compromis temporaire — c'est une vraie complémentarité tant qu'aucune des deux faiblesses n'est résolue à 100%.

---

## 9 — Annexes (deep-dives)

### Annexe A — Le soft-gate Bayésien en 4 étapes

**Step 1 — Collecte des votes engagés.** Chaque spécialiste produit `(decision, confidence_score)`. Si confidence_score < seuil, le vote n'est pas considéré comme "committed" et n'entre pas dans la combinaison.

**Step 2 — Mapping des votes.** OPEN = +1, MONITOR = 0, HEDGE = -1.

**Step 3 — Pondération + agrégation.**
```
weight_i = perf_30d(specialist_i) × cluster_weight × Bayesian_prior
net_score = Σ(weight_i × vote_i × alpha_factors_i) / Σ weight_i
```
où `alpha_factors_i` incorpore `alpha_macro × alpha_prior × alpha_anomaly` calibrés sur Fold B (cf. cheatsheet §6.2).

**Step 4 — Projection sur OPEN/HEDGE/MONITOR.**
- `|net_score| < commit_threshold` (= 0.2493) → MONITOR
- `net_score ≥ commit_threshold` → OPEN (sauf si `prior_open` très bas)
- `net_score ≤ -commit_threshold` → HEDGE (sauf si `prior_hedge` très bas)

Référence académique : Bayesian Model Averaging — Hoeting et al. (1999).

### Annexe B — Compass wrapper override : résultat backfill

| Métrique | Vendor wrapper R&D (OR pure) | Compass override (AND-gated release) |
|---|---|---|
| Coverage (commits / total décisions) | 17% | **49%** |
| WR accuracy (OPEN+HEDGE bien tranchés) | 100% (cold-start NaN biais) | 76% |
| Décisions « ratées » (MONITOR alors qu'OPEN/HEDGE était correct) | 73% des soft-gate commits | ~20% |

**Lecture.** Le vendor R&D est trop strict — il vetoe dispersion seule même quand le gate vient de bien performer. Compass releaste ce veto. On accepte une perte d'accuracy (100% → 76%) en échange d'un gros gain de coverage (17% → 49%) — le YTD score asymétrique Compass (cf. presentation_campaign5_v1.html) montre que ce trade est profitable parce que la pénalité sur les erreurs est plafonnée alors que le reward d'une bonne décision est borné.

Code : [compass_wrapper.py](../../backend/scripts/ensemble_compute/compass_wrapper.py) — `CompassTransitionWrapper` hérite de `TransitionProtectionWrapper` (vendor) et override la méthode de décision finale.

### Annexe C — Les 25 champs de `pl_orchestrator_decision`

Schéma intégral (vu sur la DB prod 2026-05-27) :

```sql
CREATE TABLE pl_orchestrator_decision (
  id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  date                    date NOT NULL,
  contract_id             uuid NOT NULL REFERENCES ref_contract,
  algorithm_version_id    uuid NOT NULL REFERENCES pl_algorithm_version,

  -- Soft-gate output (NOT NULL)
  soft_gate_decision        varchar(10) NOT NULL,    -- OPEN/HEDGE/MONITOR
  net_score                 numeric(15,6) NOT NULL,
  weights_sum               numeric(15,6) NOT NULL,
  n_committed_specialists   smallint NOT NULL,

  -- Wrapper output (NOT NULL)
  decision_wrapped          varchar(10) NOT NULL,    -- OPEN/HEDGE/MONITOR (final)
  wrapper_active            boolean NOT NULL,
  fired_running_acc         boolean NOT NULL,
  fired_trend               boolean NOT NULL,
  fired_dispersion          boolean NOT NULL,
  fired_three_way           boolean NOT NULL,

  -- Diagnostics (NULLABLE — NULL signifie "pas calculable" pas "0")
  running_acc_5d            numeric(8,6),
  realized_return_5d        numeric(15,6),
  winter_vote_signed        smallint,
  spring_vote_signed        smallint,
  macro_direction           smallint,                -- -1/0/+1
  macro_surprise            numeric(8,6),
  macro_half_life_days      smallint,
  anomaly_score_z           numeric(15,6),
  prior_open                numeric(8,6),
  prior_hedge               numeric(8,6),
  prior_monitor             numeric(8,6),

  created_at                timestamp NOT NULL DEFAULT now()
);
```

Tous les diagnostics nullable suivent la rule §0 #3 fail-loud de PIPELINE_ENSEMBLE : NULL ≠ 0.0. Le frontend [dashboard_service.py](../../backend/app/services/dashboard_service.py) expose ces 25 champs via `/v1/dashboard/ensemble-diagnostics?date=...` et le composant `DecisionExplainerCard` les rend visuellement.

### Annexe D — La réutilisation du moteur LEGACY (auto-align)

Mécanique du refactor 2026-05-27 :

1. **`cc-ensemble-explainer/main.py`** (~200 lignes) calcule `data_date = previous_session(target_date)` et fait un pré-flight :
   ```python
   if not session.get_orchestrator_row(data_date, contract_id):
       raise EnsembleRowMissingError(...)
   ```
2. Puis instancie `DBAnalysisEngine(session)` **sans `algorithm_version_name`**.
3. `DBAnalysisEngine.run()` détecte l'absence de pin et passe en **auto-align mode** ([db_analysis_engine.py:187-200](../../backend/scripts/daily_analysis/db_analysis_engine.py)) :
   ```python
   if not self._algorithm_version_name:
       orchestrator = self._db.get_latest_orchestrator(contract_id, data_date)
       if orchestrator:
           self._algorithm_version_name = "ensemble_v1_softgate_wrapper"
           self._inject_ensemble_diagnostics(orchestrator)
   ```
4. Le moteur fait les 2 calls `gpt-4-turbo` :
   - Call#1 : `CALL_1_PROMPT` standard (macro/weather) — identique aux 2 tracks
   - Call#2 : `CALL_2_PROMPT_ENSEMBLE` (contient les 25 champs diag dans le prompt) au lieu de `CALL_2_PROMPT` legacy pur
5. Le validator `_force_alignment_if_drifted` ré-écrase `decision` avec `decision_wrapped` si le LLM dérive (sécurité).

Si on lance `cc-daily-analysis --algorithm-version legacy` (cf. deploy.yml), le pin force la branche legacy et n'active pas l'auto-align. C'est ce qui isole les 2 tracks malgré le code partagé.

### Annexe E — Coût et latence breakdown

| Composant | Coût/jour | Latence | Note |
|---|---|---|---|
| `cc-ensemble-compute` (14 spécialistes + soft-gate + wrapper) | ~$0.01 infra | ~10s | Pas de LLM, Compute Engine pur |
| `cc-daily-analysis --algorithm legacy` | $0.13 (gpt-4-turbo × 2) | ~60s | LLM Call#1 + Call#2 |
| `cc-ensemble-explainer` (wrap DBAnalysisEngine) | $0.13 (gpt-4-turbo × 2) | ~60s | **Mêmes prompts/modèle** que le legacy |
| `cc-compass-brief` + Drive upload | $0.001 (Drive API) | ~5s | Stateless renderer + upload |
| `cc-compass-brief-ensemble` + Drive upload | $0.001 | ~5s | Idem |
| NotebookLM audio (2 audios) | géré par Google | overnight | Hors scope coût direct |
| **Total dual-track quotidien** | **~$0.26 + infra** | ~ 19:15-19:40 UTC | |
| **Année (250 trading days)** | **~$65/an LLM** | | |

### Annexe F — Liens vers le code (récap)

| Section doc | Fichier code |
|---|---|
| §2.2, §3.5, §3.6, annexe D | [backend/scripts/ensemble_explainer/main.py](../../backend/scripts/ensemble_explainer/main.py), [db_analysis_engine.py](../../backend/scripts/daily_analysis/db_analysis_engine.py) (auto-align L187-200), [prompts.py](../../backend/scripts/daily_analysis/prompts.py) (`CALL_2_PROMPT_ENSEMBLE`) |
| §3.3, §3.4, §4.4, §5, annexe B | [backend/scripts/ensemble_compute/compass_wrapper.py](../../backend/scripts/ensemble_compute/compass_wrapper.py) |
| §4.1, §6.4 | [backend/scripts/compass_brief_ensemble/specialist_catalog.py](../../backend/scripts/compass_brief_ensemble/specialist_catalog.py) |
| §6.4, §7.4 | [backend/scripts/compass_brief_ensemble/brief_generator.py](../../backend/scripts/compass_brief_ensemble/brief_generator.py), [db_reader.py](../../backend/scripts/compass_brief_ensemble/db_reader.py) |
| §3.9 | [backend/app/services/dashboard_service.py](../../backend/app/services/dashboard_service.py) (`_resolve_algo_for_date`), [services/audio_service.py](../../backend/app/services/audio_service.py) (`BRIEF_DEFAULT_VERSION`) |
| §6.2, annexe C | [backend/app/models/pipeline.py](../../backend/app/models/pipeline.py) (`PlOrchestratorDecision`, `PlSpecialistPrediction`, `PlAlgorithmConfig`, `PlAlgorithmVersion`), migrations `o9j0k1l2m3n4`, `m7h8i9j0k1l2` |
| §1.4, §8, annexe B | [backend/vendor/campaign5_ensemble_v1.0.0/presentation_campaign5_v1.html](../../backend/vendor/campaign5_ensemble_v1.0.0/presentation_campaign5_v1.html) |

---

## 10 — Cross-références

- [PIPELINE_LEGACY.md](./PIPELINE_LEGACY.md) — le pipeline LLM legacy en détail
- [PIPELINE_ENSEMBLE.md](./PIPELINE_ENSEMBLE.md) — l'architecture ensemble exhaustive (25 diag, 14 spécialistes, vendor wrapper)
- [JOBS_AND_SCRAPERS.md](./JOBS_AND_SCRAPERS.md) — catalogue exhaustif des 19 Cloud Run Jobs
- [docs/runbooks/brief-dual-track.md](../runbooks/brief-dual-track.md) — opérations du brief dual-track
- [docs/runbooks/brief-rollback-procedure.md](../runbooks/brief-rollback-procedure.md) — rollback procedure si l'ensemble brief casse
- [docs/runbooks/brief-ensemble-evolution.md](../runbooks/brief-ensemble-evolution.md) — comment ajouter des sections au brief
- [docs/runbooks/ensemble-failure-recovery.md](../runbooks/ensemble-failure-recovery.md) — récupération en cas de panne ensemble
- [docs/runbooks/podcast-prompt-ensemble.md](../runbooks/podcast-prompt-ensemble.md) — prompt NotebookLM + mapping ID→libellé
- [docs/archive/onboarding/CAMPAIGN_5_PROD_DEPLOYMENT.md](../archive/onboarding/CAMPAIGN_5_PROD_DEPLOYMENT.md) — déploiement initial Campaign 5 + retraining mensuel (à venir)
- [docs/archive/onboarding/HEDI_DATA_MAP.md](../archive/onboarding/HEDI_DATA_MAP.md) — détail des features par spécialiste
