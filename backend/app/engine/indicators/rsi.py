"""RSI — Relative Strength Index with Wilder's smoothing.

Fix vs Sheets: Sheets used SMA (SUM/14) with off-by-one (13 values / 14).
This implementation uses standard Wilder's exponential smoothing with
correct 14-period window.

Formula:
    Δ = close[t] - close[t-1]
    gain = max(Δ, 0)
    loss = abs(min(Δ, 0))

    First 14 periods:
        avg_gain = SMA(gain[1:15])  (14 values)
        avg_loss = SMA(loss[1:15])

    Subsequent:
        avg_gain = (prev_avg_gain × 13 + gain) / 14
        avg_loss = (prev_avg_loss × 13 + loss) / 14

    RS = avg_gain / avg_loss
    RSI = 100 - 100 / (1 + RS)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

RSI_PERIOD = 14


class WilderRSI:
    name = "wilder_rsi"
    outputs = ("rsi_14d", "gain_14d", "loss_14d", "rs")
    depends_on = ("close",)
    warmup = RSI_PERIOD + 1  # need 14 deltas → 15 close values

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        result = df.copy()
        close = result["close"].to_numpy(dtype=np.float64)
        n = len(close)

        rsi = np.full(n, np.nan)
        gain_out = np.full(n, np.nan)
        loss_out = np.full(n, np.nan)
        rs_out = np.full(n, np.nan)

        # Daily changes
        deltas = np.diff(close, prepend=np.nan)
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)

        # Find first valid stretch of RSI_PERIOD+1 non-NaN closes
        first_valid = -1
        valid_count = 0
        for idx in range(n):
            if not np.isnan(close[idx]):
                valid_count += 1
                if valid_count == RSI_PERIOD + 1:
                    first_valid = idx
                    break
            else:
                valid_count = 0

        if first_valid < 0:
            for col_name, arr in [
                ("rsi_14d", rsi),
                ("gain_14d", gain_out),
                ("loss_14d", loss_out),
                ("rs", rs_out),
            ]:
                result[col_name] = arr
            return result

        # SMA seed over first 14 deltas
        seed_start = first_valid - RSI_PERIOD + 1
        avg_gain = np.nanmean(gains[seed_start : first_valid + 1])
        avg_loss = np.nanmean(losses[seed_start : first_valid + 1])

        gain_out[first_valid] = avg_gain
        loss_out[first_valid] = avg_loss

        if avg_loss == 0:
            rs_val = 999.0
        else:
            rs_val = avg_gain / avg_loss

        rs_out[first_valid] = rs_val
        rsi[first_valid] = 100.0 - 100.0 / (1.0 + rs_val)

        # Wilder's smoothing
        for idx in range(first_valid + 1, n):
            if np.isnan(close[idx]):
                continue
            avg_gain = (avg_gain * (RSI_PERIOD - 1) + gains[idx]) / RSI_PERIOD
            avg_loss = (avg_loss * (RSI_PERIOD - 1) + losses[idx]) / RSI_PERIOD

            gain_out[idx] = avg_gain
            loss_out[idx] = avg_loss

            if avg_loss == 0:
                rs_val = 999.0
            else:
                rs_val = avg_gain / avg_loss

            rs_out[idx] = rs_val
            rsi[idx] = 100.0 - 100.0 / (1.0 + rs_val)

        result["rsi_14d"] = rsi
        result["gain_14d"] = gain_out
        result["loss_14d"] = loss_out
        result["rs"] = rs_out

        return result
