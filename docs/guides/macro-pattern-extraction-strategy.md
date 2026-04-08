# Extraction de Patterns Macro-Economiques — Strategie et Approches

**Date**: Avril 2026
**Auteur**: Hedi Blagui — CTO
**Statut**: Exploratoire

---

## 1. Contexte et Objectif

### Le corpus

Commodities Compass collecte quotidiennement des analyses textuelles du marche cacao depuis avril 2025 :

| Source | Volume | Periode | Contenu type |
|--------|--------|---------|-------------|
| `pl_fundamental_article` (legacy) | 208 articles | Avr 2025 - Mar 2026 | Press reviews LLM (francais, ~2000 chars) |
| `pl_fundamental_article` (openai) | 13 articles | Mar - Avr 2026 | Press reviews o4-mini (francais, ~1900 chars) |
| `pl_weather_observation` | 259 observations | Mai 2022 - Avr 2026 | Analyses meteo des zones cacaoyeres (~2200 chars) |
| `pl_contract_data_daily` | 2 579 lignes | Jan 2016 - Avr 2026 | OHLCV + IV + stocks + positions |

Chaque article couvre potentiellement : prix de marche (MARCHE), fondamentaux (FONDAMENTAUX), offre (OFFRE), sentiment (SENTIMENT MARCHE). Ces sections sont conditionnelles — un article pauvre en sources ne couvre que le marche.

### L'objectif

Extraire des **patterns generalisables** a partir de ces textes, segmentes selon deux axes :

**Axe geographique (2 zones)**
- **Afrique de l'Ouest** : Cote d'Ivoire, Ghana, Nigeria, Cameroun — la production
- **Monde** : marches internationaux, Europe, Asie, Ameriques — la demande et la transformation

**Axe thematique (4 sections — taxonomie metier)**
1. **Production du cacao** : recolte, arrivages, surfaces plantees, rendements, maladies, meteo cultures, stocks certifies
2. **Premiere transformation** : broyages (grindings), capacites usines, semi-produits (beurre, poudre, liqueur)
3. **Chocolat** : demande consommateur, ventes, reformulation, substitution, saisonnalite
4. **Economie** : prix marche, devises, politiques commerciales, speculation, reglementation, tarifs douaniers

### Usage potentiel des patterns decouverts

L'usage exact n'est pas defini a ce stade — c'est exploratoire. Trois pistes :
- **Dashboard BI** : visualiser les tendances thematiques, les causalites recurrentes, l'evolution du sentiment par zone
- **Input pour le Daily Analysis LLM** : enrichir le contexte du bot de trading avec des patterns historiques identifies
- **Signal trading** : correler sentiment/causalites extraits avec les mouvements de prix (backtesting)

---

## 2. Etat de l'art — Ce que dit la recherche

### 2.1 Text Mining applique aux commodites

**"Forecasting Commodity Price Shocks Using Temporal and Semantic Fusion"** (2025, arXiv)
Framework hybride combinant prix historiques et signaux semantiques extraits de news economiques via un pipeline generatif. Dual-stream LSTM avec attention pour fusionner series temporelles et embeddings textuels. AUC=0.94, accuracy=0.91. Directement pertinent : montre que des signaux textuels peuvent etre fusionnes avec des donnees de prix pour le forecasting.

**"Incorporating Market Risk Perception in Copper Commodity Price Forecasting"** (Wu et al., 2025, IEEE BigData)
Construit un **index de sentiment a 4 dimensions** (supply, demand, financial environment, policy) a partir de text mining de rapports commodity. Le mecanisme dual-track pour l'identification des risques explicites et variants est architecturalement proche de notre besoin : segmenter le texte en signaux offre vs demande. **Ce papier valide notre approche 4 themes.**

**"Assessing Text Mining and Technical Analyses on Forecasting Financial Time Series"** (Lashgari, 2023)
Compare le sentiment derive de FinBERT avec l'analyse technique pour la prediction du S&P 500. FinBERT surpasse ARIMA/GARCH/LSTM. Methodologie pertinente : sentiment transformer fine-tune comme feature input a cote des indicateurs techniques.

