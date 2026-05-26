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


def has_contract_data_for_date(target_date: date) -> bool:
    """Return True if pl_contract_data_daily has a row for target_date (active contract).

    Opens its own short-lived session. Used by downstream jobs (daily-analysis,
    compass-brief) to avoid running when upstream scrapers haven't created data.
    """
    from sqlalchemy import text

    with get_session() as session:
        row = session.execute(
            text(
                "SELECT 1 FROM pl_contract_data_daily d "
                "JOIN ref_contract c ON d.contract_id = c.id "
                "WHERE d.date = :dt AND c.is_active = true "
                "LIMIT 1"
            ),
            {"dt": target_date},
        ).fetchone()
        return row is not None


def get_next_session_date(
    target_date: date | None = None,
    exchange_code: str = "IFEU",
) -> date:
    """Return the next trading session strictly AFTER target_date (default: today).

    Alias of :func:`get_display_date` but named for the P2b Phase B agents
    (press_review, meteo, daily_analysis, compass_brief) — these write data
    keyed to the upcoming session, not "today". On weekends and holidays
    this skips ahead to the next IFEU trading day automatically.
    """
    from app.utils.trading_calendar import get_next_trading_day_sync

    check_date = target_date or date.today()
    with get_session() as session:
        return get_next_trading_day_sync(session, check_date, exchange_code)


def is_eve_of_trading_day(
    today: date | None = None,
    exchange_code: str = "IFEU",
) -> bool:
    """Return True iff TOMORROW is a trading day.

    Gate used by P2b Phase B daily cron jobs to decide whether to fire.
    The cron pattern is ``M H * * *`` (every day), and each agent calls
    this at startup to skip cleanly when there is no upcoming session
    (e.g. Friday → Saturday eve, or Sunday → bank-holiday-Monday eve).

    Pure-local question — never refers to upstream history, so every
    holiday pattern self-corrects without special-casing.
    """
    from datetime import timedelta

    from app.utils.trading_calendar import is_trading_day_sync

    today = today or date.today()
    tomorrow = today + timedelta(days=1)
    with get_session() as session:
        return is_trading_day_sync(session, tomorrow, exchange_code)


def get_previous_session_date(
    target_date: date,
    exchange_code: str = "IFEU",
) -> date:
    """Return the last trading session strictly BEFORE target_date.

    Used by daily-analysis Call #1/#2 to read upstream technicals
    (the most recent completed market session) when its own
    ``target_date`` is the NEXT trading day.
    """
    from app.utils.trading_calendar import get_previous_trading_day_sync

    with get_session() as session:
        return get_previous_trading_day_sync(session, target_date, exchange_code)


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
