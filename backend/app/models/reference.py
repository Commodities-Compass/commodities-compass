"""Reference tables for the MVP schema.

Static and semi-static entities: exchanges, commodities, contracts, trading calendar.
All in public schema with ref_ prefix, ready for eventual schema split.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    DATE,
    INTEGER,
    TEXT,
    TIMESTAMP,
    VARCHAR,
    Boolean,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class RefExchange(Base):
    """Exchange registry (ICE Europe, ICE US, CME, etc.)."""

    __tablename__ = "ref_exchange"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(VARCHAR(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(VARCHAR(100), nullable=False)
    timezone: Mapped[str] = mapped_column(VARCHAR(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())


class RefCommodity(Base):
    """Commodity registry (London Cocoa, NY Cocoa, Sugar #11, etc.)."""

    __tablename__ = "ref_commodity"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(VARCHAR(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(VARCHAR(100), nullable=False)
    exchange_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ref_exchange.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())


class RefContract(Base):
    """Specific tradeable contract (e.g. CAK26 = London Cocoa May 2026).

    Contract-centric from day one: all market data is keyed to contracts,
    not commodities. The front-month is derived, not stored.
    """

    __tablename__ = "ref_contract"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    commodity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ref_commodity.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(VARCHAR(20), unique=True, nullable=False)
    contract_month: Mapped[str] = mapped_column(VARCHAR(10), nullable=False)
    expiry_date: Mapped[Optional[date]] = mapped_column(DATE)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Canonical front-month roll calendar: the session date this contract became
    # the operator-pinned front-month. NULL = never front-month. Resolver:
    # front_month_for_date(d) = contract with greatest active_from <= d.
    active_from: Mapped[Optional[date]] = mapped_column(DATE)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())


class RefTradingCalendar(Base):
    """Trading days per exchange. Distinguishes 'scraper failed' from 'market closed'."""

    __tablename__ = "ref_trading_calendar"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    exchange_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ref_exchange.id"), nullable=False
    )
    date: Mapped[date] = mapped_column(DATE, nullable=False)
    is_trading_day: Mapped[bool] = mapped_column(Boolean, nullable=False)
    session_type: Mapped[Optional[str]] = mapped_column(String(20))
    reason: Mapped[Optional[str]] = mapped_column(String(100))

    __table_args__ = (
        UniqueConstraint(
            "exchange_id", "date", name="uq_trading_calendar_exchange_date"
        ),
        Index("ix_trading_calendar_date", "date"),
    )


class RefPublicationCalendar(Base):
    """Expected publication dates for fundamental data sources.

    Source of truth used by fundamentals scrapers (ECA, NCA, future ICCO)
    to decide whether to fetch on a given day. Each row represents one
    expected publication, identified by ``(source, category, period_label)``.

    Scrapers gate on::

        actual_publication_date IS NULL
        AND today() BETWEEN expected - tolerance AND expected + tolerance

    Once a publication is successfully ingested, the scraper UPDATEs
    ``actual_publication_date``. The daily watchdog flags rows where
    ``expected < today() - 7 days`` and ``actual_publication_date IS NULL``.
    """

    __tablename__ = "ref_publication_calendar"
    __table_args__ = (
        UniqueConstraint(
            "source", "category", "period_label", name="uq_publication_calendar"
        ),
        Index(
            "ix_publication_calendar_lookup",
            "source",
            "expected_publication_date",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    source: Mapped[str] = mapped_column(VARCHAR(30), nullable=False)
    category: Mapped[str] = mapped_column(VARCHAR(30), nullable=False)
    region: Mapped[Optional[str]] = mapped_column(VARCHAR(30))
    period_label: Mapped[str] = mapped_column(VARCHAR(20), nullable=False)
    period_date: Mapped[date] = mapped_column(DATE, nullable=False)
    expected_publication_date: Mapped[date] = mapped_column(DATE, nullable=False)
    tolerance_days: Mapped[int] = mapped_column(
        INTEGER, nullable=False, server_default=text("14")
    )
    actual_publication_date: Mapped[Optional[date]] = mapped_column(DATE)
    notes: Mapped[Optional[str]] = mapped_column(TEXT)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())
