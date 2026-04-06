"""Shared sync DB session factory for scraper scripts.

All scrapers write to GCP Cloud SQL via DATABASE_SYNC_URL env var.
No default fallback — must be explicitly set to prevent accidental local writes.
"""

import logging
import os
from collections.abc import Generator
from contextlib import contextmanager
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

_logger = logging.getLogger(__name__)


class DbSessionError(Exception):
    pass


def get_sync_engine(url: str | None = None):
    """Create a sync SQLAlchemy engine from DATABASE_SYNC_URL or explicit URL."""
    db_url = url or os.getenv("DATABASE_SYNC_URL")
    if not db_url:
        raise DbSessionError(
            "DATABASE_SYNC_URL env var not set. "
            "Set it to the GCP Cloud SQL connection string."
        )
    return create_engine(db_url, pool_pre_ping=True)


@contextmanager
def get_session(url: str | None = None) -> Generator[Session, None, None]:
    """Yield a sync session that auto-commits on success, rolls back on error."""
    engine = get_sync_engine(url)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


def get_display_date(
    target_date: date | None = None,
    exchange_code: str = "IFEU",
) -> date:
    """Return the next trading day after target_date (default: today).

    This is the date that will be stored in the database — it represents
    when users will first see this data on the dashboard.

    Opens its own short-lived session. Fail-closed: if the calendar lookup
    fails, the exception propagates and the job fails (exit 1).
    """
    from app.utils.trading_calendar import get_next_trading_day_sync

    check_date = target_date or date.today()
    with get_session() as session:
        return get_next_trading_day_sync(session, check_date, exchange_code)


def should_skip_non_trading_day(
    force: bool = False,
    target_date: date | None = None,
    exchange_code: str = "IFEU",
) -> bool:
    """Return True if today is not a trading day and the job should skip.

    Opens its own short-lived session so callers don't need to manage one.
    Fail-closed: if the calendar check fails, the exception propagates and
    the job fails (exit 1). This prevents unnecessary scrapes, token spend,
    and stale data on non-trading days.
    """
    if force:
        return False

    from app.utils.trading_calendar import is_trading_day_sync

    check_date = target_date or date.today()
    with get_session() as session:
        if not is_trading_day_sync(session, check_date, exchange_code):
            _logger.info(
                "Skipping: %s is not a trading day for %s",
                check_date,
                exchange_code,
            )
            return True
    return False
