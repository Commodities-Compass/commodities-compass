"""Simple ratio indicators: Close/Pivot, Volume/OI, Daily Return."""

from __future__ import annotations

import numpy as np
import pandas as pd


class ClosePivotRatio:
    name = "close_pivot_ratio"
    outputs = ("close_pivot_ratio",)
    depends_on = ("close", "pivot")
    warmup = 0

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        result = df.copy()
        result["close_pivot_ratio"] = result["close"] / result["pivot"]
        return result


class VolumeOIRatio:
    name = "volume_oi_ratio"
    outputs = ("volume_oi_ratio",)
    depends_on = ("volume", "oi")
    warmup = 0

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        result = df.copy()
        volume = result["volume"].astype(float)
        oi = result["oi"].astype(float).replace(0, np.nan)
        result["volume_oi_ratio"] = volume / oi
        return result


class DailyReturn:
    name = "daily_return"
    outputs = ("daily_return",)
    depends_on = ("close",)
    warmup = 1

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        result = df.copy()
        close = result["close"].astype(float)
        result["daily_return"] = close.pct_change()
        return result
