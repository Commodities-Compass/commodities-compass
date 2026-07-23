"""Session gate tests — London trading window with DST handling."""

from datetime import date, datetime, timezone

from scripts.intraday_monitor.session_gate import (
    in_london_session,
    london_session_date,
)


class TestInLondonSession:
    def test_mid_session_summer(self):
        # 09:00 UTC = 10:00 BST → in session
        assert in_london_session(datetime(2026, 7, 22, 9, 0, tzinfo=timezone.utc))

    def test_evening_out_of_session(self):
        # 17:00 UTC = 18:00 BST → out
        assert not in_london_session(datetime(2026, 7, 22, 17, 0, tzinfo=timezone.utc))

    def test_mid_session_winter(self):
        # 10:00 UTC = 10:00 GMT → in session
        assert in_london_session(datetime(2026, 1, 14, 10, 0, tzinfo=timezone.utc))

    def test_dst_boundary_correctness(self):
        # 08:45 UTC = 09:45 BST (in) in July, but 08:45 GMT (before open) in Jan
        assert in_london_session(datetime(2026, 7, 22, 8, 45, tzinfo=timezone.utc))
        assert not in_london_session(datetime(2026, 1, 21, 8, 45, tzinfo=timezone.utc))

    def test_before_open(self):
        # 08:00 UTC = 09:00 BST < 09:30 open
        assert not in_london_session(datetime(2026, 7, 22, 8, 0, tzinfo=timezone.utc))

    def test_late_session_still_open(self):
        # 15:50 UTC = 16:50 BST < 16:55 close (official ICE hours) → in
        assert in_london_session(datetime(2026, 7, 22, 15, 50, tzinfo=timezone.utc))

    def test_close_boundary_exclusive(self):
        # 15:55 UTC = 16:55 BST = close → out (half-open interval)
        assert not in_london_session(datetime(2026, 7, 22, 15, 55, tzinfo=timezone.utc))


class TestLondonSessionDate:
    def test_returns_london_calendar_date(self):
        assert london_session_date(
            datetime(2026, 7, 23, 10, 0, tzinfo=timezone.utc)
        ) == date(2026, 7, 23)

    def test_utc_midnight_rolls_to_london_next_day_in_summer(self):
        # 23:30 UTC = 00:30 BST next day
        assert london_session_date(
            datetime(2026, 7, 22, 23, 30, tzinfo=timezone.utc)
        ) == date(2026, 7, 23)
