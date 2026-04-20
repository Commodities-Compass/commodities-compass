# Press Review V2 — Enrichissement Signal + Valeur Business

## User Story

En tant que système de trading Commodities Compass, je veux que la press review quotidienne extraise des scores de sentiment structurés par thème (production, chocolat, transformation, économie) en plus de la revue narrative existante, afin de pouvoir accumuler les données nécessaires à l'intégration de features macro-économiques dans le moteur de trading.

En tant que trader utilisant le dashboard, je veux une revue de presse quotidienne plus riche en contenu production et chocolat, avec un aperçu visuel du sentiment par thème, tout en conservant le format actuel (tabs Marché/Fondamentaux/Sentiment, mots-clés, impact).

## Context

EXP-014 (validé 14 avril 2026) a montré que les thèmes **production** (p=0.017) et **chocolat** (p=0.025) portent un signal Granger à lag 3-4 via z-score delta du sentiment. Le signal vient des changements narratifs quotidiens, pas des data points. Les thèmes économie et transformation n'ont aucun pouvoir prédictif.

La press review actuelle produit du contenu sur ces thèmes mais :
- 4/10 sources (Barchart, Investing, Nasdaq, MarketScreener) sont des intermédiaires qui alimentent le thème économie/marché — celui sans signal
- Aucune extraction structurée du sentiment par thème — le signal est enfoui dans le prose
- Pas de z-delta features accumulées pour le moteur V2

Lien avec EXP-014 : [normalisation-features-macro-v2.pdf](../../normalisation-features-macro-v2.pdf)

## Principe architectural

Un seul pipeline, un seul appel LLM, deux sorties, deux couches de sources :

```
Sources fixes (8)            → contenu complet (httpx/Playwright)
Google News RSS (8 requêtes) → titres + source + date (XML, pas de follow)
         │                              │
         └──────── Même LLM call ───────┘
                       │
                       ├→ resume/mots_cle/impact  (enrichi par les headlines)
                       └→ theme_sentiments        (nouveau)
```

**Dual-sourcing** inspiré du pattern TogetherCocoa Monitor (cf. [DEEP_DIVE.md](../../DEEP_DIVE.md)) :
- **Sources fixes** = profondeur (contenu complet pour le resume, chiffres, analyse)
- **Google News RSS** = couverture (titres de ~50 000 sources indexées par Google, aucun sujet raté)

Les headlines Google News enrichissent les **deux sorties** : le resume (le LLM peut mentionner des événements captés uniquement par les headlines) et le scoring sentiment (plus de signaux narratifs à évaluer).

**Avantage clé — détection anticipatoire** : Google News capte le bruit narratif qui précède les événements (analyses, previews, spéculations) 2-3 jours avant les publications officielles. Exemple : les articles "Analysts expect weak European Q1 grindings" circulent J-2/J-3 avant la publication ECA. Nos sources fixes ne couvrent les grindings que le jour J (dépêche Reuters). Google News avance la fenêtre de détection du sentiment — ce qui correspond directement au lag Granger 3-4 jours identifié par EXP-014.

Zéro appel LLM supplémentaire. Zéro perte de valeur business. Le document de stratégie complet est dans [press-review-v2-strategy.md](../press-review-v2-strategy.md).

## Acceptance Criteria

### AC1 — Sources recomposées + Google News RSS

**Sources fixes :**
- [ ] 3 intermédiaires redondants supprimés (Barchart News, Nasdaq, MarketScreener)
- [ ] ICCO Statistics supprimé (page quasi-statique)
- [ ] 2 sources production ajoutées : Cacao.ci + The Cocoa Post (accessibilité validée par probe httpx le 17 avril)
- [ ] source_count ≥ 5 sur dry run

**Google News RSS (couche additionnelle) :**
- [ ] 8 requêtes thématiques (4 EN + 4 FR) via Google News RSS (`when:1d`)
  - production EN/FR : `"cocoa" AND ("crop" OR "ivory coast" OR "ghana" OR "arrivals")`
  - chocolat EN/FR : `"cocoa" AND ("grindings" OR "chocolate demand" OR "processing")`
- [ ] Parsing XML (ElementTree), extraction titre + source + date par item
- [ ] Dedup par hash MD5 du titre (pattern TogetherCocoa Monitor)
- [ ] Max 10 items par requête, ~40-80 headlines/jour
- [ ] Headlines formatées comme section séparée dans le prompt (distincte des sources complètes pour le grounding)
- [ ] Le resume et le sentiment exploitent les deux couches

