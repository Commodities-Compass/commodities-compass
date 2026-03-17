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
    TIMESTAMP,
    VARCHAR,
    Boolean,
    ForeignKey,
    Index,
    UniqueConstraint,
    Uuid,
    func,
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

    __table_args__ = (
        UniqueConstraint(
            "exchange_id", "date", name="uq_trading_calendar_exchange_date"
        ),
        Index("ix_trading_calendar_date", "date"),
    )
