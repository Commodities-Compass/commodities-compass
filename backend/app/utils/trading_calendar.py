"""Trading calendar date resolution — single source of truth.

All date resolution goes through ref_trading_calendar.
Async variants for FastAPI, sync variants for scraper scripts.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.reference import RefExchange, RefTradingCalendar


class TradingCalendarError(Exception):
    """Raised when trading calendar lookup fails."""


# Module-level cache: exchange_code -> exchange_id (never changes at runtime).
_exchange_cache: dict[str, uuid.UUID] = {}


# ---------------------------------------------------------------------------
# Internal: exchange code resolution
# ---------------------------------------------------------------------------


async def _resolve_exchange_id(db: AsyncSession, code: str) -> uuid.UUID:
    if code in _exchange_cache:
        return _exchange_cache[code]
    result = await db.execute(select(RefExchange.id).where(RefExchange.code == code))
    row = result.scalar_one_or_none()
    if row is None:
        raise TradingCalendarError(f"Exchange '{code}' not found in ref_exchange")
    _exchange_cache[code] = row
    return row


def _resolve_exchange_id_sync(session: Session, code: str) -> uuid.UUID:
    if code in _exchange_cache:
        return _exchange_cache[code]
    result = session.execute(select(RefExchange.id).where(RefExchange.code == code))
    row = result.scalar_one_or_none()
    if row is None:
        raise TradingCalendarError(f"Exchange '{code}' not found in ref_exchange")
    _exchange_cache[code] = row
    return row


# ---------------------------------------------------------------------------
# Async functions (FastAPI / service layer)
# ---------------------------------------------------------------------------


async def get_latest_trading_day(
    db: AsyncSession,
    target_date: Optional[date] = None,
    exchange_code: str = "IFEU",
) -> date:
    """Most recent trading day <= target_date.

    Raises TradingCalendarError if no trading day is found.
    """
    if target_date is None:
        target_date = date.today()
    exchange_id = await _resolve_exchange_id(db, exchange_code)
    result = await db.execute(
        select(RefTradingCalendar.date)
        .where(
            RefTradingCalendar.exchange_id == exchange_id,
            RefTradingCalendar.date <= target_date,
            RefTradingCalendar.is_trading_day.is_(True),
        )
        .order_by(RefTradingCalendar.date.desc())
        .limit(1)
    )
    trading_day = result.scalar_one_or_none()
    if trading_day is None:
        raise TradingCalendarError(
            f"No trading day found on or before {target_date} for {exchange_code}"
        )
    return trading_day


async def get_previous_trading_day(
    db: AsyncSession,
    target_date: Optional[date] = None,
    exchange_code: str = "IFEU",
) -> date:
    """Most recent trading day strictly before target_date.

    Raises TradingCalendarError if no previous trading day is found.
    """
    if target_date is None:
        target_date = date.today()
    exchange_id = await _resolve_exchange_id(db, exchange_code)
    result = await db.execute(
        select(RefTradingCalendar.date)
        .where(
            RefTradingCalendar.exchange_id == exchange_id,
            RefTradingCalendar.date < target_date,
            RefTradingCalendar.is_trading_day.is_(True),
        )
        .order_by(RefTradingCalendar.date.desc())
        .limit(1)
    )
    trading_day = result.scalar_one_or_none()
    if trading_day is None:
        raise TradingCalendarError(
            f"No trading day found before {target_date} for {exchange_code}"
        )
    return trading_day


async def is_trading_day(
    db: AsyncSession,
    target_date: Optional[date] = None,
    exchange_code: str = "IFEU",
) -> bool:
    """True if target_date is a trading day for the exchange."""
    if target_date is None:
        target_date = date.today()
    exchange_id = await _resolve_exchange_id(db, exchange_code)
    result = await db.execute(
        select(RefTradingCalendar.is_trading_day).where(
            RefTradingCalendar.exchange_id == exchange_id,
            RefTradingCalendar.date == target_date,
        )
    )
    row = result.scalar_one_or_none()
    # Not in calendar (e.g. weekend) -> not a trading day
    return row is True


# ---------------------------------------------------------------------------
# Sync functions (scraper scripts)
# ---------------------------------------------------------------------------


def get_latest_trading_day_sync(
    session: Session,
    target_date: Optional[date] = None,
    exchange_code: str = "IFEU",
) -> date:
    """Sync variant of get_latest_trading_day for scraper scripts."""
    if target_date is None:
        target_date = date.today()
    exchange_id = _resolve_exchange_id_sync(session, exchange_code)
    result = session.execute(
        select(RefTradingCalendar.date)
        .where(
            RefTradingCalendar.exchange_id == exchange_id,
            RefTradingCalendar.date <= target_date,
            RefTradingCalendar.is_trading_day.is_(True),
        )
        .order_by(RefTradingCalendar.date.desc())
        .limit(1)
    )
    trading_day = result.scalar_one_or_none()
    if trading_day is None:
        raise TradingCalendarError(
            f"No trading day found on or before {target_date} for {exchange_code}"
        )
    return trading_day


def is_trading_day_sync(
    session: Session,
    target_date: Optional[date] = None,
    exchange_code: str = "IFEU",
) -> bool:
    """Sync variant of is_trading_day for scraper scripts."""
    if target_date is None:
        target_date = date.today()
    exchange_id = _resolve_exchange_id_sync(session, exchange_code)
    result = session.execute(
        select(RefTradingCalendar.is_trading_day).where(
            RefTradingCalendar.exchange_id == exchange_id,
            RefTradingCalendar.date == target_date,
        )
    )
    row = result.scalar_one_or_none()
    return row is True
