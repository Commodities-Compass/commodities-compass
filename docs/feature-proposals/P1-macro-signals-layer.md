# Macro Signals Layer — Feature Proposal

**Type :** Feature proposal (product brief, pas user story)
**Date :** 2026-05-07
**Statut :** Proposed
**Slug :** `macro-signals-layer`
**Première phase déjà spécifiée :** [`docs/user-stories/P1-macro-climate-signal.md`](../user-stories/P1-macro-climate-signal.md)

---

## TL;DR

Ajouter une **couche "macro signals"** au pipeline Compass, composée de **3 à 4 gauges normalisées** indépendantes, parallèles aux technicals et à la météo locale :

1. **Climate macro** (ENSO, Atlantic Niño, anomalies WAM…)
2. **Disease & pest** (black pod, swollen shoot, mirides)
3. **Producer policy** (EUDR, farmgate CCC/COCOBOD, taxes export, stabilité)
4. **FX & financial regime** (DXY, GBP/USD, real rates) *(optionnel — à arbitrer)*

Chaque gauge produit un score **-1 à +1** type sentiment macro, alimenté par des sources publiques scientifiques / institutionnelles, exploité par `daily-analysis` puis (à terme) intégré comme inputs supplémentaires de la power formula composite.

**Pourquoi maintenant** : l'épisode El Niño du 3-4 mai 2026 a fait bouger le marché 1-2 jours avant qu'on ne capte le signal via la presse spécialisée. Ce n'est pas un cas isolé : on a des trous systématiques sur 3 autres familles macro (maladies, politique, FX). Le rallye cocoa 2023-2025 (~+250%) a été drivé par la combinaison de ces familles — on ne les capte aujourd'hui qu'indirectement et avec retard.

---

## Le problème

Le pipeline actuel observe le marché à travers **deux lentilles** :

- **Technicals** (RSI, MACD, Bollinger, %K, ATR, OI, IV, stocks) — capte la dynamique de prix et le positionnement, en lag du fondamental.
- **Météo locale** (`meteo_agent`, 6 villes Ghana/CI, J-1 à J+1) — capte le stress hydrique court terme.

Et un canal **sentiment macro indirect** :

- **Press review** + **daily-analysis** Call #1 → produit `macroeco_bonus` ∈ [-0.10, +0.10] qui pondère le score composite.

Le `macroeco_bonus` actuel est une **boîte noire LLM** alimentée par un flux presse non structuré. Conséquence : invisibilité sur les facteurs macro structurels qui drivent les rallyes/krachs cocoa multi-mois.

### Cas concret — l'angle mort El Niño (3-4 mai 2026)

OMM puis NOAA signalent un renforcement du risque El Niño avec impact attendu 6-12 mois. Le marché bouge. On capte l'info à J+1 et J+2 via CocoaIntel (canal presse). Trop tard, et avec une couverture qualitative seulement.

Les sources scientifiques (NOAA CPC, IRI, BoM) publiaient ce signal **5 à 14 jours avant** la presse spécialisée. Lead time exploitable, ignoré.

### Mais El Niño n'est qu'un exemple

Trois autres familles présentent le même profil "haut impact, peu/pas capté, signal scientifique ou institutionnel publié à l'avance" :

