"""The single LLM call: judge's raw material in, native prose out.

This is the one place in the regime pipeline where prose is written, and it
replaces what used to be a separate explainer job. One call per language, and
each call *composes natively* — it does not translate. The judge's English
fields are handed over as raw material, exactly as a desk analyst would hand
over notes, and the model writes the section in its own language.

Why not translate once and reuse: a translated paragraph reads like a
translation. The brief is the product's voice.

What crosses into the prompt, and what does not:

    IN   drift_summary, key_risk, disconfirming_case, evidence quotes
         + the regime call and the session's figures, as context
    OUT  rationale — the deterministic policy trace ("ABSTAIN HEDGE->MONITOR:
         judge contradicts at conf=3"). It is audit material for the judge's own
         replay, has no editorial value, and would leak decision mechanics into
         a trader-facing text.

The model never invents a figure: numbers are rendered deterministically by the
template from the same data (the facts/voice split established by US-1). It is
told so explicitly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from scripts.daily_analysis.llm_client import LLMClient, LLMClientError
from scripts.llm_utils import extract_json
from scripts.regime_brief.db_reader import BriefData

logger = logging.getLogger(__name__)

# Prose only — deterministic, no sampling noise between reruns of a session.
_TEMPERATURE = 0.4
_MAX_TOKENS = 1600

_DECISION_LABEL = {
    "fr": {"OPEN": "OPEN (achat)", "HEDGE": "HEDGE (couverture)", "MONITOR": "MONITOR"},
    "en": {"OPEN": "OPEN (buy)", "HEDGE": "HEDGE (cover)", "MONITOR": "MONITOR"},
}


class NarrationError(RuntimeError):
    """The narrator could not produce a usable narrative."""


@dataclass(frozen=True)
class Narrative:
    """What the brief publishes and what the dashboard stores."""

    conclusion: str
    eco: str
    confidence_rationale: str


_PROMPT_FR = """\
Tu es l'analyste du desk Compass CC, spécialiste du cacao. Tu rédiges la note \
quotidienne destinée à des traders et des acheteurs physiques.

DÉCISION DU JOUR — elle est arrêtée, tu ne la discutes pas, tu l'expliques :
- Signal publié : {decision}
- Conviction : {confidence}/5
- Direction implicite : {direction}
- Base technique : {regime_decision} (régime {regime}, spécialiste {specialist})

ÉLÉMENTS DU SPÉCIALISTE MACRO — ils te sont fournis EN ANGLAIS. Ne les traduis \
pas mot à mot : sers-t'en comme d'une note de travail et rédige en français \
naturel, dans ta voix.
- Dérive observée : {drift_summary}
- Risque principal : {key_risk}
- Ce qui invaliderait la lecture : {disconfirming_case}
- Extraits de presse cités : {evidence}

CONTEXTE DU JOUR (pour ton jugement — NE RECOPIE AUCUN CHIFFRE, ils sont \
rendus ailleurs dans la note) :
- Revue de presse : {press_summary}
- Impact presse : {press_impact}
- Météo : {weather_body}

CONSIGNES
- Français natif, ton éditorial sobre et professionnel. Jamais de traduction \
littérale de l'anglais.
- Ne mentionne JAMAIS d'IA, de modèle, d'algorithme, de LLM, de score ni de \
probabilité. Tu es un analyste.
- Aucun chiffre chiffré dans ta prose (pas de prix, volumes, pourcentages) : \
qualifie ("nettement au-dessus", "en repli marqué").
- N'invente rien qui ne soit pas dans les éléments ci-dessus.

Réponds UNIQUEMENT avec ce JSON :
{{
  "conclusion": "3 à 5 lignes. Une ligne par idée. La lecture du jour et ce \
qu'elle implique pour l'acheteur.",
  "eco": "2 à 3 phrases sur le contexte macro et fondamental de la fenêtre.",
  "confidence_rationale": "1 à 2 phrases : ce qui pourrait faire mentir cette \
lecture."
}}"""

_PROMPT_EN = """\
You are the Compass CC desk analyst covering cocoa. You write the daily note \
read by traders and physical buyers.

TODAY'S CALL — it is settled. You explain it, you do not re-litigate it:
- Published signal: {decision}
- Conviction: {confidence}/5
- Implied direction: {direction}
- Technical base: {regime_decision} (regime {regime}, specialist {specialist})

