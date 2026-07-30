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
        ret = close.pct_change()
        if "is_roll_boundary" in result.columns:
            # A front-month roll splices two contracts' closes: the day-over-day
            # change is a phantom spread, not a real move. Neutralize it to 0.
            ret = ret.mask(result["is_roll_boundary"].astype(bool), 0.0)
        result["daily_return"] = ret
        return result
