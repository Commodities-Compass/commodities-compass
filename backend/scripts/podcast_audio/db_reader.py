"""Reading one episode's inputs: the figures, and the prose already published.

The podcast does not re-derive anything. ``cc-regime-brief`` has already written
the narrative onto the served row, and that is what the dashboard renders — so
the episode quotes it rather than composing a second opinion from the same data.
Two sources that say almost the same thing is how a product starts contradicting
itself in front of a client.

The served version is resolved by ``serving_rank = 1``, never by a name pinned in
code: that integer is what decides what is published (see CLAUDE.md).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date as date_cls

from sqlalchemy import text
from sqlalchemy.orm import Session

from scripts.regime_brief.db_reader import BriefData, read_brief_data
from scripts.regime_brief.narrator import Narrative


class EpisodeInputsMissingError(RuntimeError):
    """An input the episode cannot be written without."""


@dataclass(frozen=True)
class EpisodeInputs:
    """Everything ``script_writer`` needs for one session in one language."""

    data: BriefData
    narrative: Narrative


def resolve_served_version_id(session: Session) -> uuid.UUID:
    """The algorithm version currently published."""
    row = session.execute(
        text(
            "SELECT id FROM pl_algorithm_version "
            "WHERE serving_rank = 1 ORDER BY version DESC LIMIT 1"
        )
    ).fetchone()
    if row is None:
        raise EpisodeInputsMissingError(
            "no pl_algorithm_version carries serving_rank = 1 — nothing is served"
        )
    return row[0]


def _read_narrative(
    session: Session,
    *,
    session_date: date_cls,
    algorithm_version_id: uuid.UUID,
    language: str,
) -> Narrative:
    row = session.execute(
        text(
            "SELECT conclusion, eco, confidence_rationale FROM pl_indicator_daily "
            "WHERE date = :d AND algorithm_version_id = :v AND language = :l"
        ),
        {"d": session_date, "v": str(algorithm_version_id), "l": language},
    ).fetchone()
    if row is None:
        raise EpisodeInputsMissingError(
            f"no served row for {session_date} [{language}]"
        )
    if not (row.conclusion or "").strip():
        # cc-regime-brief writes the prose; without it there is nothing to voice
        # and the episode would have to invent its own read.
        raise EpisodeInputsMissingError(
            f"served row {session_date} [{language}] carries no narrative — "
            "run cc-regime-brief first"
        )
    return Narrative(
        conclusion=row.conclusion,
        eco=row.eco or "",
        confidence_rationale=row.confidence_rationale or "",
    )


def read_episode_inputs(
    session: Session, *, session_date: date_cls, language: str
) -> EpisodeInputs:
    """Assemble one episode's inputs, or fail loud on the first gap."""
    version_id = resolve_served_version_id(session)
    data = read_brief_data(
        session,
        session_date=session_date,
        algorithm_version_id=version_id,
        language=language,
    )
    narrative = _read_narrative(
        session,
        session_date=session_date,
        algorithm_version_id=version_id,
        language=language,
    )
    return EpisodeInputs(data=data, narrative=narrative)