### 2.2 Extraction structuree depuis des textes financiers

**"Harnessing Generative LLMs for Enhanced Financial Event Entity Extraction"** (2025, arXiv)
Reformule l'extraction d'entites comme generation text-to-structured-output. Utilise du Parameter-Efficient Fine-Tuning (PEFT/LoRA) sur des LLMs pre-entraines pour generer directement des objets JSON. Directement applicable : definir un schema d'extraction (zone, theme, entites, liens causaux) et extraire avec un LLM.

**"LLM-enhanced multi-causal event causality mining in financial texts"** (2025, Journal of King Saud University)
Premier travail sur la causalite multi-cause/multi-effet dans le texte financier. Utilise LLM + raisonnement causal base sur des graphes pour detecter les causes indirectes sur plusieurs phrases. Pertinent pour extraire des chaines causales comme : "secheresse au Ghana -> baisse des arrivages -> deficit offre -> hausse des prix".

**Instructor** (Python, 11k GitHub stars, 3M+ downloads mensuels)
Librairie production-grade pour l'extraction structuree LLM via des modeles Pydantic. Compatible OpenAI, Claude, Gemini. Definir le schema comme des classes Pydantic et obtenir une sortie validee et typee. C'est l'outil le plus immediatement implementable pour notre cas.

### 2.3 Topic modeling et decouverte de patterns

**BERTrend** (RTE France, 2024, open source, MPL v2)
Topic modeling neuronal pour la detection de tendances emergentes. Construit sur BERTopic avec tracking temporel. Classifie les topics en **noise / weak signal / strong signal** selon la tendance de popularite. Inclut l'evaluation de stabilite, la volatilite, et des outils de visualisation. **C'est l'outil open source le plus pertinent** — il fait exactement ce dont on a besoin : tracker l'evolution des topics dans un corpus de documents, detecter les signaux emergents, et distinguer les patterns persistants du bruit.

**BERTopic pour l'agriculture** (2024, ScienceDirect/PMC)
Compare BERTopic vs LDA sur un corpus agricole. BERTopic coherence=0.7 vs LDA=0.27. Pipeline optimal : sentence embeddings + UMAP + HDBSCAN + NER-based stop words + c-TF-IDF. Identifie 37 topics distincts organises en 8 sous-domaines.

**AgriLens** (2025, arXiv)
"Semantic Retrieval in Agricultural Texts Using Topic Modeling and Language Models." Utilise BERTopic avec des embeddings transformer et class-based TF-IDF pour un corpus agricole.

### 2.4 Knowledge Graphs causaux

**FinDKG** (2024, arXiv/GitHub, open source)
Dynamic knowledge graph a partir de news financieres sur 20+ ans. Utilise ICKG (Vicuna-7B fine-tune) pour convertir des news non structurees en triplets KG structures. Capture 15 types de relations et 12 types d'entites. Snapshots temporels hebdomadaires. L'approche KG temporel (snapshots hebdo) mappe directement sur nos rapports quotidiens cacao.

**FinCaKG-Onto** (2025, Applied Intelligence/Springer)
Knowledge graph de causalite financiere avec integration ontologique. Utilise BERT-based causality detection + entity linking vers FIBO (Financial Industry Business Ontology). Atteint 95.6% de consistance ontologique.

**"Text to Causal Knowledge Graph"** (2023, MDPI Information)
Framework utilisant SpanBERT (F1=0.89) pour l'extraction cause-effet depuis des rapports business. Tokens labeles Cause (C), Effect (E), Causal Trigger (CT). Synthetise des graphes causaux diriges.

### 2.5 NLP francais — modeles et outils

| Modele / Outil | Usage | Pertinence |
|----------------|-------|-----------|
| **CamemBERT** | Meilleur BERT francais — sentiment, NER | Haute — backbone pour tout NLP francais |
| **sentence-camembert-large** | Embeddings de phrases francaises (1024-dim) | Haute — pour BERTopic/clustering |
| **BERTrend** (rte-france) | Topic modeling temporel + detection tendances | Haute — exactement notre besoin |
| **BERTopic** | Topic modeling avec transformers | Haute — base pour la decouverte de patterns |
| **Instructor** (567-labs) | Extraction structuree LLM avec Pydantic | Haute — compatible avec notre stack |
| **spaCy fr_core_news_lg** | NER, POS tagging, parsing francais | Moyenne — extraction d'entites baseline |
| **FinDKG** | Dynamic financial knowledge graph | Moyenne — architecture de reference pour KG |

