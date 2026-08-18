"""Project the regime+judge decision into pl_indicator_daily ("adapter row").

The dashboard reads decisions from ``pl_indicator_daily``. Rather than refactor
every endpoint to read ``pl_regime_shadow`` + ``pl_judge_shadow`` directly
(strategy B in the bascule plan — cleaner, 3× the work, and a much riskier
switch), regime writes a projection of its decision into the table the
dashboard already knows.

Regime stays conceptually pure: its own table remains the source of truth, this
is a derived view of it.

**Writing this row exposes nothing.** What the dashboard serves is decided by
``pl_algorithm_version.serving_rank``, and regime has none. So the adapter row
can be written and compared against the incumbent for weeks before anyone sees
it — that is the shadow-parity mode the bascule needs.

Language handling — deliberately asymmetric:

  * BOTH rows (fr + en) carry the structured fields (decision, confidence,
    direction). The fr row is not optional: the YTD series pins
    ``language='fr'`` and would silently score nothing without it.
  * ONLY the en row carries free text. The judge reasons and writes in English;
    copying that prose under ``language='fr'`` would break the invariant the
    whole codebase holds — never serve one language's narrative under another
    language's label. The French narrative is produced downstream by the brief
    generator, which translates as it composes.

Until then the French dashboard falls back to the legacy narrative through the
existing 4-tier cascade in ``get_latest_recommendations`` — a known and
accepted mismatch, not an accident.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date as date_cls

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

DEFAULT_LANGUAGE = "fr"
NARRATIVE_LANGUAGE = "en"

# Every value column not listed here is left NULL on purpose. Regime computes
# no z-scores and no macro bonus; NULL means "not computed" and stays
# queryable, whereas 0.0 is a valid score and would silently corrupt anything
# averaging these columns (.claude/rules/pipeline-continuity.md).
_UPSERT = """
INSERT INTO pl_indicator_daily (
    id, date, contract_id, algorithm_version_id, language,
    decision, confidence, direction, eco, conclusion, confidence_rationale
) VALUES (
    gen_random_uuid(), :date, :contract_id, :algorithm_version_id, :language,
    :decision, :confidence, :direction, :eco, :conclusion, :confidence_rationale
)
ON CONFLICT ON CONSTRAINT uq_indicator_daily DO UPDATE SET
    decision             = EXCLUDED.decision,
    confidence           = EXCLUDED.confidence,
    direction            = EXCLUDED.direction,
    eco                  = EXCLUDED.eco,
    conclusion           = EXCLUDED.conclusion,
    confidence_rationale = EXCLUDED.confidence_rationale
"""

_READ_REGIME = """
SELECT contract_id, decision, regime, specialist, prob_up
FROM pl_regime_shadow
WHERE date = :date AND algorithm_version_id = :aid
"""

_READ_JUDGE = """
SELECT final_decision, judge_direction, judge_stance, judge_confidence,
       is_anomaly, changed, rationale, drift_summary, disconfirming_case,
       key_risk, evidence
FROM pl_judge_shadow
WHERE date = :date
ORDER BY created_at DESC
LIMIT 1
"""


class AdapterSourceMissingError(RuntimeError):
    """No regime row for the date — there is nothing to project."""


def _compose_conclusion(regime_row, judge_row) -> str | None:
    """Human-readable narrative, English, assembled from the two layers.

    Mirrors the structure the legacy narrative uses so the frontend parser
    (``parse_recommendations_text``: one item per line) keeps working.
    """
    if judge_row is None:
        return None

    lines: list[str] = []
    if judge_row.rationale:
        lines.append(judge_row.rationale.strip())

    evidence = judge_row.evidence or []
    for quote in evidence[:2]:
        if isinstance(quote, str) and quote.strip():
            lines.append(f"> {quote.strip()}")

    lines.append(
        f"Technical base: {regime_row.decision} "
        f"(regime {regime_row.regime}, specialist {regime_row.specialist}, "
        f"P(up)={float(regime_row.prob_up):.2f})."
    )
    if judge_row.changed:
        lines.append(f"The macro overlay moved the call to {judge_row.final_decision}.")
    return "\n".join(line for line in lines if line) or None


def _compose_eco(judge_row) -> str | None:
    """Macro paragraph — the drift summary plus the risk the judge named."""
    if judge_row is None:
        return None
    parts = [
        part.strip()
        for part in (judge_row.drift_summary, judge_row.key_risk)
        if part and part.strip()
    ]
    return " ".join(parts) or None


def write_adapter_row(
    session: Session,
    *,
    session_date: date_cls,
    algorithm_version_id: uuid.UUID | str,
) -> int:
    """Project (regime, judge) for ``session_date`` into pl_indicator_daily.

    Reads the two shadow rows back from the DB rather than taking the in-memory
    objects, so this is replayable on its own for a backfill and testable
    without an LLM. Returns the number of rows written (2 = fr + en).

    Raises ``AdapterSourceMissingError`` when no regime row exists: a missing
    projection must be loud, not an empty dashboard section discovered the next
    morning.
    """
    aid = str(algorithm_version_id)
    regime_row = session.execute(
        text(_READ_REGIME), {"date": session_date, "aid": aid}
    ).fetchone()
    if regime_row is None:
        raise AdapterSourceMissingError(
            f"No pl_regime_shadow row at {session_date} for algorithm {aid} — "
            "nothing to project into pl_indicator_daily"
        )

    judge_row = session.execute(text(_READ_JUDGE), {"date": session_date}).fetchone()
    if judge_row is None:
        logger.warning(
            "No judge row at %s — projecting the raw regime call without the "
            "macro overlay",
            session_date,
        )

    # The judge's fused call wins when present; regime alone otherwise.
    decision = judge_row.final_decision if judge_row else regime_row.decision
    confidence = judge_row.judge_confidence if judge_row else None
    direction = judge_row.judge_direction if judge_row else None

    conclusion = _compose_conclusion(regime_row, judge_row)
    eco = _compose_eco(judge_row)
    confidence_rationale = judge_row.disconfirming_case if judge_row else None

    written = 0
    for language in (DEFAULT_LANGUAGE, NARRATIVE_LANGUAGE):
        carries_text = language == NARRATIVE_LANGUAGE
        session.execute(
            text(_UPSERT),
            {
                "date": session_date,
                "contract_id": str(regime_row.contract_id),
                "algorithm_version_id": aid,
                "language": language,
                "decision": decision,
                "confidence": confidence,
                "direction": direction,
                "eco": eco if carries_text else None,
                "conclusion": conclusion if carries_text else None,
                "confidence_rationale": (
                    confidence_rationale if carries_text else None
                ),
            },
        )
        written += 1

    logger.info(
        "adapter row %s: decision=%s confidence=%s (%d languages)",
        session_date,
        decision,
        confidence,
        written,
    )
    return written
