"""Build the 12-feature vector for `today` from a trailing market panel.

The nine derived indicators are passed through from `pl_derived_indicators`
(roll-neutralized upstream). trend20 / trend60 / vol20 are computed here from the
daily-return series exactly as the freezer does — this IS the train/serve parity
guarantee for the router-derived features.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from regime.config import DERIVED_PASSTHROUGH, FEATURES


def compute_feature_row(
    market_history: pd.DataFrame,
    today: pd.Timestamp,
    *,
    trend_window: int = 20,
    confirm_window: int = 60,
    vol_window: int = 20,
) -> pd.Series:
    """Return a Series indexed by FEATURES for `today`. Raises if inputs are insufficient."""
    if "date" not in market_history.columns:
        raise ValueError("market_history must contain a 'date' column")
    df = market_history.sort_values("date").reset_index(drop=True)
    today = pd.Timestamp(today)

    missing = [c for c in DERIVED_PASSTHROUGH if c not in df.columns]
    if missing:
        raise ValueError(f"market_history missing passthrough columns: {missing}")

    r = df["daily_return"].fillna(0.0)
    idx = (1.0 + r).cumprod()
    df = df.assign(
        trend20=idx / idx.shift(trend_window) - 1.0,
        trend60=idx / idx.shift(confirm_window) - 1.0,
        vol20=r.rolling(vol_window).std() * np.sqrt(252),
    )

    row = df[df["date"] == today]
    if row.empty:
        raise ValueError(f"market_history does not include today={today.date()}")
    row = row.iloc[-1]

    feat = row[list(FEATURES)]
    if feat.isna().any():
        nan_cols = [c for c in FEATURES if pd.isna(row[c])]
        raise ValueError(
            f"feature(s) NaN for {today.date()}: {nan_cols} — need >= {confirm_window} "
            f"trailing rows and non-null derived indicators."
        )
    return feat.astype(float)
