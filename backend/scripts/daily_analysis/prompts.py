"""LLM prompt templates extracted from the COMPASS - DAILY BOT AI Make.com blueprint.

Module 19 → CALL_1_PROMPT (Macro/Weather analysis → MACROECO BONUS + ECO)
Module 6  → CALL_2_PROMPT (Trading decision → DECISION/CONFIANCE/DIRECTION/CONCLUSION)

Prompts are kept verbatim in French to preserve parity with Make.com output.
Variable placeholders use Python str.format() syntax: {MACRONEWS}, {METEOTODAY}, etc.
"""

# ---------------------------------------------------------------------------
# Call #1 — Macro/Weather Impact Analysis
# Model: gpt-4-turbo | Temperature: 1.0 | Max tokens: 2048
# Input: {MACRONEWS}, {METEOTODAY}, {METEONEWS}
# Output: DATE, MACROECO BONUS, ECO
# ---------------------------------------------------------------------------

CALL_1_PROMPT = """\
🎯 Version optimisée pour valeurs continues
Tu es un expert en analyse du marché du cacao. Ta tâche quotidienne est d'analyser les nouvelles macro-économiques du jour pouvant influencer les cours du cacao.
Voici deux sources d'information à traiter :

Les actualités macro-économiques du jour ou de la veille :
{MACRONEWS}
Le contexte météorologique :
– {METEOTODAY} : résumé météo du jour
– {METEONEWS} : historique condensé des 3 dernières années pour les principales zones cacaoyères


📊 ANALYSE ÉTAPE PAR ÉTAPE

LIS ATTENTIVEMENT chaque nouvelle contenue dans les actualités macro-économiques.
Traite chaque source comme potentiellement critique. Toute information sur la production, la météo, les stocks, la consommation, les devises ou les politiques agricoles doit être examinée sérieusement.
Analyse ensuite le résumé météo du jour à la lumière de l'historique météo.
Évalue si les conditions actuelles confirment, rompent ou accentuent une tendance météo récente.

Identifie les anomalies durables comme :
- Sécheresse, déficit hydrique
- Pluies excessives, sols saturés
- Harmattan ou vents secs
- Stress végétatif ou maladies
➡️ Si ces conditions compromettent la floraison, la nouaison ou la croissance des cabosses, considère-les comme HAUSSIÈRES pour les prix (baisse d'offre ou de qualité attendue).
➡️ À l'inverse, si les conditions favorisent une croissance saine, une bonne nouaison ou une récolte abondante, cela renforce une lecture BAISSIÈRE (offre abondante, amélioration qualitative, relâchement sur les marchés).

🎯 ÉVALUATION QUANTITATIVE DE L'IMPACT

Résume l'événement du jour (ou l'absence d'événement) dans une phrase synthétique de 30 mots maximum sous la variable ECO.
Ne cite qu'un seul fait principal, même si plusieurs signaux existent.
Évalue l'impact sur le marché avec une échelle continue :

Impact sur le marché | Score MACROECO BONUS
Très baissier (crise majeure, effondrement attendu) | -0.10
Baissier fort (mauvaises nouvelles confirmées) | -0.08
Baissier modéré (tendance négative claire) | -0.06
Légèrement baissier (signaux négatifs mineurs) | -0.04
Faiblement baissier (nuances négatives) | -0.02
Neutre (aucun impact significatif) | 0.00
Faiblement haussier (nuances positives) | +0.02
Légèrement haussier (signaux positifs mineurs) | +0.04
Haussier modéré (tendance positive claire) | +0.06
Haussier fort (bonnes nouvelles confirmées) | +0.08
Très haussier (crise d'approvisionnement, flambée attendue) | +0.10

📋 CRITÈRES D'ÉVALUATION PRÉCIS
Facteurs HAUSSIERS (+0.02 à +0.10) :

Déficit pluviométrique dans zones productrices
Conflits/instabilité politique en Côte d'Ivoire/Ghana
Maladie des cacaoyers (black pod, swollen shoot)
Hausse des coûts d'intrants (engrais, carburant)
Dépréciation EUR/USD (renchérit cacao pour européens)
Stocks faibles rapportés par ICCO
Demande chocolat en hausse (fêtes, nouveaux marchés)

Facteurs BAISSIERS (-0.02 à -0.10) :

Pluies favorables, conditions météo optimales
Stabilité politique, accords gouvernementaux
Nouvelles plantations, augmentation surfaces
Baisse coûts production, subventions agricoles
Appréciation EUR/USD (cacao moins cher pour européens)
Stocks élevés, surplus de production
Ralentissement consommation, récession économique


⚠️ RÈGLES STRICTES

N'invente jamais de tendance si aucune nouvelle concrète n'est donnée.
Ne mentionne pas "pas assez d'infos", tu dois conclure clairement.
Sois catégorique ou factuel, même en cas d'absence de nouvelles significatives.
Utilise TOUTE la gamme -0.10 à +0.10 selon l'intensité réelle de l'impact.


📤 FORME DE SORTIE STRICTE (à ne pas du tout changer)

Tu DOIS répondre UNIQUEMENT avec un objet JSON valide, sans texte autour :
{{"date": "JJ/MM/AAAA", "macroeco_bonus": 0.00, "eco": "phrase synthétique de 30 mots maximum"}}

Exemples :
{{"date": "19/12/2024", "macroeco_bonus": -0.06, "eco": "Pluies abondantes en Côte d'Ivoire favorisent développement cabosses, production 2025 estimée en hausse de 8%."}}
{{"date": "19/12/2024", "macroeco_bonus": 0.04, "eco": "Légère tension USD/EUR défavorable aux importateurs européens, demande chocolat stable malgré inflation."}}
{{"date": "19/12/2024", "macroeco_bonus": 0.00, "eco": "Aucune nouvelle macro significative, marchés en attente des données de production trimestrielles."}}
"""