---

## 3. Trois approches proposees

### Approche A — Extraction structuree LLM

**Principe** : passer chaque article existant dans un LLM avec un schema Pydantic strict qui force la segmentation 2 zones x 4 themes.

**Schema de sortie** :
```
Article du 2026-04-07
    |
    v  LLM (o4-mini, single call)
    |
    +-- Segment 1: zone=afrique_ouest, theme=production
    |     facts: "Arrivages CI 1,445 Mt (+0.2% y/y)"
    |     causal_chains: [{cause: "pluies regulieres", effect: "arrivages stables", direction: "neutre"}]
    |     sentiment: neutre, score: 0.05
    |     entities: [{type: "lieu", value: "Cote d'Ivoire"}, {type: "chiffre", value: "1,445 Mt"}]
    |     confidence: 0.85
    |
    +-- Segment 2: zone=monde, theme=economie
    |     facts: "Londres 2 459 GBP/t (-5.16%), New York -214$ (-6.62%)"
    |     causal_chains: [{cause: "correction technique", effect: "baisse cours", direction: "baissier"}]
    |     sentiment: baissier, score: -0.65
    |     entities: [{type: "lieu", value: "Londres"}, {type: "chiffre", value: "2 459 GBP/t"}]
    |     confidence: 0.92
    |
    +-- Segment 3: zone=monde, theme=transformation
          facts: "Expeditions de pate -7.14%"
          causal_chains: [{cause: "demande en recul", effect: "baisse expeditions pate", direction: "baissier"}]
          ...
```

**Decouverte de patterns** : une fois les segments stockes en base, requetes SQL analytiques :
- Frequence des chaines causales par zone/theme
- Correlation sentiment extrait vs mouvement de prix J+1
- Detection de patterns recurrents (`GROUP BY cause, effect HAVING count > N`)
- Evolution temporelle du sentiment par zone/theme

**Effort** : 2-3 jours
**Cout** : ~$2-4 pour le backfill de 221 articles (o4-mini)
**Avantage** : exploite l'infra existante (OpenAI, Pydantic, PostgreSQL), resultat immediat, pas de modele ML a entrainer
**Limite** : le LLM extracteur est aussi bon que le LLM qui a ecrit l'article — pas de decouverte de patterns latents au-dela de ce qui est explicitement ecrit

---

### Approche B — Topic modeling temporel (BERTrend)

**Principe** : laisser un modele non-supervise decouvrir les topics qui emergent et evoluent dans le corpus, sans imposer la taxonomie a priori.

**Pipeline** :
```
221 articles (ou segments de l'Approche A)
    |
    v  sentence-camembert-large (embeddings francais)
    |
    v  UMAP (reduction dimensionnelle)
    |
    v  HDBSCAN (clustering)
    |
    v  c-TF-IDF (representation des topics)
    |
    v  BERTrend (tracking temporel)
    |
    +-- Topic 1: "secheresse Ghana" — STRONG SIGNAL (croissant depuis Dec)
    +-- Topic 2: "surplus 2025/26" — WEAK SIGNAL (apparu en Mars)
    +-- Topic 3: "broyages Europe en baisse" — STRONG SIGNAL (stable)
    +-- Topic 4: "cours ICE London" — PERSISTENT (toujours present)
    +-- Topic 5: "tarifs douaniers" — EMERGING (apparu cette semaine)
    ...
```

**Ce que ca donne** :
- Topics auto-decouverts — pas limites a notre grille 2x4
- Classification automatique en **weak signal / strong signal / noise**
- Visualisation de l'evolution des topics sur les 11 mois de donnees
- Mapping possible des topics decouverts vers notre taxonomie metier