| Famille | Cas marquant 2023-25 | Pipeline actuel |
|---|---|---|
| Maladies / ravageurs | Swollen shoot Ghana → -15% production cumulée 2022-24 | Aucune surveillance dédiée |
| Politique pays producteur | EUDR Dec 2025 + hausses farmgate CCC → restructure structurelle | Capté tardivement via presse |
| FX & régime financier | USD strength + GBP volatility (London cocoa #7 en GBP) | Non capté |

Pour chaque famille, des **sources publiques structurées** existent (bulletins COCOBOD/ICCO, registry EUDR, FRED/Yahoo Finance pour FX) avec une fréquence et un format permettant l'ingestion automatisée.

---

## La proposition : couche "macro gauges"

### Principe

Une **gauge = un agent + une table d'inputs + un score normalisé** lu par le LLM `daily-analysis`. Architecture identique pour les 4 familles, ce qui maximise la réutilisation.

```
┌────────────────────────────────────────────────────────────────┐
│         Couche "Macro Gauges" (NEW)                            │
├────────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐  ┌─────────────────┐  ┌────────────────┐  │
│  │  cc-macro-      │  │  cc-disease-    │  │  cc-policy-    │  │
│  │  climate-agent  │  │  monitor-agent  │  │  watch-agent   │  │
│  │  (Phase 1)      │  │  (Phase 2)      │  │  (Phase 3)     │  │
│  └────────┬────────┘  └────────┬────────┘  └────────┬───────┘  │
│           ▼                     ▼                    ▼          │
│  pl_climate_signal     pl_disease_signal    pl_policy_signal    │
│           │                     │                    │          │
│           ▼                     ▼                    ▼          │
│      [Gauge climat]      [Gauge maladies]    [Gauge politique]  │
│              │                  │                   │           │
│              └──────────────────┼───────────────────┘           │
│                                 ▼                                │
│        + (Phase 4, optionnel) Gauge FX (DXY / GBP/USD)          │
└─────────────────────────────────┬───────────────────────────────┘
                                  ▼
              ┌──────────────────────────────────────┐
              │  cc-daily-analysis (existant)        │
              │  Call #1 lit les 3-4 gauges          │
              │  → Décompose explicitement           │
              │     macroeco_bonus en composantes    │
              └──────────────────┬───────────────────┘
                                 ▼
                     pl_indicator_daily.macroeco_bonus
                                 │
                                 ▼
                  Power formula composite (existante)
```

### Les 4 gauges

#### 1. Climate macro — "Régime climatique global"

**Tracking** : phase ENSO (El Niño / Neutral / La Niña), Niño 3.4 SST anomaly, ONI, Atlantic Niño SST, forecast saisonnier précip belt cocoa.

**Sources** : NOAA CPC, NOAA OISST, IRI, Open-Meteo Climate API, BoM (gratuit, pas d'auth).

**Pourquoi cocoa** : ENSO a un lead time documenté de 3-9 mois sur les rendements West Africa. La Niña (humide) tend à favoriser, El Niño (sec) à pénaliser le big crop ivoirien/ghanéen.

**Phase** : 1 (déjà spécifiée — voir [user story dédié](../user-stories/macro-climate-signal.md)).

#### 2. Disease & pest — "Pression épidémique"

**Tracking** : risque black pod (proxy : humidité > 85% + temp 25-30°C sur les zones), surveillance swollen shoot (bulletins COCOBOD), pression mirides (corrélée sécheresse).

**Sources** : COCOBOD (Ghana) bulletins, ICCO Quarterly Bulletin (déjà scrappé pour grindings), dérivation depuis `pl_weather_observation` existante.

**Pourquoi cocoa** : black pod peut effacer 30-50% d'une saison régionale. Swollen shoot virus a détruit ~15-20% des arbres au Ghana sur 2020-2024 (driver structurel du rallye 2023-25).

**Phase** : 2 (après validation du pattern climat).

#### 3. Producer policy — "Risque politique / structurel pays producteur"

**Tracking** : décisions farmgate CCC / COCOBOD (annuel), changements taxes export et quotas, deadline et enforcement EUDR, indicateurs stabilité politique CI/Ghana.

**Sources** : sites CCC + COCOBOD, EU EUDR registry, presse spécialisée (CocoaIntel, ICCO), événementiel.

**Pourquoi cocoa** : EUDR Dec 2025 = restructure structurelle de la chaîne d'appro EU (45% de la demande). Hausses farmgate CCC répétées en 2024-25 ont signalé tension d'offre. Très LLM-driven (pas de chiffre brut → LLM extrait l'événement et le score).

**Phase** : 3.

#### 4. FX & financial regime — "Contexte financier macro"

**Tracking** : DXY (USD strength), GBP/USD (London cocoa #7 en GBP), real rates US 10Y, fund flows ETF soft commodities.

**Sources** : FRED, Yahoo Finance, ICE (free tier).

**Pourquoi cocoa** : DXY corrélé inversement aux soft commodities (financialisation). GBP/USD impact direct sur la valorisation London cocoa. Real rates pèsent sur le carry des positions speculatives.

**Phase** : 4 (optionnel — à arbitrer car recoupe partiellement les technicals).

### Décomposition explicite de macroeco_bonus

Aujourd'hui : `macroeco_bonus = LLM(presse + meteo locale)` → opaque.

Cible : `macroeco_bonus = f(gauge_climate, gauge_disease, gauge_policy, gauge_fx)` → décomposable, traçable, debuggable.

À terme (Phase 5 / Option 3 quantitative), chaque gauge devient un input direct du composite (power formula passe de 8 à 11-12 inputs), avec coefficients calibrés par backtest. Une nouvelle algo version `v1.1.0` co-existe avec la v1.0.x.

---

## Phasing recommandé

| Phase | Gauge | Effort | Trigger |
|---|---|---|---|
| 1 | Climate | ~1.5j | Spec validée, prête à shipper |
| 2 | Disease & pest | ~2j | Phase 1 stable depuis ≥ 1 mois en prod |
| 3 | Producer policy | ~2-3j (LLM-heavy) | Phase 2 stable |
| 4 *(optionnel)* | FX | ~1j | Décision produit après backtest |
| 5 | Intégration quantitative composite | ~1 semaine + backtest | 3-6 mois d'historique sur ≥ 2 gauges |

**Logique** : on commence par la famille avec le meilleur ratio impact / facilité d'ingestion (climat), on valide le pattern d'architecture, puis on duplique. Pas de big bang.

---

## Bénéfices attendus

### Pour le produit

- **Lead time de 5-14 jours** sur les signaux macro vs presse spécialisée
- **Décomposition explicable** du `macroeco_bonus` actuel (boîte noire → 4 composantes)
- **Couverture des 4 grands drivers** du rallye cocoa 2023-2025 (climat + maladies + politique + FX)
- **Auditabilité** : chaque score traçable jusqu'à ses inputs bruts persistés en DB

### Pour la roadmap technique

- **Pattern réutilisable** : un nouvel agent macro = ~1.5-2j (template clair après Phase 1)
- **Compatible North Star** : tables `pl_*_signal` immutables, agents indépendants, fail-loud, config as data
- **Pré-requis pour le composite v1.1.0 quantitatif** : sans historique de signaux, pas de backtest possible. Cette feature génère ce dataset.

### Pour le business

- **Différenciation produit** : "Compass voit ce que les desks ne voient pas encore"
- **Argumentaire investisseur / B2B** : tangible, démontrable (un screenshot de l'évolution d'une gauge avant un mouvement marché)
- **Levier pricing** : tier supérieur "Macro signals access" envisageable

---

## Coût estimé (4 gauges)

| Item | Coût mensuel |
|---|---|
| Cloud Run Jobs (4 agents, ~30s/jour chacun) | < $1 |
| LLM (gpt-4.1, ~4 appels/jour) | ~$60-80 |
| Sources externes (NOAA, IRI, FRED, Yahoo, COCOBOD, ICCO) | $0 (toutes publiques) |
| **Total** | **~$80/mois** |

Effort ingénierie cumulé : ~6-8 jours pour les 4 gauges (Phase 1 → 4), hors Phase 5 quantitative.

---

## Risques & mitigations

| Risque | Mitigation |
|---|---|
| Sources HTML/PDF qui changent de structure (NOAA, COCOBOD) | Fixtures snapshots dans tests, alerte CI quand parser fail |
| Doublon LLM avec press review (le LLM voit déjà ENSO via la presse) | Distinguer signal scientifique vs presse dans le prompt → instruction explicite anti double comptage |
| Faux signaux en période de transition (ENSO neutre, IOD ambigu) | Confidence score + range `macroeco_bonus` modeste si confidence < 0.7 |
| Surcharge cognitive du LLM Call #1 (3-4 gauges en plus du reste) | Format JSON strict, sections clairement séparées dans le prompt |
| Politique = très qualitatif, hard à normaliser | Accepter une gauge "binaire-ish" (-1 / 0 / +1) sur événements, pas un score continu |

---

## Décisions à prendre

1. **Inclure la gauge FX (Phase 4) ou pas ?** Son recoupement avec les technicals est limite. À trancher après Phase 1-3.
2. **Décomposition transparente de `macroeco_bonus` côté UI ?** Soit on garde une gauge unique côté dashboard (lisible mais opaque), soit on expose les 3-4 sous-gauges (transparent mais charge cognitive).
3. **Algorithme v1.1.0 vs v1.0.x** : intégrer les gauges dans le composite (Phase 5) crée un nouveau régime de scoring. Quel critère pour basculer le default ? Backtest > 6 mois ? Validation manuelle qualitative ?
4. **Cible commerciale** : la couche macro signals est-elle un upgrade silencieux du produit ou un tier payant à part ?

---

## Références

- User story Phase 1 (climat) : [`docs/user-stories/P1-macro-climate-signal.md`](../user-stories/P1-macro-climate-signal.md)
- Règles projet relevantes : `.claude/rules/pipeline-error-handling.md`, `.claude/rules/north-star-alignment.md`, `.claude/rules/pipeline-continuity.md`
- North Star repo : `The_North_Star.md`
- User story grindings (existant, complémentaire) : `docs/user-stories/P2-icco-grinding-alerts.md`
