"""Shared sync DB session factory for scraper scripts.

All scrapers write to GCP Cloud SQL via DATABASE_SYNC_URL env var.
No default fallback — must be explicitly set to prevent accidental local writes.
"""

import logging
import os
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
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
    (meteo, press_review, ensemble_compute, daily_analysis, ensemble_explainer,
    compass_brief, compass_brief_ensemble) — these write data keyed to the
    upcoming session, not "today". On weekends and holidays this skips ahead
    to the next IFEU trading day automatically.
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


def is_trading_day(
    check_date: date,
    exchange_code: str = "IFEU",
) -> bool:
    """Return True iff ``check_date`` is a trading session for the exchange.

    Opens its own short-lived session. Used to fail-loud on an operator
    ``--session-date`` that names a weekend or exchange holiday.
    """
    from app.utils.trading_calendar import is_trading_day_sync

    with get_session() as session:
        return is_trading_day_sync(session, check_date, exchange_code)


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


@dataclass(frozen=True)
class PhaseBDates:
    """Immutable Phase-B date pair — the single source of truth for the split.

    Every Phase-B job (meteo, press_review, ensemble_compute, daily_analysis,
    ensemble_explainer, compass_brief, compass_brief_ensemble) derives its two
    dates from :func:`resolve_phase_b_dates` and NEVER re-computes them inline.

    Attributes:
        target_date: T+1 — the upcoming trading session the work informs.
            Drives prompt framing and Sentry context only. NEVER a DB write key.
        data_date: T — the last completed session. The row date that EVERY
            Phase-B DB write and brief filename is keyed to.

    Getting this backwards (writing a row at ``target_date``) is the recurring
    P2b bug that renders the dashboard empty the morning after — see
    ``docs/architecture/flows/date-semantics.md``.
    """

    target_date: date
    data_date: date


def resolve_phase_b_dates(
    session_date: date | None = None,
    exchange_code: str = "IFEU",
) -> PhaseBDates:
    """Resolve the ``(target_date, data_date)`` pair for a Phase-B job.

    Two paths, one immutable result:

    * **Cron** (``session_date=None``) — derive from today. The job fires on the
      eve of a trading day, so ``target_date`` is the upcoming session and
      ``data_date`` is the session that just closed::

          target_date = get_next_session_date(today)        # T+1
          data_date   = get_previous_session_date(target)   # T

    * **Backfill** (explicit ``session_date``) — the operator types the ROW date
      (the session to (re)generate). ``data_date`` is exactly what they typed;
      ``target_date`` is derived and only used for framing::

          data_date   = session_date                        # T (what you type)
          target_date = get_next_session_date(session_date) # T+1 (derived)

    Both paths yield the same pair for the same underlying session, so a backfill
    of session T produces rows identical to the cron run that first wrote T.
    """
    if session_date is not None:
        # Fail-loud: an explicit --session-date must name a real trading session,
        # otherwise the job would write a pl_* row keyed to a weekend/holiday.
        if not is_trading_day(session_date, exchange_code):
            raise ValueError(
                f"--session-date {session_date} is not a {exchange_code} trading "
                "day. Pass the session date T (the row date to regenerate), not a "
                "weekend or exchange holiday."
            )
        data_date = session_date
        target_date = get_next_session_date(session_date, exchange_code)
    else:
        target_date = get_next_session_date(date.today(), exchange_code)
        data_date = get_previous_session_date(target_date, exchange_code)
    return PhaseBDates(target_date=target_date, data_date=data_date)


def phase_b_should_skip(
    session_date: date | None,
    force: bool,
    exchange_code: str = "IFEU",
) -> bool:
    """Return True iff a Phase-B run should skip cleanly (exit 0).

    Skips ONLY in the pure cron path — no explicit ``session_date``, no
    ``--force`` — when tomorrow is not a trading day (Fri→Sat eve, or an eve of
    a holiday). An explicit ``session_date`` or ``force`` always runs (backfills
    and manual reruns bypass the gate).
    """
    if force or session_date is not None:
        return False
    return not is_eve_of_trading_day(exchange_code=exchange_code)


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