**Effort** : 1-2 semaines (incluant setup ML deps, experimentation)
**Cout** : negligeable (inference locale, pas d'appels API)
**Avantage** : decouvre des patterns qu'on n'aurait pas cherches (unknown unknowns). Detecte les signaux emergents.
**Limite** : 221 articles est borderline pour BERTopic (~100 min, ~1000 recommande). Pas de causalite, juste de la co-occurrence. Necessite des dependances lourdes (~2GB: torch, transformers).

**Mitigation du volume** : si on execute l'Approche A d'abord, les segments (3-6 par article) multiplient le corpus a ~800-1200 documents — suffisant pour BERTopic.

---

### Approche C — Knowledge Graph causal

**Principe** : extraire des triplets (entite, relation, entite) de chaque article et construire un graphe causal qui accumule de la connaissance au fil du temps.

**Architecture** :
```
Article quotidien
    |
    v  LLM extraction (Instructor/Pydantic)
    |
    (Ghana, reduced_production, 15%)
    (Drought, causes, reduced_production)
    (reduced_production, leads_to, supply_deficit)
    (supply_deficit, drives, price_increase_london)
    |
    v  Stockage PostgreSQL (ou Neo4j si volume justifie)
    |
    pl_causal_triple(date, source_entity, relation, target_entity, zone, theme, confidence)
    |
    v  Agregation temporelle
    |
    Graphe causal cumulatif
```

**Ontologie cacao** (a definir) :

| Categorie | Entites |
|-----------|---------|
| Regions | Ghana, Cote d'Ivoire, Cameroun, Nigeria, Ecuador, Bresil |
| Marches | ICE London, ICE New York, marche physique |
| Metriques | arrivages, broyages, stocks, deficit, surplus, production |
| Phenomenes | secheresse, black pod, harmattan, El Nino, inondations |
| Acteurs | speculateurs, commerciaux, industriels, planteurs |
| Produits | feves, beurre, poudre, liqueur, chocolat |

| Relations | Semantique |
|-----------|-----------|
| `causes` | A provoque directement B |
| `correlates_with` | A et B varient ensemble |
| `precedes` | A apparait avant B dans le temps |
| `mitigates` | A reduit l'effet de B |
| `amplifies` | A renforce l'effet de B |

**Requetes possibles une fois le graphe construit** :
- "Quelles chaines causales apparaissent >5 fois et precedent une hausse de prix ?"
- "Quels facteurs Afrique de l'Ouest vs Monde ont le plus d'impact sur le prix ?"
- "Y a-t-il des patterns saisonniers dans les chaines causales ?"
- "Quels phenomenes weather ont historiquement le plus d'impact sur la production ?"

**Effort** : 2-4 semaines
**Cout** : ~$5-10 pour l'extraction (plus de tokens par article a cause de l'ontologie)
**Avantage** : le seul qui capture la causalite multi-hop (secheresse -> baisse arrivages -> deficit -> hausse prix). Accumule du savoir structurel long-terme.
**Limite** : le plus lourd a implementer. Necessite une ontologie domaine bien definie et iteree. Qualite fortement dependante du prompt engineering.

---

## 4. Comparaison des approches

| Critere | A — Extraction LLM | B — BERTrend | C — Knowledge Graph |
|---------|-------------------|-------------|-------------------|
| **Effort** | 2-3 jours | 1-2 semaines | 2-4 semaines |
| **Cout API** | ~$2-4 | $0 (local) | ~$5-10 |
| **Infra requise** | Existante (OpenAI + PG) | +torch, transformers (~2GB) | Existante (OpenAI + PG) |
| **Type de patterns** | Explicites (ce qui est ecrit) | Latents (topics emergents) | Causaux (chaines cause-effet) |
| **Segmentation 2x4** | Forcee par le schema | Decouverte libre (mappable ensuite) | Forcee par l'ontologie |
| **Volume min** | 1 article suffit | ~100-1000 docs | 50+ articles |
| **Correlation prix** | Via JOIN SQL | Via regression sur topics | Via graph queries |
| **Decouverte** | Known knowns | Unknown unknowns | Known unknowns (causalite) |
| **Maintenance** | Faible (prompt tuning) | Moyenne (re-entrainement periodique) | Elevee (evolution ontologie) |

