"""5-day SMA scoring layer.

Computes raw scores from derived indicators:
- RSI, MACD, Stochastic, ATR: 5-day SMA smoothing
- Close/Pivot: no smoothing (asymmetry preserved from original design)
- Volume/OI: 5-day SMA smoothing
"""

from __future__ import annotations

import pandas as pd

# Mapping: score column → source derived column
_SMOOTHED_SCORES = {
    "rsi_score": "rsi_14d",
    "macd_score": "macd",
    "stochastic_score": "stochastic_k_14",
    "atr_score": "atr_14d",
    "volume_oi": "volume_oi_ratio",
}

# Not smoothed — direct copy
_DIRECT_SCORES = {
    "close_pivot": "close_pivot_ratio",
}


def compute_raw_scores(df: pd.DataFrame, smoothing_window: int = 5) -> pd.DataFrame:
    """Compute raw scores from derived indicators.

    Returns a new DataFrame with score columns added.
    """
    result = df.copy()

    for score_col, source_col in _SMOOTHED_SCORES.items():
        result[score_col] = (
            result[source_col]
            .rolling(window=smoothing_window, min_periods=smoothing_window)
            .mean()
        )

    for score_col, source_col in _DIRECT_SCORES.items():
        result[score_col] = result[source_col]

    return result
