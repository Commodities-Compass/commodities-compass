"""Stochastic Oscillator (%K, %D).

Fix vs Sheets: Sheets excluded today's H/L and could go negative.
This implementation includes today's H/L and clamps to 0-100.

Formula:
    %K = 100 × (Close - Low14) / (High14 - Low14)
        where Low14 = min(Low over last 14 periods including today)
              High14 = max(High over last 14 periods including today)
        Clamped to [0, 100].

    %D = SMA(3) of %K
"""

from __future__ import annotations

import numpy as np
import pandas as pd

STOCH_PERIOD = 14
STOCH_D_PERIOD = 3


class StochasticK:
    name = "stochastic_k"
    outputs = ("stochastic_k_14",)
    depends_on = ("close", "high", "low")
    warmup = STOCH_PERIOD

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        result = df.copy()
        close = result["close"].to_numpy(dtype=np.float64)
        high = result["high"].to_numpy(dtype=np.float64)
        low = result["low"].to_numpy(dtype=np.float64)
        n = len(close)

        k_values = np.full(n, np.nan)

        for idx in range(STOCH_PERIOD - 1, n):
            window_start = idx - STOCH_PERIOD + 1
            high_max = np.nanmax(high[window_start : idx + 1])
            low_min = np.nanmin(low[window_start : idx + 1])

            if high_max == low_min:
                k_values[idx] = 50.0  # midpoint when range is zero
            else:
                raw_k = 100.0 * (close[idx] - low_min) / (high_max - low_min)
                k_values[idx] = float(np.clip(raw_k, 0.0, 100.0))

        result["stochastic_k_14"] = k_values
        return result


class StochasticD:
    name = "stochastic_d"
    outputs = ("stochastic_d_14",)
    depends_on = ("stochastic_k_14",)
    warmup = STOCH_PERIOD + STOCH_D_PERIOD - 1

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        result = df.copy()
        k = result["stochastic_k_14"]
        result["stochastic_d_14"] = k.rolling(
            window=STOCH_D_PERIOD, min_periods=STOCH_D_PERIOD
        ).mean()
        return result