MACRO SPECIALIST INPUT — working notes, not copy. Rewrite in your own voice.
- Observed drift: {drift_summary}
- Key risk: {key_risk}
- What would invalidate the read: {disconfirming_case}
- Press quotes on file: {evidence}

TODAY'S CONTEXT (for your judgement — DO NOT REPRODUCE ANY FIGURE, they are \
rendered elsewhere in the note):
- Press review: {press_summary}
- Press impact: {press_impact}
- Weather: {weather_body}

RULES
- Native English, sober editorial tone.
- NEVER mention AI, a model, an algorithm, an LLM, a score or a probability. \
You are an analyst.
- No numerals in your prose (no prices, volumes, percentages): qualify them \
("well above", "sharply lower").
- Invent nothing beyond the material above.

Reply with THIS JSON ONLY:
{{
  "conclusion": "3 to 5 lines, one idea per line. Today's read and what it \
means for the buyer.",
  "eco": "2 to 3 sentences on the macro and fundamental backdrop of the window.",
  "confidence_rationale": "1 to 2 sentences: what could prove this read wrong."
}}"""

# Any of these in the output means the model broke character and described the
# machinery instead of the market. Fail rather than publish it.
_BANNED_SUBSTRINGS = (
    "llm",
    "gpt",
    "openai",
    "algorithme",
    "algorithm",
    "modèle",
    "model ",
    "intelligence artificielle",
    "artificial intelligence",
    " ia ",
    " ai ",
    "prob(",
    "p(up)",
    "score de",
    "confidence score",
)


def _format_evidence(quotes: tuple[str, ...]) -> str:
    if not quotes:
        return "(aucun)"
    return " | ".join(f'"{quote}"' for quote in quotes[:3])


def _build_prompt(data: BriefData) -> str:
    template = _PROMPT_EN if data.language == "en" else _PROMPT_FR
    labels = _DECISION_LABEL.get(data.language, _DECISION_LABEL["fr"])
    return template.format(
        decision=labels.get(data.judge.final_decision, data.judge.final_decision),
        confidence=data.judge.confidence,
        direction=data.judge.direction,
        regime_decision=data.regime.decision,
        regime=data.regime.regime,
        specialist=data.regime.specialist,
        drift_summary=data.judge.drift_summary or "(none)",
        key_risk=data.judge.key_risk or "(none)",
        disconfirming_case=data.judge.disconfirming_case or "(none)",
        evidence=_format_evidence(data.judge.evidence),
        press_summary=data.press_summary,
        press_impact=data.press_impact or "(none)",
        weather_body=data.weather_body,
    )


def _assert_in_character(narrative: Narrative, language: str) -> None:
    """Refuse to publish a text that talks about the machinery.

    The brief is read aloud by a human-sounding voice; a sentence naming a
    model breaks the product. This is a producer, so it fails rather than
    degrades (.claude/rules/pipeline-error-handling.md).
    """
    blob = " ".join(
        (narrative.conclusion, narrative.eco, narrative.confidence_rationale)
    ).lower()
    hits = [banned for banned in _BANNED_SUBSTRINGS if banned in blob]
    if hits:
        raise NarrationError(
            f"Narrative [{language}] mentions the machinery {hits} — refusing to "
            "publish. Re-run; if it recurs, the prompt needs tightening."
        )


def narrate(data: BriefData, client: LLMClient | None = None) -> Narrative:
    """Compose the narrative natively in ``data.language``."""
    client = client or LLMClient()
    prompt = _build_prompt(data)

    try:
        response = client.call(prompt, temperature=_TEMPERATURE, max_tokens=_MAX_TOKENS)
    except LLMClientError as exc:
        raise NarrationError(f"Narration [{data.language}] failed: {exc}") from exc

    payload = extract_json(response.raw_text)
    missing = [
        field
        for field in ("conclusion", "eco", "confidence_rationale")
        if not str(payload.get(field, "")).strip()
    ]
    if missing:
        raise NarrationError(
            f"Narration [{data.language}] is missing {missing} — refusing to "
            "publish a partial brief"
        )

    narrative = Narrative(
        conclusion=str(payload["conclusion"]).strip(),
        eco=str(payload["eco"]).strip(),
        confidence_rationale=str(payload["confidence_rationale"]).strip(),
    )
    _assert_in_character(narrative, data.language)
    logger.info(
        "narrated [%s]: %d chars (model=%s, %d output tokens)",
        data.language,
        len(narrative.conclusion),
        response.model,
        response.output_tokens,
    )
    return narrative