---

## 5. Recommandation : Layer Cake (A -> B -> C)

Les trois approches ne sont pas mutuellement exclusives — elles se nourrissent les unes les autres :

```
Phase 1: Approche A (Extraction LLM)
    |
    |  Produit: ~800-1200 segments structures en base
    |  Valeur: requetable SQL immediatement, correlation prix
    |
    v
Phase 2: Approche B (BERTrend)
    |
    |  Input: segments de Phase 1 (pas les articles bruts)
    |  Produit: topics auto-decouverts + signaux emergents
    |  Valeur: decouvre ce qu'on n'a pas cherche
    |
    v
Phase 3: Approche C (Knowledge Graph) — optionnel
    |
    |  Input: enrichi par les insights de Phase 1 + 2
    |  Produit: graphe causal cumulatif
    |  Valeur: intelligence structurelle long-terme
```

**Phase 1 est le fondement** — elle produit les donnees structurees qui alimentent tout le reste. On peut s'arreter a n'importe quelle phase.

**Decision gate entre chaque phase** : on evalue les resultats avant de continuer. Si Phase 1 revele que les articles sont trop pauvres pour la grille 2x4 (ex: 80% des segments sont zone=monde, theme=economie), on ajuste la taxonomie avant de passer a Phase 2.

---

## 6. Risques et mitigations

| Risque | Impact | Mitigation |
|--------|--------|-----------|
| Corpus trop petit (221 articles) pour BERTopic | Phase 2 instable | Phase 1 multiplie les docs (segments). Attendre d'avoir 6+ mois de donnees supplementaires. |
| Articles trop centres "marche" — peu de contenu sur transformation/chocolat | Grille 2x4 desequilibree | Analyser la distribution apres Phase 1. Ajuster la taxonomie si necessaire. |
| LLM hallucine des causalites non presentes dans le texte | Faux patterns | Instruction stricte "n'invente rien, omets si absent". Score de confiance. Validation croisee. |
| Dependances ML lourdes (Phase 2) alourdissent l'image Docker prod | Regression deploy | Groupe de dependances optionnel (`poetry group ml`). Dockerfile separe pour ML. |
| Ontologie cacao (Phase 3) trop rigide ou trop large | Extraction bruitee | Iterer l'ontologie sur un echantillon avant le backfill complet. |
| Correlation sentiment-prix = spurious | Faux signal trading | Backtesting rigoureux. Ne jamais utiliser comme signal unique. |

---

## 7. References

### Papers
- Wu et al. (2025) — "Incorporating Market Risk Perception in Copper Commodity Price Forecasting", IEEE BigData
- "Forecasting Commodity Price Shocks Using Temporal and Semantic Fusion" (2025), arXiv
- Lashgari (2023) — "Assessing Text Mining and Technical Analyses on Forecasting Financial Time Series"
- "Harnessing Generative LLMs for Enhanced Financial Event Entity Extraction" (2025), arXiv
- "LLM-enhanced multi-causal event causality mining in financial texts" (2025), J. King Saud University
- "BERTopic for Precision Agriculture" (2024), ScienceDirect/PMC
- "AgriLens: Semantic Retrieval in Agricultural Texts" (2025), arXiv
- FinDKG (2024), arXiv — Dynamic Knowledge Graph from Financial News
- FinCaKG-Onto (2025), Applied Intelligence/Springer
- "Text to Causal Knowledge Graph" (2023), MDPI Information
- CAMEF (2025), KDD — Causal-Augmented Multi-Modality Event-Driven Financial Forecasting

### Outils open source
- BERTrend (RTE France) — github.com/rte-france/BERTrend
- BERTopic — github.com/MaartenGr/BERTopic
- Instructor — python.useinstructor.com
- FinDKG — github.com/xiaohui-victor-li/FinDKG
- CamemBERT — huggingface.co/camembert
- sentence-camembert-large — huggingface.co/dangvantuan/sentence-camembert-large
