"""Output validation for press review LLM responses."""

import logging
from typing import Any

from scripts.press_review_agent.config import THEMES, VALIDATION, Provider

logger = logging.getLogger(__name__)


def validate_output(result: dict[str, str], provider: Provider) -> list[str]:
    """Validate LLM output fields.

    Returns list of error strings (empty = valid).
    """
    errors: list[str] = []
    tag = provider.value

    for field in ("resume", "mots_cle", "impact_synthetiques"):
        val = result.get(field)
        if not val or not isinstance(val, str):
            errors.append(f"[{tag}] '{field}' missing or not a string")

    resume = result.get("resume", "")
    mots_cle = result.get("mots_cle", "")
    impact = result.get("impact_synthetiques", "")

    if isinstance(resume, str):
        if len(resume) < VALIDATION["resume_min_chars"]:
            errors.append(
                f"[{tag}] resume too short ({len(resume)} chars, "
                f"min {VALIDATION['resume_min_chars']})"
            )
        if len(resume) > VALIDATION["resume_max_chars"]:
            errors.append(
                f"[{tag}] resume too long ({len(resume)} chars, "
                f"max {VALIDATION['resume_max_chars']})"
            )

    if isinstance(mots_cle, str):
        if len(mots_cle) < VALIDATION["mots_cle_min_chars"]:
            errors.append(f"[{tag}] mots_cle too short ({len(mots_cle)} chars)")
        if len(mots_cle) > VALIDATION["mots_cle_max_chars"]:
            errors.append(f"[{tag}] mots_cle too long ({len(mots_cle)} chars)")

    if isinstance(impact, str):
        if len(impact) < VALIDATION["impact_min_chars"]:
            errors.append(
                f"[{tag}] impact_synthetiques too short ({len(impact)} chars)"
            )
        if len(impact) > VALIDATION["impact_max_chars"]:
            errors.append(f"[{tag}] impact_synthetiques too long ({len(impact)} chars)")

    # theme_sentiments is optional — validate only if present
    theme_sentiments = result.get("theme_sentiments")
    if theme_sentiments is not None:
        ts_errors = _validate_theme_sentiments(theme_sentiments, tag)
        errors.extend(ts_errors)

    if errors:
        for e in errors:
            logger.warning(f"Validation: {e}")
    else:
        ts_count = len(theme_sentiments) if isinstance(theme_sentiments, dict) else 0
        logger.info(
            f"[{tag}] Validation passed "
            f"(resume={len(resume)}, mots_cle={len(mots_cle)}, "
            f"impact={len(impact)}, theme_sentiments={ts_count} themes)"
        )

    return errors


def _validate_theme_sentiments(ts: Any, tag: str) -> list[str]:
    """Validate theme_sentiments field. Returns error strings."""
    errors: list[str] = []

    if not isinstance(ts, dict):
        errors.append(
            f"[{tag}] theme_sentiments must be a dict, got {type(ts).__name__}"
        )
        return errors

    for theme, data in ts.items():
        if theme not in THEMES:
            errors.append(f"[{tag}] theme_sentiments unknown theme '{theme}'")
            continue

        if not isinstance(data, dict):
            errors.append(f"[{tag}] theme_sentiments[{theme}] must be a dict")
            continue

        score = data.get("score")
        if score is None or not isinstance(score, (int, float)):
            errors.append(
                f"[{tag}] theme_sentiments[{theme}].score missing or not numeric"
            )
        elif not (-1.0 <= float(score) <= 1.0):
            errors.append(
                f"[{tag}] theme_sentiments[{theme}].score={score} out of [-1.0, 1.0]"
            )

        confidence = data.get("confidence")
        if confidence is None or not isinstance(confidence, (int, float)):
            errors.append(
                f"[{tag}] theme_sentiments[{theme}].confidence missing or not numeric"
            )
        elif not (0.0 <= float(confidence) <= 1.0):
            errors.append(
                f"[{tag}] theme_sentiments[{theme}].confidence={confidence} out of [0.0, 1.0]"
            )

        rationale = data.get("rationale")
        if not rationale or not isinstance(rationale, str):
            errors.append(
                f"[{tag}] theme_sentiments[{theme}].rationale missing or empty"
            )

    return errors
