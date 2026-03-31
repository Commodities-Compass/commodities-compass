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
    return (
        float(row.get("rsi_norm", np.nan)),
        float(row.get("macd_norm", np.nan)),
        float(row.get("stoch_k_norm", np.nan)),
        float(row.get("atr_norm", np.nan)),
        float(row.get("close_pivot_norm", np.nan)),
        float(row.get("vol_oi_norm", np.nan)),
    )


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

    # Pass 1: base score = power formula with momentum=0
    base_score = np.full(n, np.nan)
    for idx in range(n):
        rsi, macd, stoch, atr, cp, voi = _extract_norm_inputs(result.iloc[idx])
        base_score[idx] = compute_score(
            rsi_norm=rsi,
            macd_norm=macd,
            stoch_norm=stoch,
            atr_norm=atr,
            cp_norm=cp,
            voi_norm=voi,
            momentum=0.0,
            macroeco=float(macroeco[idx]),
            config=config,
        )

    result["indicator_value"] = base_score

    # Momentum: direction change of base_score day-over-day
    momentum_values = np.full(n, np.nan)
    for idx in range(1, n):
        momentum_values[idx] = compute_momentum(
            base_score[idx], base_score[idx - 1], config.momentum_threshold
        )
    result["momentum"] = momentum_values

    # Pass 2: final score = power formula with real momentum
    final = np.full(n, np.nan)
    decisions = ["MONITOR"] * n

    for idx in range(n):
        rsi, macd, stoch, atr, cp, voi = _extract_norm_inputs(result.iloc[idx])
        mom = float(momentum_values[idx]) if not np.isnan(momentum_values[idx]) else 0.0
        score = compute_score(
            rsi_norm=rsi,
            macd_norm=macd,
            stoch_norm=stoch,
            atr_norm=atr,
            cp_norm=cp,
            voi_norm=voi,
            momentum=mom,
            macroeco=float(macroeco[idx]),
            config=config,
        )
        final[idx] = score
        decisions[idx] = compute_decision(score, config)

    result["final_indicator"] = final
    result["decision"] = decisions

    # macroeco_score = 1.0 + macroeco_bonus (computed here, not in writers)
    result["macroeco_score"] = result.get(
        macroeco_col, pd.Series(np.nan, index=result.index)
    ).apply(
        lambda v: 1.0 + v
        if not (v is None or (isinstance(v, float) and np.isnan(v)))
        else np.nan
    )

    return result
