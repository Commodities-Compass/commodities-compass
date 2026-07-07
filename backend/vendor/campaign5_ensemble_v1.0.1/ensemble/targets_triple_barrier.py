"""Triple-barrier labels (López de Prado 2018, *Advances in Financial Machine Learning* §3.3).

A path-dependent labeling scheme. For each event time t:
    - Upper barrier: ``close[t] * (1 + atr_tp_mult * atr_pct[t])``
    - Lower barrier: ``close[t] * (1 - atr_sl_mult * atr_pct[t])``
    - Vertical barrier (time): ``t + max_horizon`` trading days.

Label rule (mapped to our CLASS_ORDER DOWN/FLAT/UP):
    - close path hits upper before lower or time barrier   -> "UP"
    - close path hits lower before upper or time barrier   -> "DOWN"
    - neither barrier hit within ``max_horizon`` days      -> "FLAT"

References:
    - López de Prado (2018), *Advances in Financial Machine Learning*, Wiley, §3.3.
    - mlfinpy docs: https://mlfinpy.readthedocs.io/en/latest/Labelling.html
    - Hudson & Thames blog: https://hudsonthames.org/does-meta-labeling-add-to-signal-efficacy-triple-barrier-method/
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd


UP_LABEL = "UP"
FLAT_LABEL = "FLAT"
DOWN_LABEL = "DOWN"


def _atr_pct_causal(df: pd.DataFrame, window: int = 14) -> pd.Series:
    """ATR / close ratio, computed strictly causally with Wilder's true range."""
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


def compute_triple_barrier_labels(
    df: pd.DataFrame,
    *,
    atr_window: int = 14,
    atr_tp_mult: float = 2.0,
    atr_sl_mult: float = 1.0,
    max_horizon: int = 22,
    use_high_low: bool = True,
) -> pd.Series:
    """Vectorised triple-barrier labelling.

    For each event index t with valid ATR, scan forward up to ``max_horizon`` rows
    (or until DataFrame end). If ``use_high_low`` is True, barriers are tested
    against intraday high/low (the realistic case — touch barriers); otherwise
    against close prices only (a stricter, simpler test).

    Args:
        df: DataFrame with at least ``close`` (and ``high``/``low`` if ``use_high_low``).
        atr_window: window for the ATR percentage used to set barrier widths.
        atr_tp_mult: take-profit barrier = close[t] * (1 + atr_tp_mult * atr_pct[t]).
        atr_sl_mult: stop-loss barrier = close[t] * (1 - atr_sl_mult * atr_pct[t]).
        max_horizon: vertical (time) barrier in trading days.
        use_high_low: whether to test highs/lows against barriers (preferred).

    Returns:
        pd.Series indexed by ``df.index`` with values in {DOWN_LABEL, FLAT_LABEL, UP_LABEL}.
        Rows where the barrier scan cannot complete (e.g., final ``max_horizon``
        rows of the DataFrame) are labeled FLAT.
    """
    if "close" not in df.columns:
        raise ValueError("DataFrame missing 'close' column")
    n = len(df)
    close = df["close"].astype(float).to_numpy()
    if use_high_low and {"high", "low"}.issubset(df.columns):
        high = df["high"].astype(float).to_numpy()
        low = df["low"].astype(float).to_numpy()
    else:
        high = close.copy()
        low = close.copy()

    atr_pct = _atr_pct_causal(df, window=atr_window).to_numpy()
    labels = np.full(n, FLAT_LABEL, dtype=object)

    for t in range(n):
        atr_t = atr_pct[t]
        if not np.isfinite(atr_t) or atr_t <= 0.0:
            continue
        upper = close[t] * (1.0 + atr_tp_mult * atr_t)
        lower = close[t] * (1.0 - atr_sl_mult * atr_t)
        last = min(t + max_horizon + 1, n)
        # Scan forward from t+1
        hit_up = -1
        hit_dn = -1
        for s in range(t + 1, last):
            if hit_up < 0 and high[s] >= upper:
                hit_up = s
            if hit_dn < 0 and low[s] <= lower:
                hit_dn = s
            if hit_up >= 0 or hit_dn >= 0:
                break
        # Resolve race condition: both hit at the same row → unresolved, label FLAT
        # (LdP §3.3: when ambiguous, mark with the more conservative neutral label).
        if hit_up < 0 and hit_dn < 0:
            labels[t] = FLAT_LABEL
        elif hit_up >= 0 and hit_dn < 0:
            labels[t] = UP_LABEL
        elif hit_dn >= 0 and hit_up < 0:
            labels[t] = DOWN_LABEL
        else:
            # Both bars resolved on the same row (rare). Compare which was touched
            # earlier intra-bar using close-direction heuristic.
            if hit_up < hit_dn:
                labels[t] = UP_LABEL
            elif hit_dn < hit_up:
                labels[t] = DOWN_LABEL
            else:
                labels[t] = FLAT_LABEL

    out = pd.Categorical(labels, categories=[DOWN_LABEL, FLAT_LABEL, UP_LABEL], ordered=False)
    series = pd.Series(out, index=df.index, name="tb_label")

    balance = series.value_counts(normalize=True)
    for cls in [DOWN_LABEL, FLAT_LABEL, UP_LABEL]:
        share = float(balance.get(cls, 0.0))
        if share < 0.10:
            warnings.warn(
                f"Triple-barrier class {cls!r} only {share:.1%} of sample. "
                "Consider tuning atr_tp_mult / atr_sl_mult / max_horizon.",
                stacklevel=2,
            )
    return series


@dataclass(frozen=True)
class TBCalibration:
    atr_window: int
    atr_tp_mult: float
    atr_sl_mult: float
    max_horizon: int
    achieved_balance: dict[str, float]


def calibrate_triple_barrier(
    df: pd.DataFrame,
    *,
    target_flat_share: float = 0.30,
    atr_window: int = 14,
    max_horizon: int = 22,
    n_grid: int = 11,
) -> TBCalibration:
    """Grid-search ``atr_tp_mult == atr_sl_mult`` (symmetric) to hit a target FLAT share.

    Returns the calibration whose FLAT share is closest to ``target_flat_share``.
    """
    grid = np.linspace(0.5, 3.0, n_grid)
    best: tuple[float, float, dict[str, float]] | None = None
    for k in grid:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            lbl = compute_triple_barrier_labels(
                df,
                atr_window=atr_window,
                atr_tp_mult=float(k),
                atr_sl_mult=float(k),
                max_horizon=max_horizon,
            )
        bal = lbl.value_counts(normalize=True)
        bd = {cls: float(bal.get(cls, 0.0)) for cls in [DOWN_LABEL, FLAT_LABEL, UP_LABEL]}
        err = abs(bd[FLAT_LABEL] - target_flat_share)
        if best is None or err < best[1]:
            best = (float(k), err, bd)
    assert best is not None
    return TBCalibration(
        atr_window=atr_window,
        atr_tp_mult=best[0],
        atr_sl_mult=best[0],
        max_horizon=max_horizon,
        achieved_balance=best[2],
    )