### AC2 — Prompt et fetcher ajustés
- [ ] OFFRE et FONDAMENTAUX remontés en priorité dans le prompt
- [ ] MARCHE réduit à 2-3 phrases contextuelles
- [ ] La sortie JSON conserve les 3 champs existants (resume, mots_cle, impact_synthetiques)
- [ ] Backward compat : les articles existants dans pl_fundamental_article ne sont pas impactés
- [ ] `MAX_CHARS_PER_SOURCE` passé de 2 000 à 4 000 chars — évite que les jours de publication lourde (grindings Q1, etc.) tronquent la section OFFRE au profit du contenu événementiel
- [ ] Instruction prompt ajoutée : privilégier tendances et contexte plutôt que chiffres exacts non vérifiables (évite propagation d'erreurs de transcription type Malaysia 91 496 vs 91 946)

### AC3 — Extraction sentiment structuré
- [ ] Nouveau champ `theme_sentiments` dans la sortie JSON du LLM
- [ ] Chaque thème : score [-1.0, +1.0], confidence [0.0, 1.0], rationale (1 phrase)
- [ ] Thèmes omis si les sources n'en parlent pas (pas d'invention)
- [ ] Validation optionnelle — l'article s'écrit même si theme_sentiments est absent
- [ ] Scores stockés dans `pl_article_segment` avec `extraction_version='inline_v1'`
- [ ] Écriture sentiment non-bloquante — si elle échoue, l'article est quand même persisté

### AC4 — Z-delta shadow mode
- [ ] Nouvelle table `pl_sentiment_feature` (date, theme, raw_score, zscore, zscore_delta)
- [ ] Z-score rolling 21 jours, min_periods=5
- [ ] Delta 3 jours : z[t] - z[t-3]
- [ ] Script CLI `poetry run compute-sentiment-features [--dry-run]`
- [ ] Log d'accumulation par thème (ex: `production=167/250`)
- [ ] Features NON injectées dans le composite score (shadow mode strict)

### AC5 — API + Frontend

**API :**
- [ ] Nouvel endpoint `GET /dashboard/news/sentiment?target_date=YYYY-MM-DD`
- [ ] Response : date, themes[] (score, confidence, rationale, zscore_delta, has_signal), accumulation

