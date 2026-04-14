"""Output validation for meteo agent LLM responses."""

import logging

from scripts.meteo_agent.config import VALIDATION

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = ("texte", "resume", "mots_cle", "impact_synthetiques")


def validate_output(result: dict[str, str]) -> list[str]:
    """Validate LLM output fields.

    Returns list of error strings (empty = valid).
    """
    errors: list[str] = []

    for field_name in REQUIRED_FIELDS:
        val = result.get(field_name)
        if not val or not isinstance(val, str):
            errors.append(f"'{field_name}' missing or not a string")

    texte = result.get("texte", "")
    resume = result.get("resume", "")
    mots_cle = result.get("mots_cle", "")
    impact = result.get("impact_synthetiques", "")

    if isinstance(texte, str):
        if len(texte) < VALIDATION["texte_min_chars"]:
            errors.append(
                f"texte too short ({len(texte)} chars, "
                f"min {VALIDATION['texte_min_chars']})"
            )
        if len(texte) > VALIDATION["texte_max_chars"]:
            errors.append(
                f"texte too long ({len(texte)} chars, "
                f"max {VALIDATION['texte_max_chars']})"
            )

    if isinstance(resume, str):
        if len(resume) < VALIDATION["resume_min_chars"]:
            errors.append(f"resume too short ({len(resume)} chars)")
        if len(resume) > VALIDATION["resume_max_chars"]:
            errors.append(f"resume too long ({len(resume)} chars)")

    if isinstance(mots_cle, str):
        if len(mots_cle) < VALIDATION["mots_cle_min_chars"]:
            errors.append(f"mots_cle too short ({len(mots_cle)} chars)")
        if len(mots_cle) > VALIDATION["mots_cle_max_chars"]:
            errors.append(f"mots_cle too long ({len(mots_cle)} chars)")

    if isinstance(impact, str):
        if len(impact) < VALIDATION["impact_min_chars"]:
            errors.append(f"impact_synthetiques too short ({len(impact)} chars)")
        if len(impact) > VALIDATION["impact_max_chars"]:
            errors.append(f"impact_synthetiques too long ({len(impact)} chars)")

    # Diagnostics validation — not in REQUIRED_FIELDS (backward compat),
    # but invalid format is a real error (LLM output is broken).
    diag = result.get("diagnostics")
    if diag is not None:
        if not isinstance(diag, dict):
            errors.append(f"'diagnostics' is {type(diag).__name__}, expected dict")
        else:
            valid_statuses = {"normal", "degraded", "stress"}
            for loc, status in diag.items():
                if status not in valid_statuses:
                    errors.append(
                        f"diagnostics[{loc}] = {status!r} — "
                        f"expected one of {valid_statuses}"
                    )
    else:
        logger.warning("diagnostics field missing from LLM output")

    if errors:
        for e in errors:
            logger.warning("Validation: %s", e)
    else:
        logger.info(
            "Validation passed (texte=%d, resume=%d, mots_cle=%d, impact=%d)",
            len(texte),
            len(resume),
            len(mots_cle),
            len(impact),
        )

    return errors
