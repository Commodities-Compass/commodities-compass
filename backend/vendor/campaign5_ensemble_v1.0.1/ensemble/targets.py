"""3-class target encoding using ATR-calibrated thresholds (causal).

Spec: methodology/framework-spec.md §4.2.

Public API:
    compute_3class_target(df, horizon, threshold_method, atr_window, atr_multiple) -> Series
    calibrate_thresholds(df, target_class_balance) -> dict
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd


UP_LABEL = "UP"
FLAT_LABEL = "FLAT"
DOWN_LABEL = "DOWN"


def _rolling_atr_pct(df: pd.DataFrame, window: int = 14) -> pd.Series:
    """Causal rolling ATR expressed as percentage of close (so it matches forward_return scale).

    Uses Wilder true range: max(high-low, |high-prev_close|, |low-prev_close|).
    Rolling mean over `window` days, divided by close.
    """
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    atr = tr.rolling(window, min_periods=window).mean()
    return (atr / close).rename(f"atr_pct_{window}d")


def compute_3class_target(
    df: pd.DataFrame,
    horizon: int = 6,
    threshold_method: str = "atr_multiple",
    atr_window: int = 14,
    atr_multiple: float = 0.5,
    fixed_threshold: float | None = None,
    forward_return_col: str | None = None,
) -> pd.Series:
    """Map forward return into UP / FLAT / DOWN labels.

    Args:
        df: must contain ``close`` and ``forward_return_<horizon>d`` (or ``forward_return_col``).
        threshold_method: 'atr_multiple' | 'quantile' | 'fixed'.
        atr_window: window for ATR (used when method='atr_multiple').
        atr_multiple: k such that UP if return > k*ATR%, DOWN if return < -k*ATR%, else FLAT.
        fixed_threshold: used when method='fixed' (absolute return threshold).
        forward_return_col: column name for forward return; defaults to f'forward_return_{horizon}d'.

    Returns:
        pd.Series of dtype 'category' with ordered categories [DOWN, FLAT, UP].
    """
    fwd_col = forward_return_col or f"forward_return_{horizon}d"
    if fwd_col not in df.columns:
        raise ValueError(f"Column {fwd_col} not in DataFrame")
    fwd = df[fwd_col].astype(float)

    if threshold_method == "atr_multiple":
        atr_pct = _rolling_atr_pct(df, window=atr_window)
        # NOTE: ATR series can be NaN for first atr_window rows. Anywhere ATR is NaN,
        # we conservatively fall back to a small absolute threshold so the label is well-defined.
        threshold = (atr_pct * atr_multiple).fillna(0.0)
        labels = np.where(
            fwd > threshold,
            UP_LABEL,
            np.where(fwd < -threshold, DOWN_LABEL, FLAT_LABEL),
        )
    elif threshold_method == "fixed":
        if fixed_threshold is None:
            raise ValueError("fixed_threshold required for method='fixed'")
        labels = np.where(
            fwd > fixed_threshold,
            UP_LABEL,
            np.where(fwd < -fixed_threshold, DOWN_LABEL, FLAT_LABEL),
        )
    elif threshold_method == "quantile":
        lo, hi = fwd.quantile(0.35), fwd.quantile(0.65)
        labels = np.where(
            fwd > hi,
            UP_LABEL,
            np.where(fwd < lo, DOWN_LABEL, FLAT_LABEL),
        )
    else:
        raise ValueError(f"Unknown threshold_method: {threshold_method}")

    out = pd.Categorical(labels, categories=[DOWN_LABEL, FLAT_LABEL, UP_LABEL], ordered=False)
    series = pd.Series(out, index=df.index, name=f"target_3class_h{horizon}")

    balance = series.value_counts(normalize=True)
    for cls in [DOWN_LABEL, FLAT_LABEL, UP_LABEL]:
        share = float(balance.get(cls, 0.0))
        if share < 0.15:
            warnings.warn(
                f"Class {cls!r} only {share:.1%} of sample (< 15%). Consider re-calibrating threshold.",
                stacklevel=2,
            )
    return series


@dataclass(frozen=True)
class ThresholdCalibration:
    method: str
    atr_window: int
    atr_multiple: float
    achieved_balance: dict[str, float]
    target_balance: tuple[float, float, float]


def calibrate_thresholds(
    df: pd.DataFrame,
    horizon: int = 6,
    target_class_balance: tuple[float, float, float] = (0.35, 0.30, 0.35),
    atr_window: int = 14,
    *,
    n_grid: int = 41,
) -> ThresholdCalibration:
    """Binary-grid-search `atr_multiple` to hit `target_class_balance` (DOWN, FLAT, UP) within ±5pp."""
    if not (abs(sum(target_class_balance) - 1.0) < 1e-6):
        raise ValueError(f"target_class_balance must sum to 1.0, got {target_class_balance}")

    grid = np.linspace(0.05, 2.0, n_grid)
    target_flat = target_class_balance[1]
    best: tuple[float, float, dict[str, float]] | None = None
    for k in grid:
        labels = compute_3class_target(
            df,
            horizon=horizon,
            threshold_method="atr_multiple",
            atr_window=atr_window,
            atr_multiple=float(k),
        )
        balance = labels.value_counts(normalize=True)
        balance_dict = {cls: float(balance.get(cls, 0.0)) for cls in [DOWN_LABEL, FLAT_LABEL, UP_LABEL]}
        err = abs(balance_dict[FLAT_LABEL] - target_flat)
        if best is None or err < best[1]:
            best = (float(k), err, balance_dict)

    assert best is not None
    return ThresholdCalibration(
        method="atr_multiple",
        atr_window=atr_window,
        atr_multiple=best[0],
        achieved_balance=best[2],
        target_balance=target_class_balance,
    )
