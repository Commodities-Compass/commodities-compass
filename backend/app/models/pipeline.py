"""Pipeline tables for the MVP schema.

Raw market data, derived indicators, algorithm config, daily signals,
fundamentals, and weather. All in public schema with pl_ prefix.
Wide columns for indicators (36 columns, not EAV).
Contract-centric keying: (date, contract_id).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    DATE,
    DECIMAL,
    INTEGER,
    TEXT,
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


class PlContractDataDaily(Base):
    """Raw OHLCV + fundamentals per contract per day.

    Replaces columns A-I of the TECHNICALS Google Sheet.
    Contract-centric: keyed on (date, contract_id), not commodity.
    """

    __tablename__ = "pl_contract_data_daily"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    date: Mapped[date] = mapped_column(DATE, nullable=False)
    contract_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ref_contract.id"), nullable=False
    )

    # OHLCV
    open: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    high: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    low: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    close: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    volume: Mapped[Optional[int]] = mapped_column(INTEGER)
    oi: Mapped[Optional[int]] = mapped_column(INTEGER)

    # Additional market data
    implied_volatility: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    stock_us: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    com_net_us: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))

    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("date", "contract_id", name="uq_contract_data_daily"),
        Index("ix_contract_data_daily_date", "date"),
    )


class PlDerivedIndicators(Base):
    """Wide columns for 27+ technical indicators per contract per day.

    Replaces columns J-AT of the TECHNICALS Google Sheet.
    Mirrors the existing Technicals model indicator columns.
    """

    __tablename__ = "pl_derived_indicators"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    date: Mapped[date] = mapped_column(DATE, nullable=False)
    contract_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ref_contract.id"), nullable=False
    )

    # Pivot points
    r3: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    r2: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    r1: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    pivot: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    s1: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    s2: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    s3: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))

    # Moving averages + MACD
    ema12: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    ema26: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    macd: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    macd_signal: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))

    # RSI + Stochastic
    rsi_14d: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    stochastic_k_14: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    stochastic_d_14: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))

    # Volatility
    atr: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    atr_14d: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    volatility: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))

    # Bollinger Bands
    bollinger: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    bollinger_upper: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    bollinger_lower: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    bollinger_width: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))

    # Ratios
    close_pivot_ratio: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    volume_oi_ratio: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))

    # RSI internals
    gain_14d: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    loss_14d: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    rs: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))

    # Daily return (new — not in legacy)
    daily_return: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))

    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("date", "contract_id", name="uq_derived_indicators"),
        Index("ix_derived_indicators_date", "date"),
    )


class PlAlgorithmVersion(Base):
    """Algorithm version tracking. Today's CONFIG columns become rows here."""

    __tablename__ = "pl_algorithm_version"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(VARCHAR(100), nullable=False)
    version: Mapped[str] = mapped_column(VARCHAR(50), nullable=False)
    horizon: Mapped[str] = mapped_column(
        VARCHAR(50), nullable=False, default="short_term"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    description: Mapped[Optional[str]] = mapped_column(TEXT)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())

    __table_args__ = (UniqueConstraint("name", "version", name="uq_algorithm_version"),)


class PlAlgorithmConfig(Base):
    """Coefficients per algorithm version. Config as data, not code."""

    __tablename__ = "pl_algorithm_config"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    algorithm_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pl_algorithm_version.id"), nullable=False
    )
    parameter_name: Mapped[str] = mapped_column(VARCHAR(100), nullable=False)
    value: Mapped[str] = mapped_column(TEXT, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(TEXT)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "algorithm_version_id",
            "parameter_name",
            name="uq_algorithm_config_param",
        ),
    )


class PlIndicatorDaily(Base):
    """Z-scores, composite score, and trading decision per contract per day.

    Replaces the INDICATOR Google Sheet.
    Keyed on (date, contract_id, algorithm_version_id) to enable
    multi-version algorithm comparison.
    """

    __tablename__ = "pl_indicator_daily"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    date: Mapped[date] = mapped_column(DATE, nullable=False)
    contract_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ref_contract.id"), nullable=False
    )
    algorithm_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pl_algorithm_version.id"), nullable=False
    )

    # Raw indicator scores (-6 to +6 range)
    rsi_score: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    macd_score: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    stochastic_score: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    atr_score: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    close_pivot: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    volume_oi: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))

    # Normalized z-scores (0-1 scale)
    rsi_norm: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    macd_norm: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    stoch_k_norm: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    atr_norm: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    close_pivot_norm: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    vol_oi_norm: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))

    # Composites
    indicator_value: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    momentum: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    macroeco_bonus: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    macroeco_score: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    final_indicator: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))

    # Decision
    decision: Mapped[Optional[str]] = mapped_column(VARCHAR(50))
    confidence: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(5, 2))
    direction: Mapped[Optional[str]] = mapped_column(VARCHAR(50))
    eco: Mapped[Optional[str]] = mapped_column(TEXT)
    composite_score: Mapped[Optional[str]] = mapped_column(TEXT)

    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "date",
            "contract_id",
            "algorithm_version_id",
            name="uq_indicator_daily",
        ),
        Index("ix_indicator_daily_date", "date"),
    )


class PlFundamentalArticle(Base):
    """Press review + fundamentals. Replaces BIBLIO_ALL / market_research."""

    __tablename__ = "pl_fundamental_article"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    date: Mapped[date] = mapped_column(DATE, nullable=False, index=True)
    category: Mapped[str] = mapped_column(VARCHAR(50), nullable=False, default="macro")
    source: Mapped[Optional[str]] = mapped_column(VARCHAR(200))
    title: Mapped[Optional[str]] = mapped_column(VARCHAR(500))
    summary: Mapped[Optional[str]] = mapped_column(TEXT)
    keywords: Mapped[Optional[str]] = mapped_column(TEXT)
    sentiment: Mapped[Optional[str]] = mapped_column(VARCHAR(50))
    impact_synthesis: Mapped[Optional[str]] = mapped_column(TEXT)
    llm_provider: Mapped[Optional[str]] = mapped_column(VARCHAR(50))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())


class PlWeatherObservation(Base):
    """Weather data. Replaces METEO_ALL / weather_data."""

    __tablename__ = "pl_weather_observation"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    date: Mapped[date] = mapped_column(DATE, nullable=False, index=True)
    region: Mapped[Optional[str]] = mapped_column(VARCHAR(100))
    observation: Mapped[Optional[str]] = mapped_column(TEXT)
    summary: Mapped[Optional[str]] = mapped_column(TEXT)
    keywords: Mapped[Optional[str]] = mapped_column(TEXT)
    impact_assessment: Mapped[Optional[str]] = mapped_column(TEXT)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())
