# Press Review V2 — Stratégie d'Évolution

> Commodities Compass — Avril 2026
>
> Contexte : EXP-014 (validé 14 avril 2026) a identifié un signal prédictif dans les changements de sentiment des revues de presse sur les thèmes **production** et **chocolat**. Ce document présente l'évolution de la press review pour capturer ce signal tout en préservant sa valeur métier.

---

## 1. Situation actuelle

### Ce que fait la press review aujourd'hui

Chaque jour de trading à 19h05 UTC, un agent LLM (o4-mini) :
- Scrape **10 sources d'actualité** cacao
- Génère une **analyse en français** structurée en 3 sections (Marché, Fondamentaux, Sentiment)
- Extrait les **data points clés** (prix, grindings, variations)
- Écrit le tout dans la base de données

Le trader ouvre le dashboard le matin et lit sa revue de presse avec le contexte marché, les fondamentaux du jour, et la synthèse d'impact.

### Ce qu'on a découvert — 3 expériences, même conclusion

Depuis février 2026, on extrait des segments thématiques de la press review (672 segments sur ~250 jours, répartis en 7 cellules zone/thème). Trois expériences successives ont exploré la même question : **est-ce que le sentiment extrait de la presse prédit les mouvements de prix du cacao ?**

| Expérience | Ce qu'on a testé | Résultat |
|------------|-----------------|----------|
| **EXP-012** | Le sentiment brut (niveau) jour par jour | Faible : p=0.037 au lag 4, mais aucun résultat solide. Les niveaux bruts de sentiment ne prédisent pas le prix. Le thème monde/économie (le plus couvert, 177 segments) affiche une corrélation proche de zéro (rho = +0.03). |
| **EXP-013** | Le changement de sentiment d'un jour à l'autre (delta brut) | Mieux : p=0.024 au lag 3 et p=0.020 au lag 4. L'information est dans les **changements**, pas dans les niveaux. Mais le signal reste fragile sans normalisation. |
| **EXP-014** | Le delta après normalisation (z-score glissant 21 jours + delta 3 jours) | Confirmé : **production** p=0.017, **chocolat** p=0.025 au lag 3. Sur 4 méthodes de normalisation testées (brut, z-score, percentile rank, z-score delta), seule la z-score delta produit des résultats significatifs. |

**Ce n'est pas une découverte isolée** — c'est une réplication à travers 3 formulations indépendantes. Le signal s'améliore à chaque étape de normalisation, ce qui renforce la confiance dans le résultat.

### Ce qui porte le signal — et ce qui n'en porte pas

