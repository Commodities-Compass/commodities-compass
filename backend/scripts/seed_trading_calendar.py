"""Seed ref_trading_calendar with ICE Futures Europe trading days (2024-2026).

Generates all weekday dates in the range, marks holidays and half-days
from a hardcoded list, and inserts rows into ref_trading_calendar.
Idempotent: skips dates that already exist for the exchange.

Usage:
    poetry run seed-trading-calendar                    # Seed to local DB
    poetry run seed-trading-calendar --dry-run          # Preview without writing
    poetry run seed-trading-calendar --target-url "postgresql+psycopg2://..."
"""

from __future__ import annotations

import argparse
import logging
from datetime import date, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.reference import RefExchange, RefTradingCalendar

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

DEFAULT_TARGET_URL = (
    "postgresql+psycopg2://postgres:password@localhost:5433/commodities_compass"
)

EXCHANGE_CODE = "IFEU"

# Date range: covers all contract data from CAU24 onwards through end of 2026
CALENDAR_START = date(2024, 1, 1)
CALENDAR_END = date(2026, 12, 31)

# ICE Futures Europe holidays — verified against UK bank holidays + ICE circulars.
# Key: date → (session_type, reason)
#   "holiday"  = market closed all day
#   "half_day" = early close (typically 12:30 London time for soft commodities)
ICE_EUROPE_HOLIDAYS: dict[date, tuple[str, str]] = {
    # ── 2024 ──
    date(2024, 1, 1): ("holiday", "New Year's Day"),
    date(2024, 3, 29): ("holiday", "Good Friday"),
    date(2024, 4, 1): ("holiday", "Easter Monday"),
    date(2024, 5, 6): ("holiday", "Early May Bank Holiday"),
    date(2024, 5, 27): ("holiday", "Spring Bank Holiday"),
    date(2024, 8, 26): ("holiday", "Summer Bank Holiday"),
    date(2024, 12, 24): ("half_day", "Christmas Eve"),
    date(2024, 12, 25): ("holiday", "Christmas Day"),
    date(2024, 12, 26): ("holiday", "Boxing Day"),
    date(2024, 12, 31): ("half_day", "New Year's Eve"),
    # ── 2025 ──
    date(2025, 1, 1): ("holiday", "New Year's Day"),
    date(2025, 4, 18): ("holiday", "Good Friday"),
    date(2025, 4, 21): ("holiday", "Easter Monday"),
    date(2025, 5, 5): ("holiday", "Early May Bank Holiday"),
    date(2025, 5, 26): ("holiday", "Spring Bank Holiday"),
    date(2025, 8, 25): ("holiday", "Summer Bank Holiday"),
    date(2025, 12, 24): ("half_day", "Christmas Eve"),
    date(2025, 12, 25): ("holiday", "Christmas Day"),
    date(2025, 12, 26): ("holiday", "Boxing Day"),
    date(2025, 12, 31): ("half_day", "New Year's Eve"),
    # ── 2026 ──
    date(2026, 1, 1): ("holiday", "New Year's Day"),
    date(2026, 4, 3): ("holiday", "Good Friday"),
    date(2026, 4, 6): ("holiday", "Easter Monday"),
    date(2026, 5, 4): ("holiday", "Early May Bank Holiday"),
    date(2026, 5, 25): ("holiday", "Spring Bank Holiday"),
    date(2026, 8, 31): ("holiday", "Summer Bank Holiday"),
    date(2026, 12, 24): ("half_day", "Christmas Eve"),
    date(2026, 12, 25): ("holiday", "Christmas Day"),
    date(2026, 12, 28): ("holiday", "Boxing Day (observed)"),
    date(2026, 12, 31): ("half_day", "New Year's Eve"),
}


def generate_calendar_rows(
    exchange_id,
) -> list[dict]:
    """Generate trading calendar rows for all weekdays in the date range."""
    rows: list[dict] = []
    current = CALENDAR_START
    while current <= CALENDAR_END:
        # Skip weekends (5=Saturday, 6=Sunday)
        if current.weekday() < 5:
            holiday_info = ICE_EUROPE_HOLIDAYS.get(current)
            if holiday_info is not None:
                session_type, reason = holiday_info
                is_trading = session_type == "half_day"
            else:
                session_type = "regular"
                reason = None
                is_trading = True

            rows.append(
                {
                    "exchange_id": exchange_id,
                    "date": current,
                    "is_trading_day": is_trading,
                    "session_type": session_type,
                    "reason": reason,
                }
            )
        current += timedelta(days=1)
    return rows


def seed_trading_calendar(session: Session, dry_run: bool = False) -> int:
    """Insert trading calendar rows. Skips dates that already exist."""
    exchange = session.execute(
        select(RefExchange).where(RefExchange.code == EXCHANGE_CODE)
    ).scalar_one_or_none()

    if exchange is None:
        log.error("Exchange %s not found — run seed-gcp first", EXCHANGE_CODE)
        return 0

    # Check existing dates to avoid duplicates
    existing_dates: set[date] = set(
        session.execute(
            select(RefTradingCalendar.date).where(
                RefTradingCalendar.exchange_id == exchange.id
            )
        )
        .scalars()
        .all()
    )

    rows = generate_calendar_rows(exchange.id)
    new_rows = [r for r in rows if r["date"] not in existing_dates]

    if not new_rows:
        log.info("All %d calendar dates already exist — nothing to insert", len(rows))
        return 0

    for row in new_rows:
        session.add(RefTradingCalendar(**row))

    session.flush()

    # Stats
    holidays = sum(1 for r in new_rows if r["session_type"] == "holiday")
    half_days = sum(1 for r in new_rows if r["session_type"] == "half_day")
    regular = sum(1 for r in new_rows if r["session_type"] == "regular")
    log.info(
        "Inserted %d rows: %d regular, %d holidays, %d half-days (skipped %d existing)",
        len(new_rows),
        regular,
        holidays,
        half_days,
        len(existing_dates),
    )
    return len(new_rows)


def run(target_url: str = DEFAULT_TARGET_URL, dry_run: bool = False) -> None:
    """Main entry point."""
    engine = create_engine(target_url)
    with Session(engine) as session:
        count = seed_trading_calendar(session, dry_run=dry_run)
        if dry_run:
            log.info("DRY RUN — rolling back %d rows", count)
            session.rollback()
        else:
            session.commit()
            log.info("Committed %d trading calendar rows", count)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed ICE Europe trading calendar (2024-2026)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview without writing"
    )
    parser.add_argument(
        "--target-url",
        default=DEFAULT_TARGET_URL,
        help="Target database URL (default: local Docker :5433)",
    )
    args = parser.parse_args()
    run(target_url=args.target_url, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
