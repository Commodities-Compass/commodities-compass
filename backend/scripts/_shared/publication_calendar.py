"""Shared publication calendar helpers for fundamentals scrapers.

The ``ref_publication_calendar`` table is the gate for low-frequency scrapers
(ECA, NCA, future ICCO / COCOBOD / etc.). Each scraper queries this table at
startup and only fetches when a publication is currently in its expected
window AND not yet ingested. This avoids 250 daily no-op fetches/year per
scraper while still triggering whenever a publication is due.

See docs/user-stories/P3-fundamental-data-scrapers-grindings.md §2.2.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PendingPublication:
    """One ``ref_publication_calendar`` row waiting to be ingested."""

    source: str
    category: str
    region: str | None
    period_label: str
    period_date: date
    expected_publication_date: date
    tolerance_days: int


def find_pending_publications(
    session: Session,
    *,
    source: str,
    category: str = "grindings",
    today: date | None = None,
) -> list[PendingPublication]:
    """Return publications whose window includes ``today`` and not yet ingested.

    A row matches when::

        actual_publication_date IS NULL
        AND today BETWEEN expected_publication_date - tolerance_days
                       AND expected_publication_date + tolerance_days

    The window is bilateral: the scraper can fire BEFORE the expected date
    (early publications) or AFTER (late publications) within ``tolerance_days``.
    Beyond the window, the daily watchdog flags missing publications.

    Args:
        session: SQLAlchemy sync session.
        source: filter on ``ref_publication_calendar.source`` (e.g. "eca").
        category: filter on ``category`` (defaults to "grindings").
        today: override today's date for tests/backfills (default ``date.today()``).

    Returns:
        List of :class:`PendingPublication` sorted by ``expected_publication_date``.
    """
    cutoff = today or date.today()
    rows = session.execute(
        text(
            """
            SELECT source, category, region, period_label, period_date,
                   expected_publication_date, tolerance_days
            FROM ref_publication_calendar
            WHERE source = :source
              AND category = :category
              AND actual_publication_date IS NULL
              AND :today BETWEEN expected_publication_date - tolerance_days * INTERVAL '1 day'
                              AND expected_publication_date + tolerance_days * INTERVAL '1 day'
            ORDER BY expected_publication_date ASC
            """
        ),
        {"source": source, "category": category, "today": cutoff},
    ).all()

    pending = [
        PendingPublication(
            source=row[0],
            category=row[1],
            region=row[2],
            period_label=row[3],
            period_date=row[4],
            expected_publication_date=row[5],
            tolerance_days=row[6],
        )
        for row in rows
    ]
    logger.info(
        "Calendar gate: %d pending %s/%s publication(s) on %s",
        len(pending),
        source,
        category,
        cutoff,
    )
    return pending
