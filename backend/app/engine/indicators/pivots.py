"""Standard classical pivot points.

Fix vs Sheets: Sheets used 1.1x multiplier and anchored R/S on Close.
This implementation uses the standard formula anchored on Pivot.

Formula:
    Pivot = (High + Low + Close) / 3
    R1 = 2×Pivot - Low
    R2 = Pivot + (High - Low)
    R3 = High + 2×(Pivot - Low)
    S1 = 2×Pivot - High
    S2 = Pivot - (High - Low)
    S3 = Low - 2×(High - Pivot)
"""

from __future__ import annotations

import pandas as pd


class PivotPoints:
    name = "pivot_points"
    outputs = ("pivot", "r1", "r2", "r3", "s1", "s2", "s3")
    depends_on = ("high", "low", "close")
    warmup = 0

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        result = df.copy()
        h, low, c = result["high"], result["low"], result["close"]

        pivot = (h + low + c) / 3
        result["pivot"] = pivot
        result["r1"] = 2 * pivot - low
        result["r2"] = pivot + (h - low)
        result["r3"] = h + 2 * (pivot - low)
        result["s1"] = 2 * pivot - h
        result["s2"] = pivot - (h - low)
        result["s3"] = low - 2 * (h - pivot)

        return result
