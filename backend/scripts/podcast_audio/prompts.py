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

COMMENT DIRE LES CHIFFRES :
- Les stocks se disent en tonnes ENTIÈRES : « 236 110 tonnes », jamais
  « 236 110 virgule zéro zéro ». La décimale n'apporte rien à cette échelle.
- Les niveaux de prix GARDENT leurs décimales : « le support à 4 160,67 ».
  C'est le niveau exact qui compte pour quelqu'un qui passe un ordre.
- N'invente AUCUN chiffre. Si une valeur n'est pas dans la matière ci-dessous,
  ne la mentionne pas — pas d'approximation de mémoire.

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
Ton de PRÉSENTATEURS de podcast : vivants, complices, jamais récitants.
- Ana lance, questionne, relance. Marc porte l'analyse.
- Alterne des tours LONGS (une analyse développée) et des tours TRÈS COURTS.
- Les tours courts sont de VRAIES réactions parlées, pas des accusés de
  réception : "ah oui, quand même", "c'est massif ouais", "attends, 40 000
  tonnes ?", "ça change tout". Après une réaction, l'autre ENCHAÎNE sur son idée
  au lieu de repartir de zéro — comme quand on se coupe gentiment la parole.
- Chaque tour court doit APPORTER quelque chose : une surprise, une objection,
  une conséquence, une question. Un tour qui se contente d'approuver n'existe
  pas dans cet épisode — s'il n'ajoute rien, supprime-le et enchaîne.
  Exemples de tours courts valides : "ça, c'est nouveau", "donc l'offre ne suit
  pas", "et côté acheteur ?", "attends, ça remonte à quand ?".
- Aucune formule d'approbation ne se répète : chaque relance a ses propres mots.
  (Ne cite AUCUN chiffre dans une réaction courte : les chiffres se disent dans
  les tours d'analyse, à partir de la matière fournie.)
- L'un finit parfois la phrase de l'autre.
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

LONGUEUR — c'est la contrainte la plus souvent ratée, relis-la avant de rendre :
- 32 à 40 tours de parole au total.
- Les tours d'analyse de Marc font 2 à 4 phrases pleines.
- Les points 4, 5 et 6 (éditorial, éco-presse, météo) sont les plus développés :
  5 à 6 tours chacun, avec des relances courtes d'Ana entre les blocs.
- Total visé : 4200 caractères de texte parlé. Plancher 3700, PLAFOND 6200.
  Les exigences de naturel ci-dessus ne sont pas une invitation à rallonger :
  un tour court qui apporte quelque chose reste court.
Une idée par tour, pas de reformulation de ce qui vient d'être dit, pas de
conclusion qui répète l'épisode.
"""

_PROMPT_EN = """\
You are writing the daily Compass CC podcast script on London COCOA, horizon the \
next session. Two financial journalists on air.

{shape}

HOW TO SAY FIGURES:
- Stocks are spoken in WHOLE tonnes: "236,110 tonnes", never "236,110 point
  zero zero". The decimal carries nothing at that scale.
- Price levels KEEP their decimals: "support at 4,160.67". The exact level is
  what matters to someone placing an order.
- Invent NO figure. If a value is not in the material below, do not mention it —
  no approximating from memory.

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
Podcast PRESENTER tone: alive, easy with each other, never reciting.
- Ana opens, questions, pushes back. Marc carries the analysis.
- Alternate LONG turns (a developed point) with VERY SHORT ones.
- Short turns are REAL spoken reactions, not acknowledgements: "oh wow, really",
  "that's huge", "hang on, forty thousand tonnes?", "that changes things". After
  a reaction the other CARRIES ON with the same thought rather than restarting —
  the way people cut in on each other without breaking the flow.
- Every short turn must ADD something: a surprise, an objection, a consequence,
  a question. A turn that merely agrees does not exist in this episode — if it
  adds nothing, drop it and carry on.
  Valid short turns look like: "that's new", "so supply isn't keeping up",
  "and for the buyer?", "hang on, since when?".
- No approving phrase repeats: every pickup has its own words.
  (Quote NO figure in a short reaction: figures belong in the analytical turns,
  taken from the material provided.)
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

LENGTH — the constraint most often missed, re-read it before you answer:
- 30 to 38 turns in total.
- Marc's analytical turns run 2 to 4 full sentences.
- Points 4, 5 and 6 (editorial, macro & press, weather) are the most developed:
  5 to 6 turns each, with short pushbacks from Ana between blocks.
- Target 3500 characters of spoken text. Floor 3000, CEILING 4900.
  The naturalness rules above are not licence to run long: a short turn
  that adds something stays short.
English is more compact than French: the same episode needs fewer characters,
so do not pad to reach a length. One idea per turn, no restating, no closing
summary that replays the episode.
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
