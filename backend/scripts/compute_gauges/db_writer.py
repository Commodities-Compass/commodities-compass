"""UPSERT gauge rows into pl_dashboard_gauge.

Idempotent on ``(date, contract_id, indicator_name)``: re-running the job for a
date it already covered rewrites the same values. That matters because the
252-day z-score of a given date is stable once its window is full, but the
warm-up rows keep improving as history accumulates — a backfill must be able to
correct them.
"""

from __future__ import annotations

import logging

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.pipeline import PlDashboardGauge

logger = logging.getLogger(__name__)

# Rows per statement. The full backfill is ~5 indicators × ~2700 sessions;
# chunking keeps the parameter count well under the driver limit.
_CHUNK_SIZE = 1000


def upsert_gauges(session: Session, rows: list[dict]) -> int:
    """Write gauge rows, returning how many were sent."""
    if not rows:
        logger.warning("No gauge rows to write")
        return 0

    written = 0
    for start in range(0, len(rows), _CHUNK_SIZE):
        chunk = rows[start : start + _CHUNK_SIZE]
        stmt = pg_insert(PlDashboardGauge).values(chunk)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_dashboard_gauge",
            set_={
                "raw_value": stmt.excluded.raw_value,
                "score_value": stmt.excluded.score_value,
                "norm_value": stmt.excluded.norm_value,
            },
        )
        session.execute(stmt)
        written += len(chunk)
    return written
