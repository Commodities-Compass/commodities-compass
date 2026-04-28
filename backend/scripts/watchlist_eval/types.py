"""Frozen dataclasses for watchlist evaluation pipeline."""

from dataclasses import dataclass
from datetime import date
from uuid import UUID


@dataclass(frozen=True)
class WatchlistItem:
    """A single parsed 'À surveiller' recommendation."""

    date: date
    contract_id: UUID
    raw_text: str
    indicator: str  # Normalized: RSI, CLOSE, OI, MACD, R1, S1, VOLUME...
    db_column: str  # Mapped DB column: rsi_14d, close, oi...
    db_table: str  # "contract_data" | "derived_indicators"
    comparator: str  # BELOW, ABOVE, CROSS_ABOVE, CROSS_BELOW, NEAR
    threshold: float | None  # None if unparseable
    implied_direction: str  # HAUSSIERE, BAISSIERE, NEUTRE
    parse_confidence: str  # HIGH, MEDIUM, LOW


@dataclass(frozen=True)
class DayData:
    """Market data snapshot for a single trading day."""

    date: date
    contract_id: UUID
    close: float
    volume: int
    oi: int
    rsi_14d: float | None
    macd: float | None
    r1: float | None
    s1: float | None
    pivot: float | None
    stochastic_k_14: float | None
    atr_14d: float | None
    bollinger_upper: float | None
    bollinger_lower: float | None
    implied_volatility: float | None
    stock_us: float | None
    com_net_us: float | None


@dataclass(frozen=True)
class EvalResult:
    """Evaluation of a single watchlist item against actual market data."""

    item: WatchlistItem
    close_on_issue: float
    # J+1
    j1_condition_hit: bool | None  # None if data missing
    j1_close: float | None
    j1_actual_value: float | None
    # J+2
    j2_condition_hit: bool | None
    j2_close: float | None
    j2_actual_value: float | None
    # J+3
    j3_condition_hit: bool | None
    j3_close: float | None
    j3_actual_value: float | None
    # Derived
    first_hit_day: int | None  # 1, 2, or 3 (None if no hit)
    direction_correct: bool | None  # At first hit: did price move in implied direction?
