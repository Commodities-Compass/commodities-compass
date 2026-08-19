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
    watch_lines: tuple[str, ...] = (),
) -> None:
    """Attach ``narrative`` to the served row for ``language``.

    ``watch_lines`` is the "to watch" block — pivot levels straight out of
    ``pl_derived_indicators``, built by ``db_reader._build_watch_lines``. It is
    appended to the conclusion here rather than asked of the model, which keeps
    the split the whole pipeline runs on: the narrator writes prose and never a
    figure, the template writes figures and never prose.

    It used to reach the Drive brief only, so the dashboard's "À surveiller"
    sidebar had nothing to render on a served row — the levels a reader acts on
    existed in the podcast and not on screen.

    Raises ``AdapterRowMissingError`` when no row was updated — that means
    cc-regime-daily has not projected this session, and a brief published
    against a decision the dashboard cannot show would be a silent split.
    """
    conclusion = narrative.conclusion
    if watch_lines:
        # The frontend parser opens the watch section on the SECOND '>' line;
        # `_build_watch_lines` already emits the header with that marker.
        conclusion = conclusion.rstrip() + "\n" + "\n".join(watch_lines)
    result: CursorResult = session.execute(
        text(_UPDATE),
        {
            "eco": narrative.eco,
            "conclusion": conclusion,
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
