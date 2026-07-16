"""LLM prompt templates extracted from the COMPASS - DAILY BOT AI Make.com blueprint.

Module 19 → CALL_1_PROMPT (Macro/Weather analysis → MACROECO BONUS + ECO)

Call #2 (the trading decision) no longer lives here: post the US-1c facts/voice
refactor the LLM emits only a voice-only headline (built in ``voice_prompts.py``)
and the engine renders the numbered conclusion from the ``FactsPayload``. What
remains is Call #1 and the shared ensemble-diagnostics helpers that
``voice_prompts.py`` still imports.

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

# English edition (US-3, EN/Ghana). Native English generation — NOT a literal
# translation of the FR output: the model writes a fresh English ``eco`` here,
# it never re-types the French sentence. The JSON shape (date / macroeco_bonus /
# eco) and the -0.10..+0.10 score scale are identical to the FR prompt so the
# parser + downstream numeric pipeline are language-agnostic.
CALL_1_PROMPT_EN = """\
🎯 Optimised version for continuous values
You are an expert cocoa-market analyst. Your daily task is to analyse today's macro-economic news that could move cocoa prices.
Two information sources to process:

Today's or yesterday's macro-economic news:
{MACRONEWS}
Weather context:
– {METEOTODAY}: today's weather summary
– {METEONEWS}: condensed history of the last 3 years for the main cocoa-growing regions


📊 STEP-BY-STEP ANALYSIS

READ CAREFULLY each item in the macro-economic news.
Treat every source as potentially critical. Any information on production, weather, stocks, consumption, currencies or agricultural policy must be examined seriously.
Then analyse today's weather summary in the light of the weather history.
Assess whether current conditions confirm, break or reinforce a recent weather trend.

Identify durable anomalies such as:
- Drought, water deficit
- Excessive rain, saturated soils
- Harmattan or dry winds
- Vegetative stress or disease
➡️ If these conditions threaten flowering, pod-set or pod growth, treat them as BULLISH for prices (expected drop in supply or quality).
➡️ Conversely, if conditions favour healthy growth, good pod-set or an abundant harvest, that reinforces a BEARISH read (ample supply, quality improvement, easing on the markets).

🎯 QUANTITATIVE IMPACT ASSESSMENT

Summarise the day's event (or the absence of one) in a single synthetic sentence of 30 words maximum under the ECO variable.
Cite only one main fact, even if several signals exist.
Assess the market impact on a continuous scale:

Market impact | MACROECO BONUS score
Very bearish (major crisis, expected collapse) | -0.10
Strongly bearish (confirmed bad news) | -0.08
Moderately bearish (clear negative trend) | -0.06
Slightly bearish (minor negative signals) | -0.04
Weakly bearish (negative nuances) | -0.02
Neutral (no significant impact) | 0.00
Weakly bullish (positive nuances) | +0.02
Slightly bullish (minor positive signals) | +0.04
Moderately bullish (clear positive trend) | +0.06
Strongly bullish (confirmed good news) | +0.08
Very bullish (supply crisis, expected spike) | +0.10

📋 PRECISE ASSESSMENT CRITERIA
BULLISH factors (+0.02 to +0.10):

Rainfall deficit in producing regions
Conflict / political instability in Côte d'Ivoire / Ghana
Cocoa-tree disease (black pod, swollen shoot)
Rising input costs (fertiliser, fuel)
EUR/USD depreciation (makes cocoa dearer for Europeans)
Low stocks reported by ICCO
Rising chocolate demand (holidays, new markets)

BEARISH factors (-0.02 to -0.10):

Favourable rains, optimal weather conditions
Political stability, government agreements
New plantings, expanded acreage
Lower production costs, farm subsidies
EUR/USD appreciation (cocoa cheaper for Europeans)
High stocks, production surplus
Slowing consumption, economic recession


⚠️ STRICT RULES

Never invent a trend if no concrete news is given.
Do not say "not enough information", you must conclude clearly.
Be categorical or factual, even when there is no significant news.
Use the FULL -0.10 to +0.10 range according to the real intensity of the impact.


📤 STRICT OUTPUT FORM (do not change at all)

