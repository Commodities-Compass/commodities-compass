"""London session gate — is the market open right now?

The cron pattern (*/15 8-16 * * 1-5 UTC) is deliberately wide so it covers
both GMT and BST regimes; this in-code gate cuts the out-of-session ticks
(exit 0 = success for the Sentry cron monitor).
"""

from __future__ import annotations

from datetime import date, datetime

from scripts.intraday_monitor.config import (
    LONDON_SESSION_CLOSE,
    LONDON_SESSION_OPEN,
    LONDON_TZ,
)


def in_london_session(now_utc: datetime) -> bool:
    """True iff ``now_utc`` falls inside [open, close) London wall-clock time."""
    local = now_utc.astimezone(LONDON_TZ).time()
    return LONDON_SESSION_OPEN <= local < LONDON_SESSION_CLOSE


def london_session_date(now_utc: datetime) -> date:
    """The London calendar date of the session in progress."""
    return now_utc.astimezone(LONDON_TZ).date()
