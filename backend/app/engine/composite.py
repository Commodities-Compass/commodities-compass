"""NEW CHAMPION power formula composite scoring.

Formula:
    SCORE = k + Σ (coefficient × sign(input) × |input|^exponent)

    8 input pairs:
        RSI, MACD, Stochastic, ATR, Close/Pivot, Vol/OI, Momentum, Macroeco

Decision thresholds:
    SCORE ≥ open_threshold  → "OPEN"
    SCORE ≤ hedge_threshold → "HEDGE"
    otherwise               → "MONITOR"

Note: Labels are CORRECT here (fix vs Sheets which swapped MONITOR/HEDGE).
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from app.engine.types import AlgorithmConfig


def _power_term(coefficient: float, exponent: float, value: float) -> float:
    """Compute: coefficient × sign(value) × |value|^exponent."""
    if math.isnan(value) or value == 0.0:
        return 0.0
    sign = 1.0 if value > 0 else -1.0
    return coefficient * sign * abs(value) ** exponent


def compute_score(
    rsi_norm: float,
    macd_norm: float,
    stoch_norm: float,
    atr_norm: float,
    cp_norm: float,
    voi_norm: float,
    momentum: float,
    macroeco: float,
    config: AlgorithmConfig,
) -> float:
    """Compute composite score from normalized inputs + algorithm config.

    Pure function, no side effects.
    """
    return (
        config.k
        + _power_term(config.a, config.b, rsi_norm)
        + _power_term(config.c, config.d, macd_norm)
        + _power_term(config.e, config.f, stoch_norm)
        + _power_term(config.g, config.h, atr_norm)
        + _power_term(config.i, config.j, cp_norm)
        + _power_term(config.l, config.m, voi_norm)
        + _power_term(config.n, config.o, momentum)
        + _power_term(config.p, config.q, macroeco)
    )


def compute_decision(score: float, config: AlgorithmConfig) -> str:
    """Map composite score to trading decision."""
    if math.isnan(score):
        return "MONITOR"
    if score >= config.open_threshold:
        return "OPEN"
    if score <= config.hedge_threshold:
        return "HEDGE"
    return "MONITOR"


def compute_momentum(linear_today: float, linear_yesterday: float) -> float:
    """Binary momentum: +0.2 if linear increased, -0.2 otherwise.

    Matches current production behavior. Can be swapped for
    continuous momentum in future algorithm versions.
    """
    if math.isnan(linear_today) or math.isnan(linear_yesterday):
        return 0.0
    return 0.2 if linear_today > linear_yesterday else -0.2


def compute_linear_indicator(
    rsi_norm: float,
    macd_norm: float,
    stoch_norm: float,
    atr_norm: float,
    cp_norm: float,
    voi_norm: float,
) -> float:
    """Linear formula used only as input to MOMENTUM calculation.

    Not used for decisions — only to determine momentum direction.
    Coefficients are the original hardcoded weights from INDICATOR!N.
    """
    return (
        -0.79 * rsi_norm
        + 0.49 * macd_norm
        - 1.16 * stoch_norm
        - 0.11 * atr_norm
        - 0.82 * cp_norm
        - 0.52 * voi_norm
        + 0.519
    )


def compute_signals(
    df: pd.DataFrame,
    config: AlgorithmConfig,
    macroeco_col: str = "macroeco_bonus",
) -> pd.DataFrame:
    """Compute composite scores, momentum, and decisions for all rows.

    Expects DataFrame with norm columns (rsi_norm, macd_norm, etc.)
    and optionally a macroeco_bonus column.

    Returns new DataFrame with added columns:
        indicator_value, momentum, final_indicator, decision
    """
    result = df.copy()
    n = len(result)

    # Compute linear indicator for momentum calculation
    linear = np.full(n, np.nan)
    for idx in range(n):
        row = result.iloc[idx]
        linear[idx] = compute_linear_indicator(
            rsi_norm=float(row.get("rsi_norm", np.nan)),
            macd_norm=float(row.get("macd_norm", np.nan)),
            stoch_norm=float(row.get("stoch_k_norm", np.nan)),
            atr_norm=float(row.get("atr_norm", np.nan)),
            cp_norm=float(row.get("close_pivot_norm", np.nan)),
            voi_norm=float(row.get("vol_oi_norm", np.nan)),
        )

    result["indicator_value"] = linear

    # Compute momentum (binary ±0.2)
    momentum_values = np.full(n, np.nan)
    for idx in range(1, n):
        momentum_values[idx] = compute_momentum(linear[idx], linear[idx - 1])
    result["momentum"] = momentum_values

    # Get macroeco values (default 0 if not present)
    if macroeco_col in result.columns:
        macroeco = result[macroeco_col].fillna(0.0).to_numpy(dtype=np.float64)
    else:
        macroeco = np.zeros(n)

    # Compute final composite score and decision
    final = np.full(n, np.nan)
    decisions = ["MONITOR"] * n

    for idx in range(n):
        row = result.iloc[idx]
        score = compute_score(
            rsi_norm=float(row.get("rsi_norm", np.nan)),
            macd_norm=float(row.get("macd_norm", np.nan)),
            stoch_norm=float(row.get("stoch_k_norm", np.nan)),
            atr_norm=float(row.get("atr_norm", np.nan)),
            cp_norm=float(row.get("close_pivot_norm", np.nan)),
            voi_norm=float(row.get("vol_oi_norm", np.nan)),
            momentum=float(momentum_values[idx])
            if not np.isnan(momentum_values[idx])
            else 0.0,
            macroeco=float(macroeco[idx]),
            config=config,
        )
        final[idx] = score
        decisions[idx] = compute_decision(score, config)

    result["final_indicator"] = final
    result["decision"] = decisions

    return result
