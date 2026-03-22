"""Rolling z-score normalization.

Fix vs Sheets: Sheets used full-history AVERAGE(B:B)/STDEV(B:B),
creating look-ahead bias. This uses a rolling 252-day window.

Formula:
    z = (x - mean(x, window)) / std(x, window)

Outlier handling:
    If |z| > cap, clip to ±cap (preserves direction, caps magnitude).
"""

from __future__ import annotations

import pandas as pd

from app.engine.types import NORM_COLS, SCORE_COLS

DEFAULT_WINDOW = 252  # ~1 trading year
DEFAULT_OUTLIER_CAP = 10.0

# Mapping: score column → normalized column
_SCORE_TO_NORM = dict(zip(SCORE_COLS, NORM_COLS, strict=True))


def rolling_zscore(
    series: pd.Series,
    window: int = DEFAULT_WINDOW,
    outlier_cap: float = DEFAULT_OUTLIER_CAP,
) -> pd.Series:
    """Compute rolling z-score with outlier clipping.

    Returns new Series — never mutates input.
    """
    rolling_mean = series.rolling(
        window=window, min_periods=max(window // 2, 20)
    ).mean()
    rolling_std = series.rolling(window=window, min_periods=max(window // 2, 20)).std(
        ddof=1
    )

    # Avoid division by zero
    rolling_std = rolling_std.replace(0, float("nan"))

    z = (series - rolling_mean) / rolling_std

    # Clip outliers
    return z.clip(lower=-outlier_cap, upper=outlier_cap)


def normalize_scores(
    df: pd.DataFrame,
    window: int = DEFAULT_WINDOW,
    outlier_cap: float = DEFAULT_OUTLIER_CAP,
) -> pd.DataFrame:
    """Normalize all score columns to z-scores.

    Returns new DataFrame with norm columns added.
    """
    result = df.copy()

    for score_col, norm_col in _SCORE_TO_NORM.items():
        result[norm_col] = rolling_zscore(
            result[score_col], window=window, outlier_cap=outlier_cap
        )

    return result
