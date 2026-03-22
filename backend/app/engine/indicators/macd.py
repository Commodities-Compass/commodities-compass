"""MACD (Moving Average Convergence Divergence) + Signal line.

Formula:
    MACD = EMA12 - EMA26
    Signal = EMA(9) of MACD
"""

from __future__ import annotations

import pandas as pd

from app.engine.indicators.ema import _compute_ema


class MACD:
    name = "macd"
    outputs = ("macd",)
    depends_on = ("ema12", "ema26")
    warmup = 26  # needs EMA26 to be valid

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        result = df.copy()
        result["macd"] = result["ema12"] - result["ema26"]
        return result


class MACDSignal:
    name = "macd_signal"
    outputs = ("macd_signal",)
    depends_on = ("macd",)
    warmup = 35  # 26 (EMA26 warmup) + 9 (signal warmup)

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        result = df.copy()
        result["macd_signal"] = _compute_ema(result["macd"], 9)
        return result
