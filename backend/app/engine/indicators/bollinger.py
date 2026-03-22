"""Bollinger Bands — symmetric SMA(20) ± 2×STDEV(20).

Fix vs Sheets: Sheets had asymmetric windows (STDEVP vs STDEV,
~232 rows vs 20 rows, middle band collapsed to Close on last rows).
This implementation uses standard symmetric rolling 20-period.

Formula:
    Middle = SMA(20) of Close
    StdDev = sample STDEV(20) of Close
    Upper = Middle + 2 × StdDev
    Lower = Middle - 2 × StdDev
    Width = (Upper - Lower) / Middle
"""

from __future__ import annotations

import pandas as pd

BOLLINGER_PERIOD = 20
BOLLINGER_STD_MULT = 2


class BollingerBands:
    name = "bollinger_bands"
    outputs = ("bollinger", "bollinger_upper", "bollinger_lower", "bollinger_width")
    depends_on = ("close",)
    warmup = BOLLINGER_PERIOD

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        result = df.copy()
        close = result["close"]

        middle = close.rolling(
            window=BOLLINGER_PERIOD, min_periods=BOLLINGER_PERIOD
        ).mean()
        std = close.rolling(window=BOLLINGER_PERIOD, min_periods=BOLLINGER_PERIOD).std(
            ddof=1
        )

        upper = middle + BOLLINGER_STD_MULT * std
        lower = middle - BOLLINGER_STD_MULT * std

        result["bollinger"] = middle
        result["bollinger_upper"] = upper
        result["bollinger_lower"] = lower
        result["bollinger_width"] = (upper - lower) / middle

        return result
