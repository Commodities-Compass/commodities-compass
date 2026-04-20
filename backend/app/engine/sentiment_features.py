"""Sentiment feature computation: rolling z-score + delta.

Transforms raw per-theme sentiment scores from pl_article_segment into
normalized z-delta features for the trading engine (shadow mode).

Pipeline:
    pl_article_segment (inline_v1, zone='all')
    → group by (date, theme), avg(sentiment_score)
    → rolling z-score (window=21, min_periods=5)
    → delta = z[t] - z[t - delta_lag]
    → pl_sentiment_feature

EXP-014 validated that z-score delta is the only normalization that
preserves the Granger signal (production p=0.017, chocolat p=0.025).
"""

from __future__ import annotations

import pandas as pd

SENTIMENT_ZSCORE_WINDOW = 21
SENTIMENT_MIN_PERIODS = 5
SENTIMENT_DELTA_LAG = 3


def compute_sentiment_zdelta(
    df: pd.DataFrame,
    window: int = SENTIMENT_ZSCORE_WINDOW,
    min_periods: int = SENTIMENT_MIN_PERIODS,
    delta_lag: int = SENTIMENT_DELTA_LAG,
) -> pd.DataFrame:
    """Compute rolling z-score + delta per theme.

    Args:
        df: DataFrame with columns [date, theme, raw_score].
            Must be sorted by date within each theme.
        window: Rolling z-score window in trading days.
        min_periods: Minimum observations for a valid z-score.
        delta_lag: Number of days for the delta computation.

    Returns:
        DataFrame with columns [date, theme, raw_score, zscore,
        zscore_delta, min_periods_met]. Never mutates input.
    """
    results: list[pd.DataFrame] = []

    for theme, group in df.groupby("theme"):
        group = group.sort_values("date").copy()

        rolling_mean = (
            group["raw_score"].rolling(window=window, min_periods=min_periods).mean()
        )
        rolling_std = (
            group["raw_score"]
            .rolling(window=window, min_periods=min_periods)
            .std(ddof=1)
        )

        # Avoid division by zero
        rolling_std = rolling_std.replace(0, float("nan"))

        zscore = (group["raw_score"] - rolling_mean) / rolling_std
        zscore_delta = zscore - zscore.shift(delta_lag)
        min_periods_met = rolling_mean.notna()

        result = pd.DataFrame(
            {
                "date": group["date"],
                "theme": theme,
                "raw_score": group["raw_score"],
                "zscore": zscore,
                "zscore_delta": zscore_delta,
                "min_periods_met": min_periods_met,
            }
        )
        results.append(result)

    if not results:
        return pd.DataFrame(
            columns=[
                "date",
                "theme",
                "raw_score",
                "zscore",
                "zscore_delta",
                "min_periods_met",
            ]
        )

    return pd.concat(results, ignore_index=True)
