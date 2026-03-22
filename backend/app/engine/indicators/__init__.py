"""Technical indicator implementations.

Each module registers one or more indicators with the registry.
Indicators are pure functions over DataFrames — no I/O, no state.
"""

from app.engine.indicators.atr import TrueRange, WilderATR
from app.engine.indicators.bollinger import BollingerBands
from app.engine.indicators.ema import EMA12, EMA26
from app.engine.indicators.macd import MACD, MACDSignal
from app.engine.indicators.pivots import PivotPoints
from app.engine.indicators.ratios import ClosePivotRatio, DailyReturn, VolumeOIRatio
from app.engine.indicators.rsi import WilderRSI
from app.engine.indicators.stochastic import StochasticD, StochasticK

ALL_INDICATORS = [
    PivotPoints(),
    EMA12(),
    EMA26(),
    MACD(),
    MACDSignal(),
    WilderRSI(),
    StochasticK(),
    StochasticD(),
    TrueRange(),
    WilderATR(),
    BollingerBands(),
    ClosePivotRatio(),
    VolumeOIRatio(),
    DailyReturn(),
]

__all__ = ["ALL_INDICATORS"]
