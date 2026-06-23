"""Calibrated triple-barrier target.

Solves the train/test base-rate mismatch by calibrating the ATR multiplier on
the LAST ``calibration_window_months`` of the *training* slice (e.g., the most
recent 12 months before 2025-12-31) instead of the full historical record.

Why: cocoa's regime shifted post-2024-01-30 (HEDGE base rate 64.6% → ~50%) and
early-2026 was strongly bullish. Calibrating on a recent slice produces labels
whose distribution matches recent reality, not the 2016-2023 average.

Uses the existing ``compute_triple_barrier_labels`` from
``methodology.targets_triple_barrier`` — this module just wraps it with a
calibration step.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ensemble.targets_triple_barrier import (
    DOWN_LABEL,
    FLAT_LABEL,
    UP_LABEL,
    compute_triple_barrier_labels,
)


@dataclass(frozen=True)
class CalibratedTBResult:
    atr_tp_mult: float
    atr_sl_mult: float
    max_horizon: int
    calibration_window_months: int
    calibration_balance: dict[str, float]
    full_balance: dict[str, float]
    n_calibration_rows: int


def compute_calibrated_tb_labels(
    df: pd.DataFrame,
    *,
    calibration_window_months: int = 12,
    target_balance: tuple[float, float, float] = (0.33, 0.33, 0.34),
    max_horizon: int = 22,
    atr_window: int = 14,
    n_grid: int = 21,
    return_meta: bool = False,
) -> pd.Series | tuple[pd.Series, CalibratedTBResult]:
    """Triple-barrier labels with ATR multiplier calibrated on the recent slice.

    Args:
        df: DataFrame with ``date`` + OHLC.
        calibration_window_months: how many trailing months of train data drive
            the calibration. Default 12 = last year.
        target_balance: desired (DOWN, FLAT, UP) ratio on the calibration slice.
        max_horizon: vertical (time) barrier in trading days.
        atr_window: ATR window.
        n_grid: granularity of the multiplier sweep.
        return_meta: also return the CalibratedTBResult.

    Returns:
        pd.Series of TB labels aligned to ``df`` (and optionally the meta).
    """
    if "date" not in df.columns:
        raise ValueError("DataFrame missing 'date' column")
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])

    end_date = df["date"].max()
    start_calib = end_date - pd.DateOffset(months=calibration_window_months)
    calib_slice = df[df["date"] >= start_calib].reset_index(drop=True)

    if len(calib_slice) < 100:
        warnings.warn(
            f"Calibration slice has only {len(calib_slice)} rows. Falling back to atr_mult=1.0.",
            stacklevel=2,
        )
        chosen_k = 1.0
    else:
        grid = np.linspace(0.5, 3.0, n_grid)
        best: tuple[float, float, dict[str, float]] | None = None
        target_dn, target_fl, target_up = target_balance
        for k in grid:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                lbl = compute_triple_barrier_labels(
                    calib_slice,
                    atr_window=atr_window,
                    atr_tp_mult=float(k),
                    atr_sl_mult=float(k),
                    max_horizon=max_horizon,
                )
            bal = lbl.value_counts(normalize=True)
            bd = {cls: float(bal.get(cls, 0.0)) for cls in [DOWN_LABEL, FLAT_LABEL, UP_LABEL]}
            # L1 distance to target balance
            err = abs(bd[DOWN_LABEL] - target_dn) + abs(bd[FLAT_LABEL] - target_fl) + abs(bd[UP_LABEL] - target_up)
            if best is None or err < best[1]:
                best = (float(k), err, bd)
        assert best is not None
        chosen_k = best[0]
        calib_bal = best[2]

    # Apply the chosen multiplier to the WHOLE df.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        labels_full = compute_triple_barrier_labels(
            df,
            atr_window=atr_window,
            atr_tp_mult=chosen_k,
            atr_sl_mult=chosen_k,
            max_horizon=max_horizon,
        )

    full_bal = labels_full.value_counts(normalize=True)
    full_balance = {cls: float(full_bal.get(cls, 0.0)) for cls in [DOWN_LABEL, FLAT_LABEL, UP_LABEL]}
    if "calib_bal" not in dir() or len(calib_slice) < 100:
        calib_bal = full_balance  # fallback path

    meta = CalibratedTBResult(
        atr_tp_mult=chosen_k,
        atr_sl_mult=chosen_k,
        max_horizon=max_horizon,
        calibration_window_months=calibration_window_months,
        calibration_balance=calib_bal,
        full_balance=full_balance,
        n_calibration_rows=int(len(calib_slice)),
    )
    if return_meta:
        return labels_full, meta
    return labels_full
