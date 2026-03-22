"""Exponential Moving Averages (EMA12, EMA26).

Standard EMA with SMA seed for first N periods.

Formula:
    α = 2 / (period + 1)
    EMA[0..N-1] = NaN (warmup)
    EMA[N-1] = SMA(close[0:N])
    EMA[t] = close[t] × α + EMA[t-1] × (1 - α)
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _compute_ema(close: pd.Series, period: int) -> pd.Series:
    """Compute EMA with SMA seed. Returns Series with NaN during warmup."""
    values = close.to_numpy(dtype=np.float64)
    n = len(values)
    result = np.full(n, np.nan)
    alpha = 2.0 / (period + 1)

    # Find first valid window of `period` non-NaN values
    valid_count = 0
    seed_end = -1
    for idx in range(n):
        if not np.isnan(values[idx]):
            valid_count += 1
            if valid_count == period:
                seed_end = idx
                break
        else:
            valid_count = 0

    if seed_end < 0:
        return pd.Series(result, index=close.index)

    # SMA seed
    seed_start = seed_end - period + 1
    result[seed_end] = np.nanmean(values[seed_start : seed_end + 1])

    # Recursive EMA
    for idx in range(seed_end + 1, n):
        if np.isnan(values[idx]):
            result[idx] = result[idx - 1]
        else:
            result[idx] = values[idx] * alpha + result[idx - 1] * (1 - alpha)

    return pd.Series(result, index=close.index)


class EMA12:
    name = "ema12"
    outputs = ("ema12",)
    depends_on = ("close",)
    warmup = 12

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        result = df.copy()
        result["ema12"] = _compute_ema(pd.Series(result["close"]), 12)
        return result


class EMA26:
    name = "ema26"
    outputs = ("ema26",)
    depends_on = ("close",)
    warmup = 26

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        result = df.copy()
        result["ema26"] = _compute_ema(pd.Series(result["close"]), 26)
        return result
