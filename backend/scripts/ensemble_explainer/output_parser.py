"""Validate LLM output JSON against the strict schema.

The Explainer is constrained: it MUST mirror the ensemble decision and produce
``{eco, confidence, direction, conclusion}`` in the expected shape. Any
deviation is fail-loud — we don't try to repair LLM output silently.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from scripts.ensemble_explainer.config import (
    ALLOWED_DECISIONS,
    ALLOWED_DIRECTIONS,
    CONCLUSION_MAX_CHARS,
    CONFIDENCE_MAX,
    CONFIDENCE_MIN,
    ECO_MAX_CHARS,
)


class ExplainerOutputError(ValueError):
    """Raised when LLM output is structurally invalid OR contradicts decision."""


@dataclass(frozen=True)
class ExplainerOutput:
    eco: str
    confidence: int
    direction: str
    conclusion: str


# Words signalling a position OPPOSITE the decision. Used by the cross-consistency
# check to fail-loud if the LLM commentary contradicts the (immutable) decision.
_OPPOSITE_WORDS = {
    "OPEN": ("vendre", "vente", "short", "couvrir", "hedge", "fermer la position"),
    "HEDGE": ("acheter", "long", "open", "rouvrir"),
    "MONITOR": (),  # MONITOR is neutral — both buy/sell language is allowed
}


def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    )


def parse_explainer_output(parsed: dict, expected_decision: str) -> ExplainerOutput:
    """Validate the parsed LLM JSON and return an ExplainerOutput dataclass.

    Args:
        parsed: dict parsed from LLM raw JSON.
        expected_decision: the immutable ensemble decision (decision_wrapped)
            that the LLM commentary must NOT contradict.

    Raises:
        ExplainerOutputError: on any schema violation or commentary contradiction.
    """
    if expected_decision not in ALLOWED_DECISIONS:
        raise ExplainerOutputError(
            f"Bad expected_decision={expected_decision!r}; must be one of {ALLOWED_DECISIONS}."
        )

    # Required keys
    required = {"eco", "confidence", "direction", "conclusion"}
    missing = required - set(parsed.keys())
    if missing:
        raise ExplainerOutputError(f"Missing keys in LLM output: {sorted(missing)}.")

    # eco
    eco = parsed["eco"]
    if not isinstance(eco, str):
        raise ExplainerOutputError("`eco` must be a string.")
    eco = eco.strip()
    if not eco:
        raise ExplainerOutputError("`eco` cannot be empty.")
    if len(eco) > ECO_MAX_CHARS:
        eco = eco[:ECO_MAX_CHARS].rstrip()

    # confidence
    raw_conf = parsed["confidence"]
    try:
        confidence = int(raw_conf)
    except (TypeError, ValueError) as exc:
        raise ExplainerOutputError(
            f"`confidence` must be int, got {raw_conf!r}."
        ) from exc
    if not (CONFIDENCE_MIN <= confidence <= CONFIDENCE_MAX):
        raise ExplainerOutputError(
            f"`confidence`={confidence} out of [{CONFIDENCE_MIN}, {CONFIDENCE_MAX}]."
        )

    # direction
    direction_raw = parsed["direction"]
    if not isinstance(direction_raw, str):
        raise ExplainerOutputError("`direction` must be a string.")
    direction = _strip_accents(direction_raw.strip().upper())
    if direction not in ALLOWED_DIRECTIONS:
        raise ExplainerOutputError(
            f"`direction`={direction_raw!r} not in {ALLOWED_DIRECTIONS}."
        )

    # conclusion
    conclusion = parsed["conclusion"]
    if not isinstance(conclusion, str):
        raise ExplainerOutputError("`conclusion` must be a string.")
    conclusion = conclusion.strip()
    if not conclusion:
        raise ExplainerOutputError("`conclusion` cannot be empty.")
    if len(conclusion) > CONCLUSION_MAX_CHARS:
        conclusion = conclusion[:CONCLUSION_MAX_CHARS].rstrip()

    # CONSISTENCY CHECK: conclusion must not contradict ensemble decision.
    forbidden = _OPPOSITE_WORDS.get(expected_decision, ())
    lower_conclusion = conclusion.lower()
    for word in forbidden:
        if re.search(rf"\b{re.escape(word)}\b", lower_conclusion):
            raise ExplainerOutputError(
                f"`conclusion` contains '{word}' which contradicts ensemble decision "
                f"{expected_decision}. The LLM may not invert the decision."
            )

    return ExplainerOutput(
        eco=eco,
        confidence=confidence,
        direction=direction,
        conclusion=conclusion,
    )