You MUST reply ONLY with a valid JSON object, no surrounding text:
{{"date": "DD/MM/YYYY", "macroeco_bonus": 0.00, "eco": "synthetic sentence of 30 words maximum"}}

Examples:
{{"date": "19/12/2024", "macroeco_bonus": -0.06, "eco": "Heavy rains in Côte d'Ivoire support pod development, 2025 output seen up 8%."}}
{{"date": "19/12/2024", "macroeco_bonus": 0.04, "eco": "Mild USD/EUR tension unfavourable to European importers, chocolate demand steady despite inflation."}}
{{"date": "19/12/2024", "macroeco_bonus": 0.00, "eco": "No significant macro news, markets awaiting quarterly production data."}}
"""

# Per-language Call #1 template + empty-context placeholders.
_CALL_1_PROMPT: dict[str, str] = {"fr": CALL_1_PROMPT, "en": CALL_1_PROMPT_EN}

_CALL_1_PLACEHOLDERS: dict[str, dict[str, str]] = {
    "fr": {
        "macronews": "(aucune actualité disponible)",
        "meteotoday": "(aucune donnée météo du jour)",
        "meteonews": "(aucun historique météo disponible)",
    },
    "en": {
        "macronews": "(no news available)",
        "meteotoday": "(no weather data for today)",
        "meteonews": "(no weather history available)",
    },
}


# ---------------------------------------------------------------------------
# Call #1 — prompt builder (macro/weather → eco). Call #2 now emits a
# voice-only headline via voice_prompts.py, and the engine renders the
# numbered conclusion deterministically from the FactsPayload. The old
# CALL_2_PROMPT / CALL_2_PROMPT_ENSEMBLE blobs + their builders were removed
# after the US-1c facts/voice refactor (dead since).
# ---------------------------------------------------------------------------
def build_call1_prompt(
    macronews: str, meteotoday: str, meteonews: str, language: str = "fr"
) -> str:
    """Build the Call #1 prompt in ``language`` (fr | en), context injected.

    The ``eco`` field is one of the 3 native-language prose fields (D3): the EN
    prompt asks for a fresh English summary, never a translation of the FR one.
    Unknown languages fall back to French.
    """
    template = _CALL_1_PROMPT.get(language, _CALL_1_PROMPT["fr"])
    placeholders = _CALL_1_PLACEHOLDERS.get(language, _CALL_1_PLACEHOLDERS["fr"])
    return template.format(
        MACRONEWS=macronews or placeholders["macronews"],
        METEOTODAY=meteotoday or placeholders["meteotoday"],
        METEONEWS=meteonews or placeholders["meteonews"],
    )


# ---------------------------------------------------------------------------
# Shared ensemble diagnostics — the confidence rubric + allowed vocabulary
# injected into the Call #2 voice prompt. Consumed by voice_prompts.py (FR
# directly, EN via its own mirror _ENSEMBLE_DIAGNOSTICS_BLOCK_EN). This is
# the single FR canon; keep it and the EN mirror in sync.
# ---------------------------------------------------------------------------
ENSEMBLE_DIAGNOSTICS_BLOCK = """\
CONTEXTE DÉCISIONNEL — LECTURE COMPASS DU JOUR

La décision du jour ({DECISION_WRAPPED}) est le verdict Compass — tu DOIS la
justifier en t'appuyant sur les diagnostics ci-dessous, PAS sur un score
composite technique.

Diagnostics du signal :
\t•\tDécision : {DECISION_WRAPPED}
\t•\tConviction Compass intrinsèque : {CONVICTION_QUALITATIVE}
\t•\tDirection macro (signal filtré) : {MACRO_DIRECTION} (surprise={MACRO_SURPRISE}, half-life={MACRO_HALF_LIFE_DAYS}j)

═══ ÉVALUATION DE LA CONFIANCE (champs "confiance" + "confiance_rationale") ═══

La confiance reflète à quel point la décision Compass est appuyée par les
facteurs externes du jour. RÈGLE FONDAMENTALE : la décision Compass est le
verdict — les facteurs externes ne peuvent QUE renforcer la confiance ou la
nuancer légèrement. Ils ne peuvent JAMAIS la contredire.

ÉTAPE 1 — Base de la confiance, dérivée de la conviction Compass intrinsèque :
\t•\tConviction "forte"   → base 4
\t•\tConviction "modérée" → base 3
\t•\tConviction "faible"  → base 2

