"""Immutable data containers for the computation engine.

All types are frozen dataclasses — no mutation allowed.
The engine operates on pandas DataFrames internally but uses
these types for configuration and results at boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AlgorithmConfig:
    """Power formula parameters loaded from pl_algorithm_config.

    NEW CHAMPION production params (CONFIG col G).
    All 8 indicator pairs (coefficient + exponent) plus thresholds.
    """

    version_name: str
    k: float  # constant offset

    # RSI
    a: float  # coefficient
    b: float  # exponent

    # MACD
    c: float
    d: float

    # Stochastic
    e: float
    f: float

    # ATR
    g: float
    h: float

    # Close/Pivot
    i: float
    j: float

    # Volume/OI
    l: float  # noqa: E741 — matching CONFIG param naming
    m: float

    # Momentum
    n: float
    o: float

    # Macroeco
    p: float
    q: float

    # Decision thresholds
    open_threshold: float
    hedge_threshold: float

    @staticmethod
    def from_db_rows(version_name: str, params: dict[str, str]) -> AlgorithmConfig:
        """Build from pl_algorithm_config rows (parameter_name → value)."""
        return AlgorithmConfig(
            version_name=version_name,
            k=float(params["k"]),
            a=float(params["a"]),
            b=float(params["b"]),
            c=float(params["c"]),
            d=float(params["d"]),
            e=float(params["e"]),
            f=float(params["f"]),
            g=float(params["g"]),
            h=float(params["h"]),
            i=float(params["i"]),
            j=float(params["j"]),
            l=float(params["l"]),
            m=float(params["m"]),
            n=float(params["n"]),
            o=float(params["o"]),
            p=float(params["p"]),
            q=float(params["q"]),
            open_threshold=float(params["open_threshold"]),
            hedge_threshold=float(params["hedge_threshold"]),
        )


# Legacy v1.0.0 production params (CONFIG col G) — hardcoded as fallback only.
# In production, always load from pl_algorithm_config.
LEGACY_V1 = AlgorithmConfig(
    version_name="legacy_v1.0.0",
    k=-1.2,
    a=-1.3,
    b=1.8,
    c=0.5,
    d=0.7,
    e=-2.5,
    f=1.0,
    g=1.204,
    h=0.5,
    i=-0.4,
    j=1.751,
    l=4.98,
    m=1.2,
    n=-1.3,
    o=0.515,
    p=-0.5,
    q=1.98,
    open_threshold=1.5,
    hedge_threshold=-1.5,
)

# Standard column names used across the engine.
# Raw market data columns (input).
RAW_COLS = [
    "date",
    "close",
    "high",
    "low",
    "volume",
    "oi",
    "implied_volatility",
    "stock_us",
    "com_net_us",
]

# Derived indicator columns (output of indicators/).
DERIVED_COLS = [
    "pivot",
    "r1",
    "r2",
    "r3",
    "s1",
    "s2",
    "s3",
    "ema12",
    "ema26",
    "macd",
    "macd_signal",
    "rsi_14d",
    "gain_14d",
    "loss_14d",
    "rs",
    "stochastic_k_14",
    "stochastic_d_14",
    "atr",  # true range
    "atr_14d",
    "bollinger",  # middle band
    "bollinger_upper",
    "bollinger_lower",
    "bollinger_width",
    "close_pivot_ratio",
    "volume_oi_ratio",
    "daily_return",
]

# Score columns (output of smoothing layer, input to normalization).
SCORE_COLS = [
    "rsi_score",
    "macd_score",
    "stochastic_score",
    "atr_score",
    "close_pivot",
    "volume_oi",
]

# Normalized z-score columns (output of normalization).
NORM_COLS = [
    "rsi_norm",
    "macd_norm",
    "stoch_k_norm",
    "atr_norm",
    "close_pivot_norm",
    "vol_oi_norm",
]
