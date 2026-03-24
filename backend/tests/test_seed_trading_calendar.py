"""Tests for the trading calendar seed script.

Tests cover:
- generate_calendar_rows produces correct counts
- Holidays are marked correctly (is_trading_day=False, session_type=holiday)
- Half-days are marked correctly (is_trading_day=True, session_type=half_day)
- Regular weekdays are marked correctly
- No weekend dates are generated
- All hardcoded holidays fall on weekdays
"""

import uuid
from datetime import date

import pytest

from scripts.seed_trading_calendar import (
    CALENDAR_END,
    CALENDAR_START,
    ICE_EUROPE_HOLIDAYS,
    generate_calendar_rows,
)


@pytest.fixture
def exchange_id():
    return uuid.uuid4()


@pytest.fixture
def rows(exchange_id):
    return generate_calendar_rows(exchange_id)


class TestGenerateCalendarRows:
    def test_no_weekends(self, rows):
        for row in rows:
            assert row["date"].weekday() < 5, f"{row['date']} is a weekend"

    def test_all_holidays_are_weekdays(self):
        for d in ICE_EUROPE_HOLIDAYS:
            assert d.weekday() < 5, f"Holiday {d} falls on a weekend"

    def test_row_count_is_all_weekdays_in_range(self, rows):
        expected = 0
        current = CALENDAR_START
        while current <= CALENDAR_END:
            if current.weekday() < 5:
                expected += 1
            current += __import__("datetime").timedelta(days=1)
        assert len(rows) == expected

    def test_holidays_marked_not_trading(self, rows):
        by_date = {r["date"]: r for r in rows}
        for d, (session_type, reason) in ICE_EUROPE_HOLIDAYS.items():
            row = by_date[d]
            if session_type == "holiday":
                assert row["is_trading_day"] is False
                assert row["session_type"] == "holiday"
            elif session_type == "half_day":
                assert row["is_trading_day"] is True
                assert row["session_type"] == "half_day"
            assert row["reason"] == reason

    def test_regular_days_have_no_reason(self, rows):
        regular = [r for r in rows if r["session_type"] == "regular"]
        assert len(regular) > 0
        for r in regular:
            assert r["is_trading_day"] is True
            assert r["reason"] is None

    def test_date_range_boundaries(self, rows):
        dates = [r["date"] for r in rows]
        # First weekday in range
        assert min(dates) == date(2024, 1, 1)  # Monday
        # Last weekday in range
        assert max(dates) == date(2026, 12, 31)  # Thursday

    def test_holiday_count_per_year(self, rows):
        by_year: dict[int, list] = {}
        for r in rows:
            year = r["date"].year
            if r["session_type"] != "regular":
                by_year.setdefault(year, []).append(r)
        # 2024: 8 holidays + 2 half-days = 10
        assert len(by_year[2024]) == 10
        # 2025: 8 holidays + 2 half-days = 10
        assert len(by_year[2025]) == 10
        # 2026: 8 holidays + 2 half-days = 10
        assert len(by_year[2026]) == 10

    def test_exchange_id_propagated(self, exchange_id, rows):
        for r in rows:
            assert r["exchange_id"] == exchange_id
