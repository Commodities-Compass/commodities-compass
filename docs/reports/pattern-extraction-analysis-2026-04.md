# Analyse des Patterns Macro-Economiques Cacao

**Date** : 8 avril 2026
**Corpus** : 243 articles press review (avril 2025 - avril 2026)
**Methode** : Extraction structuree LLM (OpenAI o4-mini)
**Couverture** : 182/243 articles traites (75%), 672 segments extraits

---

## 1. Matrice de couverture zone x theme

|  | Production | Transformation | Chocolat | Economie | **Total** |
|---|---:|---:|---:|---:|---:|
| **Afrique de l'Ouest** | 174 | 22 | 0 | 55 | **251** |
| **Monde** | 79 | 80 | 85 | 177 | **421** |
| **Total** | **253** | **102** | **85** | **232** | **672** |

### Ce que ca revele

**Les 2 poles dominants** (collectivement 52% du corpus) :
- `afrique_ouest/production` (174 segments) — supply narrative : arrivages, recoltes, meteo, maladies
- `monde/economie` (177 segments) — price narrative : futures, devises, speculation

**Les angles morts** :
- `afrique_ouest/chocolat` = **0** — aucune couverture de la demande chocolat en Afrique. Or la consommation locale croit.
- `afrique_ouest/transformation` = 22 — faible. La politique de transformation locale (Cote d'Ivoire: objectif 50% de broyage local d'ici 2030) est sous-representee dans nos sources.

**Les themes equilibres** :
- `monde/transformation` (80) et `monde/chocolat` (85) sont bien couverts — les broyages europeens et la demande consommateur apparaissent regulierement.

---

## 2. Sentiment global

| Zone | Haussier | Baissier | Neutre | Score moyen |
|---|---:|---:|---:|---:|
| Afrique de l'Ouest | 80 | 96 | 75 | **-0.07** |
| Monde | 78 | 253 | 90 | **-0.23** |

### Lecture

Le marche est structurellement **baissier** sur la periode (avril 2025 - avril 2026), avec un biais plus prononce cote monde (-0.23) que cote Afrique (-0.07).

Cote monde, **3.2x plus de segments baissiers que haussiers** — les articles mettent en avant la demande faible, les surplus, et la pression sur les prix. Cote Afrique, c'est plus equilibre — la tension supply (secheresses, maladies) est contrebalancee par de bonnes recoltes sur certaines periodes.

---

## 3. Sentiment par theme (score moyen)

| Theme | Score | Interpretation |
|---|---:|---|
| Production | -0.13 | Legerement baissier — supply suffisant globalement |
| Transformation | -0.35 | **Nettement baissier** — broyages en recul, demande industrielle faible |
| Chocolat | -0.31 | **Baissier** — demande consommateur sous pression (prix, reformulation) |
| Economie | -0.19 | Baissier modere — pression des devises et speculation vendeuse |

Le theme **transformation** est le plus baissier (-0.35) — signal coherent avec la tendance mondiale de recul des broyages sur la periode.

---

## 4. Evolution temporelle du sentiment

### Afrique de l'Ouest / Production

| Periode | Segments | Sentiment |
|---|---:|---:|
| Mai-Juin 2025 | 31 | **+0.15** (optimisme recolte) |
| Jul-Sep 2025 | 49 | **-0.01** (stabilisation) |
| Oct-Dec 2025 | 33 | **-0.23** (craintes secheresse) |
| Jan-Mar 2026 | 58 | **-0.15** (incertitude mi-recolte) |

Retournement clair de sentiment entre Q2 2025 (optimiste) et Q4 2025 (pessimiste), avec une stabilisation en Q1 2026.

### Monde / Economie

| Periode | Segments | Sentiment |
|---|---:|---:|
| Mai-Juin 2025 | 26 | **-0.02** (neutre) |
| Jul-Sep 2025 | 51 | **-0.17** (debut pression baissiere) |
| Oct-Dec 2025 | 35 | **-0.25** (pression prix confirmee) |
| Jan-Mar 2026 | 62 | **-0.41** (acceleration baissiere) |

**Tendance claire** : le sentiment economique mondial se degrade lineairement sur 12 mois. Acceleration en Q1 2026 (-0.41).

### Monde / Transformation

| Periode | Segments | Sentiment |
|---|---:|---:|
| Mai-Juin 2025 | 10 | **-0.01** (neutre) |
| Jul-Sep 2025 | 25 | **-0.47** (chute des broyages) |
| Oct-Dec 2025 | 23 | **-0.37** (stagnation basse) |
| Jan-Mar 2026 | 21 | **-0.53** (nouveau creux) |

La transformation est le theme ou le basculement est le plus brutal : de neutre en mai-juin a tres baissier des juillet 2025. Pas de recovery.

---

## 5. Chaines causales — patterns recurrents

### Top categories de causes (1137 chaines extraites)

| Categorie cause | Baissier | Haussier | Neutre | Total |
|---|---:|---:|---:|---:|
| DEMANDE | 64 | 7 | 6 | **77** |
| SURPLUS/OFFRE | 59 | 12 | 3 | **74** |
| PRODUCTION/ARRIVAGES | 42 | 40 | 23 | **105** |
| METEO/SECHERESSE | 43 | 36 | 14 | **93** |
| STOCKS | 43 | 22 | 5 | **70** |
| TRANSFORMATION | 34 | 7 | 8 | **49** |
| SPECULATION | 21 | 18 | 11 | **50** |
| REGLEMENTATION | 18 | 6 | 3 | **27** |
| DEVISES | 17 | 11 | 0 | **28** |

### Lecture

