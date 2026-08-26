"""The episode prompt, one per language, composed natively.

Descended from the NotebookLM "Customise" panel
(docs/operations/notebooklm-podcast-prompt-regime.md), with one structural
change: that prompt asked a black box to *write and speak*. This one only asks
for a script, and everything it used to plead for — no invented figures, no
machinery vocabulary, the opening and closing formulas — is now asserted in
``script_writer.validate`` instead of hoped for.

It is redacted of the decision engine's mechanics for the same reason the brief
is: the audio is the most widely distributed Compass artefact and the easiest to
reverse-engineer from.
"""

from __future__ import annotations

from scripts.podcast_audio.speech_text import normalize_for_speech
from scripts.regime_brief.db_reader import BriefData
from scripts.regime_brief.narrator import Narrative

_SHAPE = """\
Réponds UNIQUEMENT avec un objet JSON de la forme :
{{"turns": [{{"speaker": "Ana", "text": "..."}}, {{"speaker": "Marc", "text": "..."}}]}}
Deux interlocuteurs seulement : "Ana" (femme) et "Marc" (homme)."""

_SHAPE_EN = """\
Reply ONLY with a JSON object shaped like:
{{"turns": [{{"speaker": "Ana", "text": "..."}}, {{"speaker": "Marc", "text": "..."}}]}}
Two speakers only: "Ana" (female) and "Marc" (male)."""

_PROMPT_FR = """\
Tu écris le script du podcast quotidien Compass CC sur le CACAO Londres, \
horizon la prochaine séance. Deux journalistes financiers à l'antenne.

{shape}

CE QUI EST ARRÊTÉ — tu l'expliques, tu ne le discutes pas :
- Signal publié : {decision}
- Conviction : {confidence}/5
- Direction implicite : {direction}

MATIÈRE (n'utilise QUE ça — n'invente AUCUN chiffre) :
[Lecture du jour] {conclusion}
[Éco & presse] {eco}
[Ce qui invaliderait] {confidence_rationale}
[Photo technique] {technicals}
[À surveiller] {watch}
[Météo] {weather}

C'EST UNE CONVERSATION, PAS UNE LECTURE À TOUR DE RÔLE.
- Ana lance, questionne, relance. Marc porte l'analyse.
- Alterne des tours LONGS (une analyse développée) et des tours TRÈS COURTS \
(une réaction de 3 à 8 mots : "Exactement.", "...mais le macro ne suit pas.").
- L'un finit parfois la phrase de l'autre. Ils rebondissent.
- Un script où chaque tour fait la même longueur est REFUSÉ.

DÉROULÉ :
1. Ana ouvre EXACTEMENT par "Bonjour les COMPASTEURS !" puis annonce le sujet.
2. La performance YTD si elle est fournie, sinon passe.
3. La décision du jour : {decision}, la conviction, et en une phrase ce qui \
pourrait faire mentir cette lecture.
4. Le cœur éditorial : le régime de marché en langage courant, et comment la \
lecture macro s'est positionnée face à la lecture technique.
5. Éco et revue de presse.
6. Météo Côte d'Ivoire et Ghana.
7. Les niveaux techniques qui comptent, en prose.
8. Ce qu'un acheteur physique fait concrètement demain.
9. Marc ferme EXACTEMENT par "À demain les COMPASTEURS !"

INTERDIT DE PRONONCER : intelligence artificielle, IA, algorithme, modèle, \
spécialiste, probabilité, score, z-score, régime détecté. Ne compte jamais des \
voix ni des indicateurs.

LONGUEUR : entre 3600 et 5000 caractères de texte parlé au total, en visant 4300.
"""

_PROMPT_EN = """\
You are writing the daily Compass CC podcast script on London COCOA, horizon the \
next session. Two financial journalists on air.

{shape}

SETTLED — you explain it, you do not debate it:
- Published signal: {decision}
- Conviction: {confidence}/5
- Implied direction: {direction}

MATERIAL (use ONLY this — invent NO figure):
[Today's read] {conclusion}
[Macro & press] {eco}
[What would invalidate it] {confidence_rationale}
[Technical snapshot] {technicals}
[Watch levels] {watch}
[Weather] {weather}

THIS IS A CONVERSATION, NOT TWO PEOPLE READING IN TURN.
- Ana opens, questions, pushes back. Marc carries the analysis.
- Alternate LONG turns (a developed point) with VERY SHORT ones (a 3-to-8 word \
reaction: "Exactly.", "...but the macro doesn't follow.").
- One sometimes finishes the other's sentence.
- A script where every turn is the same length is REJECTED.

RUNNING ORDER:
1. Ana opens EXACTLY with "Hello COMPASTEURS!" then names the subject.
2. YTD performance if provided, otherwise skip it.
3. Today's call: {decision}, the conviction, and in one sentence what could \
prove this read wrong.
4. The editorial core: the market regime in plain words, and how the macro read \
sat against the technical read.
5. Macro and press review.
6. Weather in Côte d'Ivoire and Ghana.
7. The levels that matter, in prose.
8. What a physical buyer actually does tomorrow.
9. Marc closes EXACTLY with "See you tomorrow COMPASTEURS!"

NEVER SAY: artificial intelligence, AI, algorithm, model, specialist, \
probability, score, z-score, detected regime. Never count votes or indicators.

LENGTH: between 3600 and 5000 characters of spoken text in total, aiming for 4300.
"""


def build_prompt(data: BriefData, narrative: Narrative) -> str:
    """The full prompt for ``data.language``, with the prose already normalised.

    ``narrative`` is what ``regime_brief.narrator`` already wrote onto the served
    row — the podcast quotes the dashboard rather than re-deriving it, so the two
    cannot disagree. ``data`` supplies only the deterministic figures.
    """
    english = data.language == "en"
    template = _PROMPT_EN if english else _PROMPT_FR
    clean = normalize_for_speech
    return template.format(
        shape=_SHAPE_EN if english else _SHAPE,
        decision=data.judge.final_decision,
        confidence=data.judge.confidence,
        direction=data.judge.direction,
        conclusion=clean(narrative.conclusion),
        eco=clean(narrative.eco),
        confidence_rationale=clean(narrative.confidence_rationale),
        technicals=clean(data.technicals_snapshot or ""),
        watch=clean(" ".join(data.watch_lines)) or "(aucun)",
        weather=clean(data.weather_body or ""),
    )