| Thème | Signal ? | Explication |
|-------|----------|-------------|
| **Production** (récolte, arrivages, météo, Afrique de l'Ouest) | **Oui** — p=0.017 | Quand le récit sur la production change de ton, le prix suit 3-4 jours après |
| **Chocolat** (grindings, demande, industrie transformation) | **Oui** — p=0.025 | Idem pour la demande chocolat |
| Économie (macro, devises, politique monétaire) | **Non** | EXP-012 avait déjà montré que le thème économie (rho = +0.03) ne fait que décrire ce qui s'est déjà passé dans le prix. Il suit le marché, il ne le précède pas. |
| Transformation (broyages, capacités industrielles) | **Non** | Trop peu de données (102 segments sur ~80 jours) et signal noyé dans le bruit |
| Agrégat (tous thèmes combinés) | **Non** | p=0.071 — dilue le signal. Production seule (p=0.017) est 4x plus significative que l'agrégat |

**Point important** : agréger les thèmes en un seul score détruit le signal. Les 4 thèmes doivent rester des features indépendantes.

Or aujourd'hui, **4 de nos 10 sources** (Barchart, Investing.com, Nasdaq, MarketScreener) sont des intermédiaires financiers qui recyclent les mêmes dépêches Reuters — et alimentent principalement le thème Économie/Marché, celui qui n'a aucun pouvoir prédictif.

### Comment le signal fonctionne — un exemple concret

Le signal ne vient pas des data points (chiffres de grindings, tonnages d'arrivages). Il vient de la façon dont le **récit quotidien** évolue d'un jour à l'autre sur les thèmes production et chocolat.

Imaginons 5 jours consécutifs de press review. Le LLM extrait un score de sentiment sur le thème "production" chaque jour :

```
Jour 1 (lundi)   : score = +0.2  "Les arrivages à Abidjan sont conformes aux attentes"
Jour 2 (mardi)   : score = +0.1  "Le rythme des arrivages ralentit légèrement"
Jour 3 (mercredi) : score = -0.3  "Des inquiétudes émergent sur la mid-crop ivoirienne"
Jour 4 (jeudi)   : score = -0.5  "Les opérateurs évoquent un possible déficit plus large"
Jour 5 (vendredi) : score = -0.6  "Le Conseil Café-Cacao confirme un retard de récolte"
```

Ce que le z-score delta capture :
- **Jour 1 à 3** : on passe de +0.2 à -0.3 → le delta est négatif et significatif
- En termes de z-score (normalisé sur 21 jours de trading), ce passage de "normal" à "inhabituel" crée un pic négatif
- Ce pic signale que la **narrative de marché est en train de basculer** sur la production

Ce qui se passe ensuite : le prix du cacao monte 3-4 jours après ce shift narratif. Pourquoi ? Parce que la presse reflète ce que les opérateurs commencent à intégrer dans leur positionnement — mais le prix met quelques jours à pleinement refléter ce repositionnement.

**Le récit n'a même pas besoin d'être "juste".** Si la mid-crop s'avère finalement correcte, le shift narratif aura quand même prédit le mouvement parce qu'il reflétait un changement de perception du marché. Le signal est dans le **changement de ton**, pas dans la véracité de l'information.

C'est aussi pourquoi le thème "économie" ne porte pas de signal : la presse économique généraliste (Reuters, Bloomberg) **décrit** les mouvements de prix après coup ("le cacao a reculé de 3% suite à...") plutôt que d'anticiper un changement. Le récit suit le prix au lieu de le précéder.

### Pourquoi c'est quotidien, pas trimestriel

Un rapport de grindings ECA ou NCA sort 4 fois par an. Mais le marché **parle** de production et de chocolat tous les jours :
- Rumeurs sur les arrivages ivoiriens avant les chiffres officiels
- Spéculations sur l'impact d'Harmattan sur la mid-crop
- Réactions aux conditions météo au Ghana
- Anticipation des publications de grindings ("le marché s'attend à un Q1 faible en Europe")
- Commentaires d'analystes sur les tendances de demande chocolat

Ce bruit narratif quotidien est exactement ce qu'on mesure. Les données structurées (grindings, arrivages) sont un chantier séparé — elles alimenteront directement le moteur de trading comme features fondamentales, pas via l'extraction de sentiment.

---

## 2. Ce qui change — Vue d'ensemble

### Le principe fondamental

**Un seul pipeline, un seul appel LLM, deux sorties :**

```
Sources améliorées
    ↓
Même appel LLM (o4-mini)
    ↓
┌─────────────────────────────────────────────────────┐
│                                                     │
│  Sortie 1 : Revue de presse (inchangée)             │
│  → resume, mots-clés, impact synthétique            │
│  → Ce que le trader lit chaque matin                │
│                                                     │
│  Sortie 2 : Scores sentiment par thème (nouveau)    │
│  → production: -0.6, chocolat: +0.3, ...            │
│  → Ce que le moteur de trading exploite              │
│                                                     │
└─────────────────────────────────────────────────────┘
```

Zéro appel LLM supplémentaire. Zéro perte de valeur métier. Le trader continue de lire sa revue de presse exactement comme avant, et le système capture en plus un signal structuré exploitable.

---

## 3. Évolution des sources

### Avant (10 sources, dont 4 redondantes)

| Source | Thème principal | Statut V2 |
|--------|----------------|-----------|
| Barchart Cocoa News | Marché (Reuters) | **Supprimée** — redondant |
| Investing.com Cocoa | Marché (Reuters) | Conservée — 1 source marché suffit |
| Nasdaq Cocoa | Marché (Reuters) | **Supprimée** — redondant |
| MarketScreener Cocoa | Marché (Reuters) | **Supprimée** — redondant |
| CocoaIntel | Production + Marché | Conservée |
| ICCO News | Production | Conservée |
| ICCO Statistics | Transformation | **Supprimée** — page quasi-statique |
| Confectionery News | Chocolat / Demande | Conservée |
| Abidjan.net Économie | Afrique / Production | Conservée |
| Agence Ecofin Cacao | Afrique / Production | Conservée |

### Audit d'accessibilité des candidates (17 avril 2026)

Plus de 25 sources ont été testées par probe httpx (même User-Agent et timeout que le fetcher en production). Voici les résultats :

**Sources viables (200 OK + contenu extractible) :**

| Source | HTTP | Contenu | Thème | Verdict |
|--------|------|---------|-------|---------|
| Cacao.ci | 200, 2177 chars | 38 articles, titres riches ("Crise filière cacao ivoirienne", "Arrivées portuaires") | Production CI | **Ajoutée** |
| The Cocoa Post | 200, 1944 chars | 53 articles, production + durabilité ("Pricing Mechanisms", "Cocoa Farmers") | Production Ghana/Global | **Ajoutée** |

**Sources rejetées :**

| Source | HTTP | Raison du rejet |
|--------|------|----------------|
| Commodafrica | 503 | Site down (Service Unavailable) |
| Candy Industry | 403 | WAF bloquant (Forbidden) |
| Barry Callebaut Newsroom | 200 | Contenu corporate, pas de titres news extractibles par CSS |
| World Cocoa Foundation | 404 | Page introuvable |
| CommodityBasis | 404 | Page introuvable |
| The Public Ledger | DNS error | Domaine inexistant |
| Fraternité Matin | 200, 80 chars | Quasi-vide côté serveur (JS-rendered) |
| Mongabay Cocoa | 200, 25 chars | Idem — contenu rendu côté client |
| Ghana Web Cocoa | 200 | Pas de contenu cacao extractible |
| Ghana Business News | 404 | Page introuvable |
| Jeune Afrique (tag cacao) | 404 | Page introuvable |
| RFI Cacao | 403 | WAF bloquant |
| Reuters Commodities | 401 | DataDome WAF (voir analyse Reuters ci-dessous) |
| Bloomberg Commodities | 403 | WAF bloquant |
| Financial Times Commodities | 403 | WAF bloquant |

### Pourquoi pas Reuters ? — Analyse coût tech + money

Reuters (`reuters.com/markets/commodities/`) retourne systématiquement un **401 DataDome WAF** sur toutes les requêtes non-browser. C'est intentionnel : ils poussent vers leurs API payantes (Refinitiv/LSEG).

**Options d'accès et coûts :**

| Option | Coût mensuel | Délai setup | Verdict |
|--------|-------------|-------------|---------|
| Scraping direct (httpx) | $0 | — | Impossible — DataDome bloque systématiquement |
| Playwright headless | $0 | ~1 jour | Instable — DataDome détecte les headless modernes |
| **Refinitiv/LSEG News API** | **$2 000 – $5 000+/mois** | 2-4 semaines (cycle commercial + intégration) | Flux Reuters complet avec SLA |
| Bloomberg B-PIPE | $2 000 – $3 000/mois | Même ordre | Bloomberg wire + data |
| RapidAPI Reuters (proxy tiers) | ~$50-100/mois | 1 jour | Non-officiel, fiabilité incertaine |

**Pourquoi on ne paie pas :**

1. **Le contenu Reuters est déjà disponible.** Investing.com relaie les dépêches Reuters avec quelques heures de délai. C'est le même contenu syndiqué — on a ~90% de la valeur Reuters à coût zéro.

2. **Reuters alimente le mauvais thème.** Le contenu Reuters est principalement du marché/économie (prix, macro, devises) — le thème qui a **zéro pouvoir prédictif** selon EXP-012/013/014. Payer $2K+/mois pour enrichir un thème sans signal est du gaspillage.

3. **Le ratio est absurde.** Le press review agent coûte ~$2/mois en LLM calls. Reuters multiplierait le coût par 1000x pour un incrément marginal sur un thème non-porteur.

4. **Les sources terrain gratuites apportent plus de valeur.** Cacao.ci et The Cocoa Post couvrent les thèmes production et chocolat (ceux avec signal) — exactement ce que Reuters ne couvre pas en profondeur.

> **Note** : si un jour un accès Reuters devient pertinent, ce serait pour le **Chantier 2** (données structurées) — Refinitiv propose des API de données commodités (prix, volumes, OI historiques) qui pourraient compléter le Barchart scraper. Mais c'est un autre budget et un autre projet.

### Après (8 sources, ciblées signal)

| # | Source | Thème | Méthode | Signal ? |
|---|--------|-------|---------|----------|
| 1 | Investing.com Cocoa | Marché (contexte prix) | httpx | Non — mais nécessaire pour la section MARCHE |
| 2 | CocoaIntel | Production + Marché | httpx | Production ✅ |
| 3 | ICCO News | Production officiel | httpx | Production ✅ |
| 4 | Confectionery News | Chocolat / Demande | httpx | Chocolat ✅ |
| 5 | Abidjan.net | Afrique / Production | httpx | Production ✅ |
| 6 | Agence Ecofin Cacao | Afrique / Production | Playwright | Production ✅ |
| 7 | **Cacao.ci** | Production Côte d'Ivoire | httpx | Production ✅ — *nouveau* |
| 8 | **The Cocoa Post** | Production Ghana + Global | httpx | Production ✅ — *nouveau* |

**Évolution du mix :**
- **Avant** : 10 sources — 4 intermédiaires Reuters (40% du contenu sur économie/marché, thème sans signal)
- **Après** : 8 sources — 6 sur production, 1 sur chocolat, 1 sur marché (~87% du contenu sur les thèmes porteurs)

### Ce que ça change pour l'utilisateur

- Le **tab Marché** reste présent mais plus concis (le Close est déjà affiché dans le dashboard, pas besoin de 4 sources pour le répéter)
- Les **tabs Fondamentaux et Offre** deviennent plus riches — plus de contenu terrain sur la production et la demande chocolat
- Les **mots-clés** (chips en bas de la card) continuent d'afficher les data points (prix, grindings, variations) quand les sources en parlent
- Le **bandeau Impact** reste identique

---

## 4. Évolution du prompt LLM

### Avant

Le prompt demande 3 champs JSON : `resume`, `mots_cle`, `impact_synthetiques`. Les sections du resume sont hiérarchisées : MARCHE en premier, puis FONDAMENTAUX, OFFRE, SENTIMENT MARCHE.

### Après

Le prompt demande **4 champs JSON** — les 3 existants inchangés + 1 nouveau :

| Champ | Pour qui | Changement |
|-------|---------|------------|
| `resume` | Trader (lecture) | Hiérarchie inversée : OFFRE et FONDAMENTAUX deviennent prioritaires, MARCHE plus concis |
| `mots_cle` | Trader (scan rapide) | Inchangé |
| `impact_synthetiques` | Trader (bandeau) | Inchangé |
| `theme_sentiments` | **Moteur signal** | **Nouveau** — scores [-1, +1] par thème avec justification |

Le champ `theme_sentiments` ressemble à ceci :

```
"theme_sentiments": {
  "production": {
    "score": -0.6,
    "confidence": 0.8,
    "rationale": "Inquiétudes sur la mid-crop ivoirienne, arrivages en baisse"
  },
  "chocolat": {
    "score": 0.3,
    "confidence": 0.7,
    "rationale": "Demande asiatique soutenue, grindings Q1 Asia en hausse"
  }
}
```

Le LLM n'inclut un thème que si les sources du jour en parlent réellement — pas d'invention.

---

## 5. Évolution côté données

### Ce qui existe aujourd'hui

```
Press Review Agent → pl_fundamental_article
                       (resume, mots_cle, impact_synthesis)
```

Un article par jour par provider. Le dashboard affiche l'article actif.

### Ce qui s'ajoute

```
Press Review Agent → pl_fundamental_article       (inchangé — valeur business)
                   → pl_article_segment            (nouveau — scores thématiques)

Compute Features  → pl_sentiment_feature           (nouveau — z-delta shadow mode)
```

| Table | Contenu | Fréquence | Lecteur |
|-------|---------|-----------|---------|
| `pl_fundamental_article` | Resume, mots-clés, impact | 1 row/jour | Dashboard (humain) |
| `pl_article_segment` | Score [-1,+1] par thème, confiance, justification | 1-4 rows/jour | API sentiment + engine |
| `pl_sentiment_feature` | Z-score 21j + delta 3j par thème | 1-4 rows/jour | Shadow mode (moteur V2) |

### Shadow mode

Les z-delta features sont calculées et stockées quotidiennement mais **ne sont pas injectées dans le moteur de trading**. C'est de l'accumulation : on a besoin de 250+ jours de données avant de pouvoir les exploiter de façon fiable. À rythme actuel, le seuil sera atteint vers **octobre 2026**.

D'ici là, les données s'accumulent silencieusement. Quand le volume sera suffisant, un re-run de l'expérience EXP-014 validera (ou non) le signal, et on décidera de l'intégration formelle.

---

## 6. Google News RSS — Couche de couverture

### Le pattern (inspiré du TogetherCocoa Monitor)

Plutôt que de crawler des sites HTML (lent, fragile, anti-bot), on délègue la découverte à Google News qui indexe ~50 000 sources en continu. Son endpoint RSS accepte des requêtes thématiques et retourne du XML propre — titre, source, date, pas de HTML à parser.

```
https://news.google.com/rss/search?q="cocoa"+AND+("crop"+OR+"ivory+coast")when:1d&hl=en&gl=US&ceid=US:en
```

### Dual-sourcing : profondeur + couverture

```
Sources fixes (8)            → contenu complet (httpx/Playwright) → resume détaillé
Google News RSS (8 requêtes) → titres seuls (~40-80 headlines)    → couverture + sentiment
         │                              │
         └──────── Même LLM call ───────┘
```

- Les **sources fixes** garantissent la profondeur (contenu complet pour le resume, chiffres, analyse)
- **Google News RSS** garantit la couverture (aucun sujet raté, quelle que soit la source d'origine)
- Les deux enrichissent le resume ET le scoring sentiment

### Détection anticipatoire

Google News capte le bruit narratif qui **précède** les événements de 2-3 jours. Exemple concret avec les grindings ECA Q1 (publiés le 16 avril) :

- **J-3 (13 avril)** : "Analysts expect weak European Q1 grindings" — capté par Google News
- **J-2 (14 avril)** : "European cocoa grindings likely to decline amid price surge" — capté
- **J-1 (15 avril)** : "Market braces for grindings data amid demand concerns" — capté
- **J (16 avril)** : Publication officielle ECA → nos sources fixes le couvrent

Nos sources fixes ne couvrent les grindings que le jour J (dépêche Reuters). Google News avance la fenêtre de détection du sentiment de 2-3 jours — ce qui correspond directement au lag Granger 3-4 jours identifié par EXP-014.

### Implémentation

- 8 requêtes thématiques (4 EN + 4 FR) avec `when:1d`
- Parsing XML avec `ElementTree` (pas de HTML, pas de follow des liens)
- Dedup par hash MD5 du titre
- Max 10 items par requête
- Headlines formatées comme section séparée dans le prompt (distincte des sources complètes pour le grounding)

Coût réseau : 8 requêtes × ~30 Ko × ~200 ms = **~2 secondes**. Négligeable.

### Prompt : distinction sources complètes vs headlines

```
=== Sources complètes (contenu vérifié) ===
[Investing.com] ... 3500 chars de contenu ...
[CocoaIntel] ... 2800 chars de contenu ...

=== Headlines du jour (titres uniquement) ===
[Ghana Business News] Minority Caucus urges Ghana government to pay cocoa farmers
[Valor International] Demand for chocolate falls in Brazil, slowing cocoa grinding
[FratMat] Filière cacao : CI et Ghana font front commun contre le swollen shoot
```

Le LLM peut mentionner les headlines dans le resume ("la presse rapporte que...") mais sans inventer de détails au-delà du titre.

---

## 7. Évolution côté application (Frontend)

### Analyse du Jour — Avant

```
┌─────────────────────────────────────────────────────────────┐
│  Analyse du Jour                                            │
│                                                             │
│  MACROECO  MACD  VOL/OI  RSI  %K  ATR                      │
│   (0.96)  (1.07) (2.70) (0.96)(0.63)(-1.45)                │
│                                                             │
│  6 gauges mélangées (5 techniques + 1 score LLM qualitatif) │
└─────────────────────────────────────────────────────────────┘
```

**Problème** : MACROECO est un score LLM qualitatif [-0.1, +0.1] mélangé avec des z-scores techniques non bornés. Incohérent visuellement et conceptuellement.

### Analyse du Jour — Après

```
┌─────────────────────────────────────────────────────────────┐
│  Indicateurs Techniques                                     │
│                                                             │
│   MACD     VOL/OI    RSI      %K       ATR                  │
│  (1.07)    (2.70)   (0.96)   (0.63)  (-1.45)               │
│                                                             │
│  5 gauges — z-scores techniques purs                        │
├─────────────────────────────────────────────────────────────┤
│  Sentiment Thématique                                       │
│                                                             │
│  PRODUCTION  CHOCOLAT  TRANSF.  ÉCONOMIE                    │
│   (-0.60)    (+0.30)   (N/A)    (-0.20)                    │
│      ★↘         ★→                 ↗                        │
│                                                             │
│  4 gauges — scores sentiment [-1, +1]                       │
│  ★ = signal significatif (production, chocolat)             │
│  ↗↘→ = tendance z-delta 3 jours                            │
└─────────────────────────────────────────────────────────────┘
```

### Ce qui change

| Élément | Avant | Après |
|---------|-------|-------|
| MACROECO gauge | Présente (mélangée avec les techniques) | **Retirée** de la ligne technique |
| Indicateurs techniques | 6 gauges (5 tech + 1 macro) | 5 gauges techniques pures |
| **Sentiment thématique** | N'existe pas | **Nouveau** — 4 gauges avec scores [-1, +1], même composant GaugeIndicator |
| Zones couleur sentiment | — | Rouge (bearish < -0.3) / Orange (neutre) / Vert (bullish > +0.3) |
| Signal significatif | — | Production et Chocolat marqués d'une étoile |
| Tendance | — | Flèche z-delta quand données suffisantes |

### NewsCard — inchangé

Le NewsCard (tabs Marché/Fondamentaux/Sentiment, mots-clés, impact banner) reste strictement identique. Le contenu du resume sera plus riche en Offre/Fondamentaux grâce aux sources améliorées.

---

## 7. Objectif final

### Court terme (mai 2026)

- Press review quotidienne enrichie : meilleures sources, focus production + chocolat
- Extraction structurée de sentiment par thème à chaque run
- Scores visibles sur le dashboard dans le nouveau bandeau thématique
- Accumulation quotidienne des z-delta features en shadow mode

### Moyen terme (octobre 2026)

- 250+ jours de données accumulées
- Re-run EXP-014 pour valider le signal sur un corpus plus large
- Si validé : intégration formelle dans le moteur de trading (4 features macro ajoutées aux 10 indicateurs techniques)
- Le modèle logistique passe de 10 à 14 features

### Vision

La press review devient un **double instrument** :
1. **Pour le trader** : une revue de presse quotidienne dense et actionnable, orientée vers les fondamentaux qui comptent (production, chocolat), pas vers le bruit Reuters
2. **Pour le système** : une source de signal structuré qui capture les shifts narratifs du marché et les transforme en features prédictives

Les deux objectifs se renforcent mutuellement. De meilleures sources produisent une meilleure revue pour le trader ET un meilleur signal pour le moteur.

---

## 8. Lien avec le Chantier 2 — Scrapers fondamentaux

Ce document couvre le **Chantier 1** (press review, sentiment quotidien, narrative).

Le **Chantier 2** (scrapers dédiés pour les données structurées : grindings ECA/NCA, arrivages CCC/COCOBOD) est un projet séparé documenté dans [fundamental-data-scrapers.md](user-stories/fundamental-data-scrapers.md). Ces deux chantiers sont indépendants et complémentaires :

- **Chantier 1** capte le récit quotidien → signal via z-delta sentiment
- **Chantier 2** ingère les data points structurées → features directes pour le moteur

Les publications du Chantier 2 (ex: grindings ECA Q1) créent des événements qui font bouger le sentiment capté par le Chantier 1. Les deux flux se nourrissent mutuellement sans se mélanger.
