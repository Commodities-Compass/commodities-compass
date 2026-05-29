"""
Technical analysis data model for commodities trading.

DEPRECATED — Legacy model from pre-MVP era. No longer read by any production
code (dashboard API queries pl_* tables exclusively). The underlying table
still exists on prod for traceability; it will be dropped in a future
migration. Do NOT use in new code. See CLAUDE.md § Database Setup.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DECIMAL, INTEGER, TEXT, TIMESTAMP, VARCHAR, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Technicals(Base):
    """
    Technical analysis data for commodities trading.

    This table stores raw OHLCV data along with calculated technical indicators
    for each time period. Currently focused on cocoa (ICE contracts) with daily frequency.
    Data updated daily via Make.com automation at 8:30 PM.

    Source: TECHNICALS sheet from Excel file
    """

    __tablename__ = "technicals"

    # Primary key and timestamp
    id: Mapped[int] = mapped_column(INTEGER, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        index=True,
        comment="Date and time of the trading period (daily frequency)",
    )

    # Commodity identifier
    commodity_symbol: Mapped[str] = mapped_column(
        VARCHAR(10),
        nullable=False,
        default="CC",
        index=True,
        comment="Commodity symbol (CC for Cocoa, expandable for other commodities)",
    )

    # === CORE OHLCV DATA ===
    # Standard trading data - Open, High, Low, Close, Volume
    close: Mapped[Decimal] = mapped_column(
        DECIMAL(15, 6),
        nullable=False,
        comment="Closing price of the commodity for this period",
    )
    high: Mapped[Decimal] = mapped_column(
        DECIMAL(15, 6),
        nullable=False,
        comment="Highest price during this trading period",
    )
    low: Mapped[Decimal] = mapped_column(
        DECIMAL(15, 6),
        nullable=False,
        comment="Lowest price during this trading period",
    )
    volume: Mapped[int] = mapped_column(
        INTEGER,
        nullable=False,
        comment="Trading volume - number of contracts/units traded",
    )
    open_interest: Mapped[int] = mapped_column(
        INTEGER,
        nullable=False,
        comment="Open interest - total number of outstanding derivative contracts",
    )

    # === MARKET DATA & FUNDAMENTALS ===
    implied_volatility: Mapped[Optional[Decimal]] = mapped_column(
        DECIMAL(15, 6), comment="Implied volatility derived from options pricing"
    )
    stock_us: Mapped[Optional[Decimal]] = mapped_column(
        DECIMAL(15, 6),
        comment="US stock values regulated by ICE, available daily online, expressed in bags (x70/1000 to convert to kgs)",
    )
    com_net_us: Mapped[Optional[Decimal]] = mapped_column(
        DECIMAL(15, 6),
        comment="Net commercial positions from COT (Commitments of Traders) report - commercial long minus short positions",
    )

    # === PIVOT POINTS ===
    # Support and resistance levels calculated from previous period's OHLC
    r3: Mapped[Decimal] = mapped_column(
        DECIMAL(15, 6),
        nullable=False,
        comment="Resistance level 3 - strongest resistance",
    )
    r2: Mapped[Decimal] = mapped_column(
        DECIMAL(15, 6),
        nullable=False,
        comment="Resistance level 2 - intermediate resistance",
    )
    r1: Mapped[Decimal] = mapped_column(
        DECIMAL(15, 6),
        nullable=False,
        comment="Resistance level 1 - nearest resistance above pivot",
    )
    pivot: Mapped[Decimal] = mapped_column(
        DECIMAL(15, 6),
        nullable=False,
        comment="Central pivot point - key support/resistance level",
    )
    s1: Mapped[Decimal] = mapped_column(
        DECIMAL(15, 6),
        nullable=False,
        comment="Support level 1 - nearest support below pivot",
    )
    s2: Mapped[Decimal] = mapped_column(
        DECIMAL(15, 6), nullable=False, comment="Support level 2 - intermediate support"
    )
    s3: Mapped[Decimal] = mapped_column(
        DECIMAL(15, 6), nullable=False, comment="Support level 3 - strongest support"
    )

    # === MOVING AVERAGES & MACD ===
    ema12: Mapped[Decimal] = mapped_column(
        DECIMAL(15, 6), nullable=False, comment="12-period Exponential Moving Average"
    )
    ema26: Mapped[Decimal] = mapped_column(
        DECIMAL(15, 6), nullable=False, comment="26-period Exponential Moving Average"
    )
    macd: Mapped[Decimal] = mapped_column(
        DECIMAL(15, 6),
        nullable=False,
        comment="MACD line (EMA12 - EMA26) - trend following momentum indicator",
    )
    signal: Mapped[Optional[Decimal]] = mapped_column(
        DECIMAL(15, 6),
        comment="MACD Signal line (EMA of MACD) - generates buy/sell signals",
    )

    # === RSI & STOCHASTIC OSCILLATORS ===
    rsi_14d: Mapped[Optional[Decimal]] = mapped_column(
        DECIMAL(15, 6),
        comment="14-day Relative Strength Index (0-100) - momentum oscillator",
    )
    stochastic_k_14: Mapped[Optional[Decimal]] = mapped_column(
        DECIMAL(15, 6), comment="14-period Stochastic %K - fast stochastic oscillator"
    )
    stochastic_d_14: Mapped[Optional[Decimal]] = mapped_column(
        DECIMAL(15, 6), comment="14-period Stochastic %D - slow stochastic (SMA of %K)"
    )
    # Note: Removed duplicate 'd' field - expert confirmed it's the same as stochastic_d_14

    # === VOLATILITY MEASURES ===
    atr: Mapped[Optional[Decimal]] = mapped_column(
        DECIMAL(15, 6), comment="Average True Range - different period than ATR 14d"
    )
    atr_14d: Mapped[Optional[Decimal]] = mapped_column(
        DECIMAL(15, 6),
        comment="14-day Average True Range - calculated from formulas, converted to numerical",
    )
    volatility: Mapped[Optional[Decimal]] = mapped_column(
        DECIMAL(15, 6),
        comment="General volatility measure (calculation method needs clarification)",
    )

    # === BOLLINGER BANDS ===
    bollinger: Mapped[Decimal] = mapped_column(
        DECIMAL(15, 6),
        nullable=False,
        comment="Bollinger Band middle line (typically 20-period SMA)",
    )
    bollinger_upper: Mapped[Decimal] = mapped_column(
        DECIMAL(15, 6),
        nullable=False,
        comment="Bollinger Band upper band (middle + 2*standard deviation)",
    )
    bollinger_lower: Mapped[Decimal] = mapped_column(
        DECIMAL(15, 6),
        nullable=False,
        comment="Bollinger Band lower band (middle - 2*standard deviation)",
    )
    bollinger_width: Mapped[Decimal] = mapped_column(
        DECIMAL(15, 6),
        nullable=False,
        comment="Bollinger Band width (limites de bolinger) - difference between upper and lower bands",
    )

    # === CALCULATED RATIOS & RELATIONSHIPS ===
    close_pivot_ratio: Mapped[Optional[Decimal]] = mapped_column(
        DECIMAL(15, 6),
        comment="Ratio of close price to pivot point - position relative to pivot",
    )
    volume_oi_ratio: Mapped[Decimal] = mapped_column(
        DECIMAL(15, 6),
        nullable=False,
        comment="Volume to Open Interest ratio (Volume / Open Interest) - liquidity indicator",
    )

    # === GAIN/LOSS CALCULATIONS ===
    gain_14d: Mapped[Optional[Decimal]] = mapped_column(
        DECIMAL(15, 6),
        comment="14-day average gain - calculated from formulas, converted to numerical for RSI calculation",
    )
    loss_14d: Mapped[Optional[Decimal]] = mapped_column(
        DECIMAL(15, 6),
        comment="14-day average loss - calculated from formulas, converted to numerical for RSI calculation",
    )
    rs: Mapped[Optional[Decimal]] = mapped_column(
        DECIMAL(15, 6), comment="Relative Strength (gain/loss ratio) - component of RSI"
    )

    # === TRADING SIGNALS & DECISIONS ===
    decision: Mapped[Optional[str]] = mapped_column(
        VARCHAR(100), comment="Trading decision: OPEN, HEDGE, or MONITOR"
    )
    confidence: Mapped[Optional[Decimal]] = mapped_column(
        DECIMAL(5, 2),
        comment="Confidence level in the trading decision as percentage (0-100%)",
    )
    direction: Mapped[Optional[str]] = mapped_column(
        VARCHAR(100), comment="Expected price direction: BULLISH or BEARISH"
    )
    score: Mapped[Optional[str]] = mapped_column(
        TEXT, comment="Structured data containing composite trading score calculations"
    )
    conclusion: Mapped[Optional[Decimal]] = mapped_column(
        DECIMAL(15, 6), comment="Final numerical conclusion/score for this period"
    )

    # === METADATA ===
    row_number: Mapped[int] = mapped_column(
        INTEGER,
        nullable=False,
        comment="Original row number from Excel sheet for reference",
    )

    # === AUDIT FIELDS ===
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, server_default=func.now(), comment="Record creation timestamp"
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        server_default=func.now(),
        onupdate=func.now(),
        comment="Record last update timestamp",
    )