**DEMANDE** = massivement baissier (64 baissier vs 7 haussier). Signal le plus unidirectionnel du corpus — la demande est systematiquement decrite comme faible.

**PRODUCTION/ARRIVAGES** = le plus equilibre (42 baissier vs 40 haussier). La production oscille entre risques (secheresse, maladies) et bonnes nouvelles (recoltes CI).

**METEO/SECHERESSE** = 43 baissier vs 36 haussier. Contra-intuitif : la meteo est a la fois une cause de baisse (surplus via bonnes pluies) et de hausse (secheresse → deficit).

**SPECULATION** = quasi neutre (21 baissier vs 18 haussier). Les positions speculatives ne sont pas directionnellement biaisees dans le recit.

### Chaines les plus recurrentes

| Cause | Effet | Direction | Occurrences |
|---|---|---|---:|
| Demande faible | Baisse des prix | Baissier | 3 |
| Stocks tombants | Hausse potentielle prix | Haussier | 2 |
| Hausse stocks ICE | Pression baissiere prix | Baissier | 2 |
| Prix eleves | Baisse de la demande | Baissier | 2 |
| Production Ghana en hausse | Pression baissiere prix | Baissier | 2 |
| Pluies abondantes | Perturbation mi-recolte | Haussier | 2 |

Note : la plupart des chaines sont uniques (occurrences = 1) car le LLM les formule differemment a chaque article. L'agregation par categorie (section precedente) est plus robuste.

---

## 6. Entites les plus mentionnees

### Lieux

| Entite | Mentions |
|---|---:|
| Cote d'Ivoire | 209 |
| Londres (ICE) | 152 |
| New York (ICE) | 131 |
| Ghana | 89 |
| Europe | 86 |
| Asie | 55 |
| Amerique du Nord | 46 |
| Etats-Unis | 31 |

### Organisations

| Entite | Mentions |
|---|---:|
| ICCO | 65 |
| Barry Callebaut | 48 |
| ICE / ICE London / ICE NY | 114 |
| Rabobank | 32 |
| CocoaIntel | 25 |
| Mondelez | 21 |
| Citigroup | 19 |

### Chiffres cles recurrents

| Chiffre | Mentions | Contexte |
|---|---:|---|
| 2 800 FCFA/kg | 34 | Prix bord champ CI |
| 49 000 t | 25 | Stocks certifies ICE |
| 4,69 Mt | 22 | Production mondiale estimee |

---

## 7. Findings cles

### 7.1 Le recit dominant : baisse de la demande, pas hausse de l'offre

Contrairement au narratif "crise de l'offre cacao", les articles de la periode pointent principalement vers une **faiblesse de la demande** comme driver principal du marche baissier. La categorie DEMANDE est la plus directionnellement baissiere (rapport 9:1).

### 7.2 La transformation est le signal le plus precoce

Le theme `monde/transformation` passe de neutre a tres baissier en juillet 2025 — **3 mois avant** le retournement du theme `monde/economie`. Les broyages sont un leading indicator du sentiment global.

### 7.3 Le sentiment Afrique est deconnecte du sentiment Monde

Score moyen Afrique = -0.07 vs Monde = -0.23. La production ouest-africaine est percue comme resiliente malgre les risques meteo. Le marche est tire vers le bas par la demande, pas par l'offre.

### 7.4 Angle mort : transformation locale Afrique

22 segments sur `afrique_ouest/transformation` vs 0 sur `afrique_ouest/chocolat`. La strategie de montee en gamme (broyage local, valeur ajoutee) est un sujet politique majeur mais quasi absent des sources news trader-centric.

### 7.5 Les chaines causales sont trop fragmentees pour du pattern matching direct

La plupart des chaines sont a occurrence unique. L'agregation par categorie est efficace, mais pour du vrai pattern matching, il faudra soit normaliser les chaines (embeddings + clustering), soit augmenter le corpus.

---

## 8. Recommandations

### Sources a ajouter au press review agent
- **ICCO Quarterly Bulletin** — couverture transformation/grinding globale
- **Confectionery News / Candy Industry** — demande chocolat consommateur
- **Commodafrica / Jeune Afrique Economie** — transformation locale Afrique
- **CFTC COT Reports** (deja scraped mais pas dans press review) — positions speculatives

### Exploitation possible des segments
1. **Dashboard widget** : sentiment moyen par zone/theme sur 30 jours glissants
2. **Input pour Daily Analysis** : injecter le sentiment moyen zone/theme dans le prompt du bot de trading
3. **Alerting** : detecter les retournements de sentiment (ex: transformation passe de neutre a baissier)

### Ameliorations pipeline
- Ajouter les aliases manquants (entity types: `temps`, `phenomene`, `concept`)
- Augmenter le `max_completion_tokens` pour les articles longs (>2000 chars)
- Retraiter les 61 articles en echec apres les fixes

---

## 9. Methodologie

- **Extraction** : OpenAI o4-mini (reasoning_effort=medium, max_tokens=4096)
- **Schema** : Pydantic strict — zone (2 valeurs), theme (4 valeurs), sentiment (3 valeurs + score numerique), causal chains, entities
- **Normalisation** : aliases pour zones, themes, types d'entites, directions de causalite
- **Merge** : segments dupliques (meme zone x theme) fusionnes avant ecriture
- **Cout total** : ~$3.50 pour 243 articles
- **Taux de succes** : 75% (182/243). Echecs principalement dus a des empty responses (o4-mini) et des types d'entites non normalises
- **Stockage** : table `pl_article_segment` sur PostgreSQL local (branche `feat/pattern-extractor`)
