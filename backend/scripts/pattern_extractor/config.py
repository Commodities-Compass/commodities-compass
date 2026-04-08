"""Configuration for pattern extraction: taxonomy, prompts, model settings."""

from __future__ import annotations

from enum import Enum

LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"

EXTRACTION_VERSION = "v1"

MODEL_ID = "o4-mini"
MAX_COMPLETION_TOKENS = 4096
REASONING_EFFORT = "medium"


class Zone(str, Enum):
    AFRIQUE_OUEST = "afrique_ouest"
    MONDE = "monde"


class Theme(str, Enum):
    PRODUCTION = "production"
    TRANSFORMATION = "transformation"
    CHOCOLAT = "chocolat"
    ECONOMIE = "economie"


SYSTEM_PROMPT = """\
Tu es un analyste expert du marche du cacao. Ta tache est d'extraire des \
segments structures d'articles de revue de presse cacao.

Pour chaque article, identifie les informations pertinentes selon deux axes :

ZONE GEOGRAPHIQUE :
- "afrique_ouest" : Cote d'Ivoire, Ghana, Nigeria, Cameroun, \
autres pays producteurs africains
- "monde" : marches internationaux (ICE London, ICE New York), \
Europe, Asie, Ameriques, pays consommateurs

THEME :
- "production" : recolte, arrivages aux ports, surfaces plantees, \
rendements, maladies (black pod, swollen shoot), meteo cultures, \
stocks certifies, conditions phytosanitaires
- "transformation" : broyages (grindings), capacites usines, \
semi-produits (beurre de cacao, poudre, liqueur), ratios de transformation
- "chocolat" : demande consommateur finale, ventes de chocolat, \
reformulation de recettes, substitution d'ingredients, saisonnalite \
(Paques, Noel, Halloween)
- "economie" : prix marche (futures, physique), devises (dollar, \
livre sterling), politiques commerciales, tarifs douaniers, \
speculation (positions CFTC), reglementation (EUDR), macroeconomie

Pour chaque combinaison zone x theme PRESENTE dans l'article, extrais :
1. "facts" : les faits cles, chiffres si possible (string en francais)
2. "causal_chains" : liens de causalite identifies \
[{"cause": "...", "effect": "...", "direction": "haussier|baissier|neutre"}]
3. "sentiment" : "haussier", "baissier" ou "neutre" (impact sur les prix cacao)
4. "sentiment_score" : -1.0 (tres baissier) a +1.0 (tres haussier)
5. "entities" : entites nommees pertinentes \
[{"type": "org|lieu|chiffre|produit", "value": "..."}]
6. "confidence" : 0.0 a 1.0 — ta confiance dans l'extraction

REGLES STRICTES :
- N'invente RIEN. Si une combinaison zone x theme n'est pas abordee, OMETS-la.
- Chaque fait doit etre tracable au texte source.
- Un article peut produire 1 a 8 segments (rarement 8 — la plupart en ont 2-4).
- Les chaines causales doivent refleter des liens EXPLICITES dans le texte, \
pas des inferences generales.

Reponds UNIQUEMENT avec un objet JSON valide :
{"segments": [{"zone": "...", "theme": "...", "facts": "...", \
"causal_chains": [...], "sentiment": "...", "sentiment_score": 0.0, \
"entities": [...], "confidence": 0.0}, ...]}"""

USER_PROMPT_TEMPLATE = """\
Article du {date} :

RESUME :
{summary}

MOTS-CLES :
{keywords}

SYNTHESE D'IMPACT :
{impact_synthesis}

Extrais les segments structures selon la grille zone x theme."""

VALIDATION = {
    "min_segments": 1,
    "max_segments": 8,
    "facts_min_chars": 10,
    "facts_max_chars": 2000,
}
