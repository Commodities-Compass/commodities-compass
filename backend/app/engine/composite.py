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

Momentum:
    Two-pass computation to avoid circularity:
    1. base_score = power formula with momentum=0 (6 indicators + macroeco)
    2. momentum[N] = direction(base_score[N] vs base_score[N-1]) → ±threshold
    3. final_indicator = power formula with real momentum (all 8 inputs)
"""

from __future__ import annotations

import logging
import math

import numpy as np
import pandas as pd

from app.engine.types import AlgorithmConfig

logger = logging.getLogger(__name__)


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


def compute_momentum(
    score_today: float,
    score_yesterday: float,
    threshold: float = 0.2,
) -> float:
    """Binary momentum: +threshold if score increased, -threshold otherwise.

    Compares power formula base scores (without momentum) day-over-day.
    """
    if math.isnan(score_today) or math.isnan(score_yesterday):
        return 0.0
    return threshold if score_today > score_yesterday else -threshold


def _extract_norm_inputs(
    row: pd.Series,
) -> tuple[float, float, float, float, float, float]:
    """Extract the 6 normalized indicator values from a DataFrame row."""

    def _val(key: str) -> float:
        v = row.get(key)
        return float(v) if v is not None else float(np.nan)

    return (
        _val("rsi_norm"),
        _val("macd_norm"),
        _val("stoch_k_norm"),
        _val("atr_norm"),
        _val("close_pivot_norm"),
        _val("vol_oi_norm"),
    )


def _vectorized_power_term(coeff: float, exp: float, arr: np.ndarray) -> np.ndarray:
    """Vectorized version of _power_term for numpy arrays."""
    sign = np.sign(arr)
    result = coeff * sign * np.abs(arr) ** exp
    result = np.where(np.isnan(arr) | (arr == 0.0), 0.0, result)
    return result


def _vectorized_score(
    rsi: np.ndarray,
    macd: np.ndarray,
    stoch: np.ndarray,
    atr: np.ndarray,
    cp: np.ndarray,
    voi: np.ndarray,
    momentum: np.ndarray,
    macroeco: np.ndarray,
    config: AlgorithmConfig,
) -> np.ndarray:
    """Vectorized composite score computation."""
    return (
        config.k
        + _vectorized_power_term(config.a, config.b, rsi)
        + _vectorized_power_term(config.c, config.d, macd)
        + _vectorized_power_term(config.e, config.f, stoch)
        + _vectorized_power_term(config.g, config.h, atr)
        + _vectorized_power_term(config.i, config.j, cp)
        + _vectorized_power_term(config.l, config.m, voi)
        + _vectorized_power_term(config.n, config.o, momentum)
        + _vectorized_power_term(config.p, config.q, macroeco)
    )


def _vectorized_decision(scores: np.ndarray, config: AlgorithmConfig) -> list[str]:
    """Vectorized decision mapping."""
    decisions = np.where(
        np.isnan(scores),
        "MONITOR",
        np.where(
            scores >= config.open_threshold,
            "OPEN",
            np.where(scores <= config.hedge_threshold, "HEDGE", "MONITOR"),
        ),
    )
    return decisions.tolist()


def compute_signals(
    df: pd.DataFrame,
    config: AlgorithmConfig,
    macroeco_col: str = "macroeco_bonus",
) -> pd.DataFrame:
    """Compute composite scores, momentum, and decisions for all rows.

    Two-pass approach (no circularity):
        Pass 1: base_score = power formula with momentum=0
        Momentum: direction(base_score[N] vs base_score[N-1]) → ±threshold
        Pass 2: final_indicator = power formula with real momentum

    Returns new DataFrame with added columns:
        indicator_value (base score), momentum, final_indicator, decision
    """
    result = df.copy()
    n = len(result)

    # Get macroeco values — warn explicitly if missing
    if macroeco_col in result.columns:
        nan_count = result[macroeco_col].isna().sum()
        if nan_count > 0:
            logger.warning(
                "%s has %d/%d NaN values — treated as 0.0 for composite scoring",
                macroeco_col,
                nan_count,
                n,
            )
        macroeco = result[macroeco_col].fillna(0.0).to_numpy(dtype=np.float64)
    else:
        logger.warning(
            "Column '%s' not found in DataFrame — all macroeco contributions will be 0.0. "
            "Check that the daily-analysis agent ran before compute-indicators.",
            macroeco_col,
        )
        macroeco = np.zeros(n)

    # Extract the 6 normalized indicator columns as numpy arrays
    def _col(name: str) -> np.ndarray:  # type: ignore[type-arg]
        if name in result.columns:
            return np.asarray(
                pd.to_numeric(result[name], errors="coerce"), dtype=np.float64
            )
        return np.full(n, np.nan)

    rsi = _col("rsi_norm")
    macd_arr = _col("macd_norm")
    stoch = _col("stoch_k_norm")
    atr = _col("atr_norm")
    cp = _col("close_pivot_norm")
    voi = _col("vol_oi_norm")

    # Pass 1: base score = power formula with momentum=0
    zero_momentum = np.zeros(n)
    base_score = _vectorized_score(
        rsi, macd_arr, stoch, atr, cp, voi, zero_momentum, macroeco, config
    )
    result["indicator_value"] = base_score

    # Momentum: direction change of base_score day-over-day
    momentum_values = np.full(n, np.nan)
    shifted = np.roll(base_score, 1)
    shifted[0] = np.nan
    valid = ~np.isnan(base_score) & ~np.isnan(shifted)
    momentum_values[valid] = np.where(
        base_score[valid] > shifted[valid],
        config.momentum_threshold,
        -config.momentum_threshold,
    )
    result["momentum"] = momentum_values

    # Pass 2: final score = power formula with real momentum
    mom_for_score = np.where(np.isnan(momentum_values), 0.0, momentum_values)
    final = _vectorized_score(
        rsi, macd_arr, stoch, atr, cp, voi, mom_for_score, macroeco, config
    )
    result["final_indicator"] = final
    result["decision"] = _vectorized_decision(final, config)

    # macroeco_score = 1.0 + macroeco_bonus (computed here, not in writers)
    if macroeco_col in result.columns:
        bonus = pd.to_numeric(result[macroeco_col], errors="coerce")
        result["macroeco_score"] = pd.Series(bonus, dtype="float64") + 1.0
    else:
        result["macroeco_score"] = np.nan

    return result