ÉTAPE 2 — Modulation par les 5 piliers externes (technique, macro, sentiment
de marché, fondamentaux, climat). Pour chacun, juge s'il SOUTIENT, est NEUTRE,
ou apporte une NUANCE légère par rapport à la décision Compass :
\t•\tSOUTIEN : le pilier va clairement dans le sens de la décision (ex : HEDGE
\t  + RSI baissier + MACD baissier + stocks en hausse → tech soutient)
\t•\tNEUTRE : le pilier n'apporte pas de signal clair ou est mixte
\t•\tNUANCE : le pilier introduit une légère friction (ex : sentiment légèrement
\t  haussier sur une décision HEDGE) — JAMAIS de contradiction franche

ÉTAPE 3 — Ajustement final (max ±1 par rapport à la base) :
\t•\tMajorité de piliers SOUTIEN → +1 (max 5)
\t•\tMajorité NEUTRE ou mixte    → 0 (garde la base)
\t•\t1 ou 2 piliers NUANCE       → -1 (min 1)

RÈGLE STRICTE : pas de -2 ou plus. Les facteurs externes ne contredisent jamais
la décision Compass — ils ne font que nuancer la confiance autour de la base.

Vocabulaire à utiliser dans la conclusion :
\t•\t"Conviction forte / modérée / faible" pour qualifier l'engagement Compass
\t•\t"Convergence des lectures du jour" / "lectures qui s'alignent"
\t•\t"Direction haussière / baissière / neutre" pour décrire le biais du jour

VOCABULAIRE STRICTEMENT INTERDIT (ne JAMAIS écrire ces mots, ils déclenchent
une coupure du pipeline en aval) :
\t•\tToute mention du nombre de spécialistes du panel — pas de "X spécialistes sur 14", pas de "X/14", pas de "panel de 14", pas de "sur 14 confirment", pas de "des 14"
\t•\tToute valeur technique chiffrée du diagnostic interne : pas de "net_score", pas de "running_acc", pas de "anomaly_z", pas de "score composite"
\t•\tToute mention d'architecture interne : pas de "soft-gate", pas de "wrapper", pas de "filet de sécurité", pas de "détecteur", pas de "cluster Winter", pas de "cluster Spring", pas de "orchestrateur bayésien", pas de "ensemble v1", pas de "machine learning", pas de "modèle propriétaire"
\t•\tPas de noms techniques de spécialistes (W1, W2, S1, exp_optim_*, xpol_*)

Tu peux nommer un OU deux libellés business de spécialistes (Lecteur de
tendance, Sentinelle baissière FX, Stratège macro global…) si pertinent, mais
seulement pour décrire ce qu'ils regardent — jamais pour révéler la taille
du panel.

"""


def _format_optional(value: object, digits: int | None = None) -> str:
    """Format an optional float/int for prompt injection. None → 'n/a'."""
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "oui" if value else "non"
    if isinstance(value, float) and digits is not None:
        return f"{value:.{digits}f}"
    return str(value)


def _qualitative_conviction(
    net_score: object, n_committed: object, *, panel_size: int = 14
) -> str:
    """Map (net_score, n_committed) → qualitative conviction label.

    The "adhesion" metric combines unanimity (|net_score|) and engagement
    (n_committed / panel_size) into one composite that captures both axes :

        adhesion = |net_score| × sqrt(n_committed / panel_size)

    Thresholds (set against the 30-day prod distribution) :
        adhesion ≥ 0.70  → "forte"
        0.40 ≤ adhesion < 0.70 → "modérée"
        adhesion < 0.40 → "faible"

    Returns ``"faible"`` when either input is missing/invalid — the safe
    default lets the LLM start from base 2 rather than crash.
    """
    import math

    try:
        ns = float(net_score) if net_score is not None else 0.0
        nc = int(n_committed) if n_committed is not None else 0
    except (TypeError, ValueError):
        return "faible"
    if panel_size <= 0:
        return "faible"
    adhesion = abs(ns) * math.sqrt(max(nc, 0) / panel_size)
    if adhesion >= 0.70:
        return "forte"
    if adhesion >= 0.40:
        return "modérée"
    return "faible"