**Refonte "Analyse du Jour" — séparation technique / sentiment :**
- [ ] MACROECO retiré de la ligne des 6 gauges techniques (c'est un score LLM qualitatif mélangé avec des z-scores quantitatifs — incohérent)
- [ ] Section "Indicateurs Techniques" : 5 gauges (MACD, VOL/OI, RSI, %K, ATR) — même composant `GaugeIndicator`, mêmes données
- [ ] Nouvelle section "Sentiment Thématique" : 4 gauges (PRODUCTION, CHOCOLAT, TRANSFORMATION, ÉCONOMIE)
  - Même composant `GaugeIndicator` réutilisé (semi-circular SVG, color zones)
  - Échelle [-1.0, +1.0] au lieu des z-scores techniques
  - Zones couleur : rouge (bearish < -0.3) / orange (neutre) / vert (bullish > +0.3)
  - Tooltip avec rationale + confidence
  - Production et Chocolat marqués visuellement (signal significatif — étoile ou bordure)
  - Thèmes sans données du jour = gauge grisée N/A
- [ ] Le NewsCard existant (tabs, mots-clés, impact banner) est strictement inchangé

## Phases d'implémentation

### Phase 1 — Sources (AC1)

**Fichiers :**
- `backend/scripts/press_review_agent/config.py` — NEWS_SOURCES + GOOGLE_NEWS_QUERIES
- `backend/scripts/press_review_agent/news_fetcher.py` — ajout `fetch_google_news_headlines()`
- `backend/scripts/press_review_agent/README.md`

**Sources fixes — mix final (8 sources, validées par probe httpx le 17 avril) :**

| # | Source | Thème | Méthode | Status |
|---|--------|-------|---------|--------|
| 1 | Investing.com Cocoa | Marché | httpx | 200 ✅ |
| 2 | CocoaIntel | Production + Marché | httpx | 200 ✅ |
| 3 | ICCO News | Production | httpx | 200 ✅ |
| 4 | Confectionery News | Chocolat / Demande | httpx | 200 ✅ |
| 5 | Abidjan.net | Afrique / Production | httpx | 200 ✅ |
| 6 | Agence Ecofin Cacao | Afrique / Production | Playwright | ✅ |
| 7 | **Cacao.ci** | Production CI | httpx | 200 ✅ *nouveau* |
| 8 | **The Cocoa Post** | Production Ghana/Global | httpx | 200 ✅ *nouveau* |

Sources rejetées (probe 17 avril) : Commodafrica (503), Candy Industry (403), Barry Callebaut (contenu non extractible), WCF (404), CommodityBasis (404), The Public Ledger (DNS error), Reuters/Bloomberg/FT (WAF). Détails dans [press-review-v2-strategy.md](../press-review-v2-strategy.md).

**Google News RSS — couche de couverture :**
- Nouvelle fonction `fetch_google_news_headlines()` dans `news_fetcher.py`
- 8 requêtes thématiques (production EN/FR, chocolat EN/FR, marché EN/FR, offre EN/FR)
- Parsing XML avec `xml.etree.ElementTree` (pas de HTML, pas de follow)
- Dedup MD5 sur les titres, max 10 items/requête
- Retourne une liste de `NewsHeadline(title, source, date, theme)`
- Formatée comme section séparée dans le prompt pour le grounding

**Vérification :** `poetry run press-review --provider openai --dry-run --verbose` → sources fixes ≥ 5, headlines Google News ≥ 10, resume enrichi avec contenu Offre/Fondamentaux.

### Phase 2 — Prompt (AC2)

**Fichiers :**
- `backend/scripts/press_review_agent/config.py` — SYSTEM_PROMPT

**Actions :**
- Inverser la hiérarchie : OFFRE → FONDAMENTAUX → MARCHE (concis) → SENTIMENT
- Ajouter spec du 4ème champ `theme_sentiments` au JSON output
- Ajouter constante `THEMES = ("production", "chocolat", "transformation", "economie")`

### Phase 3 — Extraction sentiment (AC3)

**Fichiers :**
- `backend/scripts/press_review_agent/validator.py` — validation theme_sentiments
- `backend/scripts/press_review_agent/db_writer.py` — `write_theme_sentiments()`
- `backend/scripts/press_review_agent/main.py` — wiring après write_article()

**DB write dans `pl_article_segment` :**
- `zone = "all"` (cross-zone per EXP-014)
- `extraction_version = "inline_v1"`
- Sentiment dérivé du signe du score (bullish/bearish/neutral)
- facts = rationale du LLM

### Phase 4 — Z-delta shadow mode (AC4)

**Fichiers :**
- `backend/alembic/versions/xxx_add_pl_sentiment_feature.py` — migration
- `backend/app/models/pipeline.py` — PlSentimentFeature
- `backend/app/engine/sentiment_features.py` — compute_sentiment_zdelta()
- `backend/scripts/compute_sentiment_features/__init__.py` + `main.py`
- `backend/pyproject.toml` — poetry script entry

### Phase 5 — API + Frontend (AC5)

**Backend :**
- `backend/app/schemas/dashboard.py` — ThemeSentiment, NewsSentimentResponse
- `backend/app/services/dashboard_service.py` — get_theme_sentiments()
- `backend/app/api/api_v1/endpoints/dashboard.py` — endpoint sentiment

**Frontend — refonte "Analyse du Jour" :**
- `frontend/src/types/dashboard.ts` — types ThemeSentiment, NewsSentimentResponse
- `frontend/src/api/dashboard.ts` — getNewsSentiment()
- `frontend/src/hooks/useDashboard.ts` — useNewsSentiment()
- `frontend/src/components/market-analysis.tsx` — retirer MACROECO des 6 gauges → 5 gauges techniques
- `frontend/src/components/gauge-indicator.tsx` — vérifier que le composant supporte l'échelle [-1, +1] (actuellement z-scores non bornés)
- `frontend/src/components/sentiment-gauges.tsx` — nouveau composant : 4 gauges sentiment thématiques, réutilise GaugeIndicator avec config spécifique (échelle [-1, +1], zones rouge/orange/vert, tooltip rationale)
- Layout : section "Indicateurs Techniques" (5 gauges) au-dessus, section "Sentiment Thématique" (4 gauges) en dessous — même card MarketAnalysis ou deux cards séparées

## Objectif final

**Court terme (mai 2026)** : press review enrichie + extraction sentiment + scores visibles sur le dashboard + accumulation shadow mode.

**Moyen terme (octobre 2026)** : 250+ jours accumulés → re-run EXP-014 → si validé, intégration formelle dans le moteur (10 → 14 features).

## Lien avec autres chantiers

- **Chantier 2 — Scrapers fondamentaux** : projet séparé ([fundamental-data-scrapers.md](fundamental-data-scrapers.md)) pour ingérer les données structurées périodiques (grindings ECA/NCA, arrivages CCC). Complémentaire mais indépendant.
- **EXP-014** : expérience de normalisation qui a validé le signal. À re-runner quand n > 250.

## Risques

| Risque | Impact | Mitigation |
|--------|--------|------------|
| LLM ne produit pas theme_sentiments de façon fiable | Données manquantes | Champ optionnel, article s'écrit quand même |
| Nouvelles sources fixes inaccessibles (WAF, paywall) | Mix de sources dégradé | Probe httpx validé le 17 avril, fallback sur sources existantes |
| Google News RSS change de format ou rate-limit | Perte de la couche headlines | Les sources fixes suffisent seules — Google News est un bonus, pas une dépendance critique. Format RSS stable depuis 10+ ans (cf. DEEP_DIVE.md) |
| Token budget insuffisant (4ème champ + headlines) | Output tronqué | ~300-500 tokens de headlines + ~100 pour theme_sentiments, largement dans le budget 8192 |
| Signal ne se réplique pas à n > 250 | Shadow mode inutile | Coût d'accumulation quasi-nul, on décide après re-validation |
| MAX_CHARS 4000 capte du bruit (sidebar, pubs) | Contenu non pertinent dans le prompt | Le LLM filtre via grounding. Possibilité d'affiner les sélecteurs CSS si nécessaire |
