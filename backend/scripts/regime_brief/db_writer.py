"""Persist the narrative onto the served row, in its own language.

The adapter row (written by cc-regime-daily) carries the structure — decision,
confidence, direction. This fills in the prose for one language. Splitting it
that way is what lets the decision land at 19:50 and the narrative at 19:55
without either job knowing about the other's internals.

UPDATE, never INSERT: the row must already exist. If it does not, the adapter
did not run, and inventing a row here would paper over a broken pipeline.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date as date_cls

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from scripts.regime_brief.narrator import Narrative

logger = logging.getLogger(__name__)


class AdapterRowMissingError(RuntimeError):
    """No served row to attach the narrative to."""


_UPDATE = """
UPDATE pl_indicator_daily
SET eco = :eco,
    conclusion = :conclusion,
    confidence_rationale = :confidence_rationale
WHERE date = :date
  AND algorithm_version_id = :algorithm_version_id
  AND language = :language
"""


def write_narrative(
    session: Session,
    narrative: Narrative,
    *,
    session_date: date_cls,
    algorithm_version_id: uuid.UUID | str,
    language: str,
) -> None:
    """Attach ``narrative`` to the served row for ``language``.

    Raises ``AdapterRowMissingError`` when no row was updated — that means
    cc-regime-daily has not projected this session, and a brief published
    against a decision the dashboard cannot show would be a silent split.
    """
    result: CursorResult = session.execute(
        text(_UPDATE),
        {
            "eco": narrative.eco,
            "conclusion": narrative.conclusion,
            "confidence_rationale": narrative.confidence_rationale,
            "date": session_date,
            "algorithm_version_id": str(algorithm_version_id),
            "language": language,
        },
    )
    if result.rowcount == 0:
        raise AdapterRowMissingError(
            f"No pl_indicator_daily row at {session_date} for algorithm "
            f"{algorithm_version_id} language={language}. Run cc-regime-daily "
            "for this session first — the narrative has nothing to attach to."
        )
    logger.info(
        "narrative persisted [%s] on %s (%d row)",
        language,
        session_date,
        result.rowcount,
    )
