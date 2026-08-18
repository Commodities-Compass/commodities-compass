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
can be written and compared against the incumbent for as long as needed before
any flip — that is the shadow-parity mode the bascule needs.

STRUCTURAL ONLY — no prose, in any language.

    decision / confidence / direction   ← written here
    conclusion / eco / confidence_rationale ← written by cc-regime-brief

The narrative is not this module's job. ``cc-regime-brief --language both``
receives the judge's English fields as raw material and *composes natively* in
each language, writing the result back into the row for that language. One job,
two languages, native prose in both — no translation step, no second LLM call.

Two things are deliberately NOT propagated:

  * ``pl_judge_shadow.rationale`` — it is the deterministic trace of
    ``policy.fuse`` ("ABSTAIN HEDGE->MONITOR: judge contradicts at conf=3"),
    not prose. It exists for the judge's own history replay and for audit. It
    never reaches the brief and is never served.
  * anything regime does not compute (z-scores, macro bonus) — those stay NULL,
    never 0.0, which is a valid score (.claude/rules/pipeline-continuity.md).

There is no cross-algorithm fallback anywhere in this path. If the projection
is missing, the job fails loudly: from this algorithm on, the pipeline behaves
as though no other algorithm exists.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date as date_cls

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Both rows are written. The French one is not optional: the YTD series pins
# ``language='fr'`` and would silently score an empty set without it.
ADAPTER_LANGUAGES = ("fr", "en")

# Only the structural columns. Everything else on pl_indicator_daily is either
# owned by cc-regime-brief (the prose) or simply not computed by regime (NULL).
_UPSERT = """
INSERT INTO pl_indicator_daily (
    id, date, contract_id, algorithm_version_id, language,
    decision, confidence, direction
) VALUES (
    gen_random_uuid(), :date, :contract_id, :algorithm_version_id, :language,
    :decision, :confidence, :direction
)
ON CONFLICT ON CONSTRAINT uq_indicator_daily DO UPDATE SET
    decision   = EXCLUDED.decision,
    confidence = EXCLUDED.confidence,
    direction  = EXCLUDED.direction
"""

_READ_REGIME = """
SELECT contract_id, decision, regime, specialist, prob_up
FROM pl_regime_shadow
WHERE date = :date AND algorithm_version_id = :aid
"""

# `rationale` is intentionally absent from this projection — see module docstring.
_READ_JUDGE = """
SELECT final_decision, judge_direction, judge_confidence
FROM pl_judge_shadow
WHERE date = :date
ORDER BY created_at DESC
LIMIT 1
"""


class AdapterSourceMissingError(RuntimeError):
    """No regime row for the date — there is nothing to project."""


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

    written = 0
    for language in ADAPTER_LANGUAGES:
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
            },
        )
        written += 1

    logger.info(
        "adapter row %s: decision=%s confidence=%s (%d languages, prose left to "
        "cc-regime-brief)",
        session_date,
        decision,
        confidence,
        written,
    )
    return written
