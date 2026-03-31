"""Tests for trading calendar date resolution functions.

Tests cover:
- get_latest_trading_day returns same date for trading days
- get_latest_trading_day skips holidays and weekends
- get_latest_trading_day raises TradingCalendarError when no data
- get_previous_trading_day returns strictly prior trading day
- is_trading_day returns correct boolean
- Sync variants mirror async behavior
"""

import uuid
from datetime import date

import pytest
from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.models.reference import RefExchange, RefTradingCalendar
from app.utils.trading_calendar import (
    TradingCalendarError,
    get_latest_trading_day,
    get_latest_trading_day_sync,
    get_previous_trading_day,
    is_trading_day,
    is_trading_day_sync,
    _exchange_cache,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_exchange_cache():
    """Reset module-level cache between tests."""
    _exchange_cache.clear()
    yield
    _exchange_cache.clear()


@pytest.fixture
async def seeded_db(db_session) -> tuple:
    """Seed a test exchange and a small trading calendar window.

    Returns (session, exchange_code) with a unique code per test to avoid
    UNIQUE constraint collisions in the session-scoped in-memory DB.
    """
    exchange_id = uuid.uuid4()
    exchange_code = f"EX_{exchange_id.hex[:8]}"

    await db_session.execute(
        insert(RefExchange).values(
            id=exchange_id,
            code=exchange_code,
            name="Test Exchange",
            timezone="UTC",
        )
    )
    # Week of 2026-03-23 (Mon) to 2026-03-27 (Fri)
    # Monday=trading, Tuesday=trading, Wednesday=holiday,
    # Thursday=trading, Friday=trading
    rows = [
        {
            "date": date(2026, 3, 23),
            "is_trading_day": True,
            "session_type": "regular",
            "reason": None,
        },
        {
            "date": date(2026, 3, 24),
            "is_trading_day": True,
            "session_type": "regular",
            "reason": None,
        },
        {
            "date": date(2026, 3, 25),
            "is_trading_day": False,
            "session_type": "holiday",
            "reason": "Test Holiday",
        },
        {
            "date": date(2026, 3, 26),
            "is_trading_day": True,
            "session_type": "regular",
            "reason": None,
        },
        {
            "date": date(2026, 3, 27),
            "is_trading_day": True,
            "session_type": "regular",
            "reason": None,
        },
    ]
    for row in rows:
        await db_session.execute(
            insert(RefTradingCalendar).values(
                id=uuid.uuid4(),
                exchange_id=exchange_id,
                **row,
            )
        )
    await db_session.flush()
    return db_session, exchange_code


# ---------------------------------------------------------------------------
# Async: get_latest_trading_day
# ---------------------------------------------------------------------------


class TestGetLatestTradingDay:
    async def test_returns_same_date_if_trading_day(self, seeded_db):
        db, code = seeded_db
        result = await get_latest_trading_day(db, date(2026, 3, 23), code)
        assert result == date(2026, 3, 23)

    async def test_skips_holiday(self, seeded_db):
        db, code = seeded_db
        # Wednesday 25th is a holiday -> should return Tuesday 24th
        result = await get_latest_trading_day(db, date(2026, 3, 25), code)
        assert result == date(2026, 3, 24)

    async def test_skips_weekend(self, seeded_db):
        db, code = seeded_db
        # Saturday 28th and Sunday 29th are not in calendar -> should return Friday 27th
        result = await get_latest_trading_day(db, date(2026, 3, 29), code)
        assert result == date(2026, 3, 27)

    async def test_raises_when_no_data(self, seeded_db):
        db, code = seeded_db
        # Date before any seeded data
        with pytest.raises(TradingCalendarError):
            await get_latest_trading_day(db, date(2020, 1, 1), code)

    async def test_raises_for_unknown_exchange(self, seeded_db):
        db, _ = seeded_db
        with pytest.raises(TradingCalendarError, match="Exchange.*not found"):
            await get_latest_trading_day(db, date(2026, 3, 23), "UNKNOWN")

    async def test_defaults_to_today_when_none(self, seeded_db):
        db, code = seeded_db
        # Should not raise (just returns whatever is latest <= today)
        try:
            await get_latest_trading_day(db, None, code)
        except TradingCalendarError:
            pass  # OK if today is outside seeded range


# ---------------------------------------------------------------------------
# Async: get_previous_trading_day
# ---------------------------------------------------------------------------


class TestGetPreviousTradingDay:
    async def test_returns_strictly_previous(self, seeded_db):
        db, code = seeded_db
        # Previous to Thursday 26th -> Tuesday 24th (skipping Wednesday holiday)
        result = await get_previous_trading_day(db, date(2026, 3, 26), code)
        assert result == date(2026, 3, 24)

    async def test_previous_from_regular_day(self, seeded_db):
        db, code = seeded_db
        # Previous to Tuesday 24th -> Monday 23rd
        result = await get_previous_trading_day(db, date(2026, 3, 24), code)
        assert result == date(2026, 3, 23)

    async def test_raises_when_no_previous(self, seeded_db):
        db, code = seeded_db
        # No trading day before Monday 23rd in our seed data
        with pytest.raises(TradingCalendarError):
            await get_previous_trading_day(db, date(2026, 3, 23), code)


# ---------------------------------------------------------------------------
# Async: is_trading_day
# ---------------------------------------------------------------------------


class TestIsTradingDay:
    async def test_true_for_regular_day(self, seeded_db):
        db, code = seeded_db
        assert await is_trading_day(db, date(2026, 3, 23), code) is True

    async def test_false_for_holiday(self, seeded_db):
        db, code = seeded_db
        assert await is_trading_day(db, date(2026, 3, 25), code) is False

    async def test_false_for_weekend(self, seeded_db):
        db, code = seeded_db
        # Saturday not in calendar -> False
        assert await is_trading_day(db, date(2026, 3, 28), code) is False


# ---------------------------------------------------------------------------
# Sync variants
# ---------------------------------------------------------------------------


def _seed_calendar_rows() -> list[dict]:
    return [
        {
            "date": date(2026, 3, 23),
            "is_trading_day": True,
            "session_type": "regular",
            "reason": None,
        },
        {
            "date": date(2026, 3, 24),
            "is_trading_day": True,
            "session_type": "regular",
            "reason": None,
        },
        {
            "date": date(2026, 3, 25),
            "is_trading_day": False,
            "session_type": "holiday",
            "reason": "Test Holiday",
        },
        {
            "date": date(2026, 3, 26),
            "is_trading_day": True,
            "session_type": "regular",
            "reason": None,
        },
        {
            "date": date(2026, 3, 27),
            "is_trading_day": True,
            "session_type": "regular",
            "reason": None,
        },
    ]


@pytest.fixture
def seeded_sync_db(sync_db_session: Session) -> tuple[Session, str]:
    """Seed a test exchange and calendar for sync tests."""
    exchange_id = uuid.uuid4()
    exchange_code = f"SX_{exchange_id.hex[:8]}"

    sync_db_session.execute(
        insert(RefExchange).values(
            id=exchange_id,
            code=exchange_code,
            name="Test Exchange",
            timezone="UTC",
        )
    )
    for row in _seed_calendar_rows():
        sync_db_session.execute(
            insert(RefTradingCalendar).values(
                id=uuid.uuid4(),
                exchange_id=exchange_id,
                **row,
            )
        )
    sync_db_session.flush()
    return sync_db_session, exchange_code


class TestSyncVariants:
    def test_get_latest_trading_day_sync(self, seeded_sync_db):
        session, code = seeded_sync_db
        result = get_latest_trading_day_sync(session, date(2026, 3, 25), code)
        assert result == date(2026, 3, 24)

    def test_is_trading_day_sync_true(self, seeded_sync_db):
        session, code = seeded_sync_db
        assert is_trading_day_sync(session, date(2026, 3, 23), code) is True

    def test_is_trading_day_sync_false(self, seeded_sync_db):
        session, code = seeded_sync_db
        assert is_trading_day_sync(session, date(2026, 3, 25), code) is False

    def test_sync_raises_when_no_data(self, seeded_sync_db):
        session, code = seeded_sync_db
        with pytest.raises(TradingCalendarError):
            get_latest_trading_day_sync(session, date(2020, 1, 1), code)


# ---------------------------------------------------------------------------
# Exchange cache
# ---------------------------------------------------------------------------


class TestExchangeCache:
    async def test_cache_populated_after_first_call(self, seeded_db):
        db, code = seeded_db
        assert code not in _exchange_cache
        await get_latest_trading_day(db, date(2026, 3, 23), code)
        assert code in _exchange_cache
