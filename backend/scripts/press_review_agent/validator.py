"""Output validation for press review LLM responses."""

import logging

from scripts.press_review_agent.config import VALIDATION, Provider

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

    if errors:
        for e in errors:
            logger.warning(f"Validation: {e}")
    else:
        logger.info(
            f"[{tag}] Validation passed "
            f"(resume={len(resume)}, mots_cle={len(mots_cle)}, "
            f"impact={len(impact)})"
        )

    return errors