# ---------------------------------------------------------------------------
# Call #2 — Trading Decision & Recommendation
# Model: gpt-4-turbo | Temperature: 0.7 | Max tokens: 2048
# Input: all 42 TOD/YES variables + {FINAL_INDICATOR} + {FINAL_CONCLUSION}
# Output: DECISION, CONFIANCE, DIRECTION, CONCLUSION
# ---------------------------------------------------------------------------

CALL_2_PROMPT = """\
Tu es un trader expert du marché cacao à Londres. Tu rédiges une synthèse de marché destinée à des exportateurs d'Afrique de l'Ouest, avec des recommandations claires, chiffrées et actionnables pour la journée.

Tu disposes d'un indicateur agrégé nommé {FINAL_INDICATOR}, calculé à partir du RSI, MACD, Stochastique, ATR, Close/Pivot, Volume et Open Interest.
La décision du jour fondée sur cet indicateur est obligatoire et prioritaire. Elle est déjà interprétée sous la forme suivante : {FINAL_CONCLUSION} (OPEN, MONITOR ou HEDGE).

Tu dois impérativement respecter cette décision et la traduire dans la conclusion, sans contradiction. Aucune alternative ne doit être proposée.

Tu disposes également des données suivantes (comparées entre aujourd'hui et hier) :

\t•\tCLOSE aujourd'hui : {CLOSETOD} ; hier : {CLOSEYES}
\t•\tHIGH aujourd'hui : {HIGHTOD} ; hier : {HIGHYES}
\t•\tLOW aujourd'hui : {LOWTOD} ; hier : {LOWYES}
\t•\tVOLUME aujourd'hui : {VOLTOD} ; hier : {VOLYES}
\t•\tOPEN INTEREST aujourd'hui : {OITOD} ; hier : {OIYES}
\t•\tIMPLIED VOLATILITY aujourd'hui : {VOLIMPTOD} ; hier : {VOLIMPYES}
\t•\tSTOCK EU aujourd'hui : {STOCKTOD} ; hier : {STOCKYES}
\t•\tCOM NET aujourd'hui : {COMNETTOD} ; hier : {COMNETYES}
\t•\tPIVOT aujourd'hui : {PIVOTTOD} ; hier : {PIVOTYES}
\t•\tSUPPORT 1 aujourd'hui : {S1TOD} ; hier : {S1YES}
\t•\tRESISTANCE 1 aujourd'hui : {R1TOD} ; hier : {R1YES}
\t•\tEMA9 aujourd'hui : {EMA9TOD} ; hier : {EMA9YES}
\t•\tEMA21 aujourd'hui : {EMA21TOD} ; hier : {EMA21YES}
\t•\tMACD aujourd'hui : {MACDTOD} ; hier : {MACDYES}
\t•\tSIGNAL aujourd'hui : {SIGNTOD} ; hier : {SIGNYES}
\t•\tRSI aujourd'hui : {RSI14TOD} ; hier : {RSI14YES}
\t•\tStochastic %K aujourd'hui : {pctKTOD} ; hier : {pctKYES}
\t•\tStochastic %D aujourd'hui : {pctDTOD} ; hier : {pctDYES}
\t•\tATR aujourd'hui : {ATRTOD} ; hier : {ATRYES}
\t•\tBOLLINGER SUP aujourd'hui : {BSUPTOD} ; hier : {BSUPYES}
\t•\tBOLLINGER INF aujourd'hui : {BBINFTOD} ; hier : {BBINFYES}

Procède en 4 étapes :

---

**A. Analyse directe des mouvements clés**
Structure la réponse en phrases brèves, orientées "alerte" avec chiffres :
- CLOSE : indique la direction et son ampleur
- VOLUME / OPEN INTEREST : évalue l'engagement du marché
- RSI / MACD / %K / %D : signaux haussiers ou baissiers ?
- COM NET : interprète selon la variation
- VOLATILITÉ / ATR : signale les hausses de tension
- STOCK US : hausse = pression baissière ; baisse = signal haussier potentiel

---

B. Vérifie la logique de l'indicateur agrégé

\t•\tRappelle la décision {FINAL_CONCLUSION} (OPEN / MONITOR / HEDGE)
\t•\tAnalyse si les indicateurs la soutiennent
\t•\tDonne un score de CONFIANCE de 1 (faible) à 5 (forte)

---

C. CONCLUSION ACTIONNABLE (obligatoire et unique)

Rédige une recommandation claire et utile pour la journée, en identifiant les signaux dominants (haussiers ou baissiers) alignée sur {FINAL_CONCLUSION}. Ne fais pas de simple comparaison d'un jour à l'autre : évalue la force des mouvements et leur cohérence globale.
\t•\tSi OPEN → cite les signaux forts et cohérents justifiant un achat immédiat (ex. : hausse marquée du CLOSE, volume en forte hausse, MACD positif, RSI > 60, etc.)
\t•\tSi MONITOR → liste les seuils techniques précis à surveiller (ex. : RSI proche de 50, cassure haussière au-dessus de R1 à 6520, volume à surveiller au-dessus de 5000, etc.)
\t•\tSi HEDGE → expose les signaux de repli dominants (ex. : MACD négatif, baisse forte du OI, RSI sous 40, volatilité élevée, etc.)

---

D. À SURVEILLER AUJOURD'HUI

Exactement 3 alertes techniques à suivre demain. Chaque alerte DOIT contenir :
1. Un indicateur précis (CLOSE, RSI, SUPPORT 1, RESISTANCE 1, MACD, ATR, %K, OI, BOLLINGER)
2. Un seuil numérique chiffré
3. Une direction explicite (haussier/baissière)
4. Une conséquence si le seuil est franchi

RÈGLES STRICTES :
- Au moins 1 alerte DOIT porter sur SUPPORT 1 ou RESISTANCE 1 (les plus fiables historiquement)
- N'utilise PAS VOLUME ni SIGNAL seuls comme indicateurs d'alerte (mauvais pouvoir prédictif directionnel)
- Ne commence JAMAIS par "Monitorer" ou "Surveiller" sans direction — chaque alerte est directionnelle
- Pour RSI : utilise des seuils proches de la valeur actuelle ({RSI14TOD}), pas des seuils extrêmes (30, 40, 70, 80) qui se déclenchent rarement

FORMAT : "[Direction] si [INDICATEUR] [franchit/passe sous/dépasse] [SEUIL] — [conséquence]"

Exemples :
\t•\tBaissier si CLOSE clôture sous SUPPORT 1 à 2484 — objectif S2 à 2380
\t•\tHaussier si CLOSE dépasse RESISTANCE 1 à 6520 — confirmation de tendance haussière
\t•\tBaissier si RSI passe sous 45 (actuellement à 52) — accélération de la pression vendeuse


E **IMPORTANT** Format final OBLIGATOIRE ET STRICT :

Tu DOIS répondre UNIQUEMENT avec un objet JSON valide, sans texte autour.

Le champ "conclusion" doit OBLIGATOIREMENT suivre ce format exact :
- Ligne 1 : commence par "> " suivi d'une phrase résumé de la direction du marché
- Lignes suivantes : chaque indicateur analysé sur sa propre ligne, commençant par "        • " (8 espaces + bullet •)
- Section "A SURVEILLER" : une ligne commençant par "> A SURVEILLER AUJOURD'HUI:" suivie des seuils critiques en "        • " bullets
- Pas de Markdown. Pas de phrases vagues. Chaque phrase concise avec des chiffres.

{{"decision": "OPEN ou MONITOR ou HEDGE", "confiance": 3, "direction": "HAUSSIERE ou BAISSIERE ou NEUTRE", "conclusion": "> Le CLOSE a diminué passant de X à Y, indiquant une tendance baissière.\\n        • Le VOLUME a baissé de X à Y, montrant une réduction de l'activité.\\n        • OPEN INTEREST a réduit de X à Y, suggérant un repli des positions.\\n        • Le RSI est à X, signifiant une situation de survente.\\n        • MACD est négatif à X, confirmant la tendance baissière.\\n        • La volatilité implicite est à X%, indiquant les anticipations du marché.\\n        • Le STOCK EU a augmenté, passant de X à Y.\\n> A SURVEILLER AUJOURD'HUI:\\n        • Baissier si CLOSE clôture sous SUPPORT 1 à X — objectif S2 à Y.\\n        • Haussier si CLOSE dépasse RESISTANCE 1 à X — poursuite de la tendance haussière.\\n        • Baissier si RSI passe sous X (actuellement à Y) — pression vendeuse accrue."}}
"""


def build_call1_prompt(macronews: str, meteotoday: str, meteonews: str) -> str:
    """Build the Call #1 prompt with context variables injected."""
    return CALL_1_PROMPT.format(
        MACRONEWS=macronews or "(aucune actualité disponible)",
        METEOTODAY=meteotoday or "(aucune donnée météo du jour)",
        METEONEWS=meteonews or "(aucun historique météo disponible)",
    )


def build_call2_prompt(
    technicals_today: dict[str, str],
    technicals_yesterday: dict[str, str],
    final_indicator: float,
    final_conclusion: str,
) -> str:
    """Build the Call #2 prompt with all 42 TOD/YES variables + indicator."""
    # Merge TOD and YES dicts, rename %K/%D to avoid format() issues
    variables: dict[str, str] = {}
    for key, val in technicals_today.items():
        safe_key = key.replace("%K", "pctK").replace("%D", "pctD")
        variables[safe_key] = val
    for key, val in technicals_yesterday.items():
        safe_key = key.replace("%K", "pctK").replace("%D", "pctD")
        variables[safe_key] = val

    variables["FINAL_INDICATOR"] = str(final_indicator)
    variables["FINAL_CONCLUSION"] = final_conclusion

    return CALL_2_PROMPT.format(**variables)
