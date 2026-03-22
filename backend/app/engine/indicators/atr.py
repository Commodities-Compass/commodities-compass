"""Average True Range (ATR) with Wilder's smoothing.

Fix vs Sheets: Sheets used EMA alpha=2/15. This uses Wilder's alpha=1/14.

Formula:
    True Range = max(High-Low, |High-Close_prev|, |Low-Close_prev|)

    First ATR = SMA(TR[0:14])
    ATR[t] = (ATR[t-1] × 13 + TR[t]) / 14
"""

from __future__ import annotations

import numpy as np
import pandas as pd

ATR_PERIOD = 14


class TrueRange:
    name = "true_range"
    outputs = ("atr",)  # named 'atr' in schema but holds True Range
    depends_on = ("high", "low", "close")
    warmup = 1  # need previous close

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        result = df.copy()
        high = result["high"].to_numpy(dtype=np.float64)
        low = result["low"].to_numpy(dtype=np.float64)
        close = result["close"].to_numpy(dtype=np.float64)
        n = len(close)

        tr = np.full(n, np.nan)
        # First row: TR = High - Low (no previous close)
        tr[0] = high[0] - low[0]

        for idx in range(1, n):
            if np.isnan(high[idx]) or np.isnan(low[idx]) or np.isnan(close[idx - 1]):
                continue
            tr[idx] = max(
                high[idx] - low[idx],
                abs(high[idx] - close[idx - 1]),
                abs(low[idx] - close[idx - 1]),
            )

        result["atr"] = tr
        return result


class WilderATR:
    name = "wilder_atr"
    outputs = ("atr_14d",)
    depends_on = ("atr",)  # depends on True Range column
    warmup = ATR_PERIOD

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        result = df.copy()
        tr = result["atr"].to_numpy(dtype=np.float64)
        n = len(tr)

        atr_values = np.full(n, np.nan)

        # Find first window of ATR_PERIOD valid TR values
        valid_count = 0
        seed_end = -1
        for idx in range(n):
            if not np.isnan(tr[idx]):
                valid_count += 1
                if valid_count == ATR_PERIOD:
                    seed_end = idx
                    break
            else:
                valid_count = 0

        if seed_end < 0:
            result["atr_14d"] = atr_values
            return result

        # SMA seed
        seed_start = seed_end - ATR_PERIOD + 1
        atr_val = np.nanmean(tr[seed_start : seed_end + 1])
        atr_values[seed_end] = atr_val

        # Wilder's smoothing: ATR = (prev × 13 + TR) / 14
        for idx in range(seed_end + 1, n):
            if np.isnan(tr[idx]):
                atr_values[idx] = atr_val
            else:
                atr_val = (atr_val * (ATR_PERIOD - 1) + tr[idx]) / ATR_PERIOD
                atr_values[idx] = atr_val

        result["atr_14d"] = atr_values
        return result
