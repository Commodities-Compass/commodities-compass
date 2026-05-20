"""Anti-bias sample / class weights for retraining.

Two ingredients that compose multiplicatively into a single sample_weight array:

1. **Balanced class weights** (sklearn-style inverse frequency):
   w[c] = n_total / (k_classes * count[c]).
   Counters the train-data label imbalance (e.g. HEDGE dominates 2016-2023 cocoa).

2. **Recency decay** (exponential half-life):
   w[i] = 0.5 ** (days_to_latest / halflife_days).
   Counters distribution shift — recent samples weigh more, so the model adapts
   to the 2024-01-30 structural break and the 2026-Q1 bullish drift.

These are causal: the latest date in the *training slice* anchors recency, NOT
the global dataset latest date, so no fold-level leakage.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def balanced_class_weight(y_train: pd.Series | np.ndarray) -> dict[str, float]:
    """Return ``{class: inverse_frequency_weight}`` such that sum(weight) ≈ n.

    Equivalent to sklearn's ``class_weight='balanced'`` formula:
        w[c] = n_samples / (n_classes * n_samples_of_class_c)
    """
    y = np.asarray(y_train)
    if len(y) == 0:
        return {}
    classes, counts = np.unique(y, return_counts=True)
    n_total = float(len(y))
    n_classes = float(len(classes))
    weights = {str(c): float(n_total / (n_classes * cnt)) for c, cnt in zip(classes, counts)}
    return weights


def recency_decay_weights(
    dates: pd.Series | np.ndarray,
    *,
    halflife_days: int = 180,
) -> np.ndarray:
    """Exponential recency decay anchored on the latest date in the array.

    ``w[i] = 0.5 ** (days_to_latest_i / halflife_days)``.

    With halflife=180: the last day has weight 1.0; ~6 months ago weight 0.5;
    ~3 years ago weight ~0.03.
    """
    dt = pd.to_datetime(pd.Series(dates))
    if len(dt) == 0:
        return np.zeros(0, dtype=float)
    latest = dt.max()
    days_to_latest = (latest - dt).dt.days.to_numpy().astype(float)
    if halflife_days <= 0:
        return np.ones(len(dt), dtype=float)
    return np.power(0.5, days_to_latest / float(halflife_days))


def composed_sample_weights(
    y_train: pd.Series | np.ndarray,
    dates: pd.Series | np.ndarray,
    *,
    use_class_weight: bool = True,
    use_recency: bool = True,
    halflife_days: int = 180,
    extra_class_weight: dict[str, float] | None = None,
) -> np.ndarray:
    """Compose final per-sample weight = class_weight × recency_decay × extra.

    Args:
        y_train: training class labels (DOWN/FLAT/UP).
        dates: aligned date series; anchors recency on the latest train date.
        use_class_weight: multiply by inverse-frequency balanced weights.
        use_recency: multiply by exponential recency decay.
        halflife_days: half-life for recency decay.
        extra_class_weight: optional manual override (multiplied on top), useful
            for bull/bear specialists (e.g. ``{"UP": 2.0, "DOWN": 0.5}``).

    Returns:
        np.ndarray of shape ``(len(y_train),)`` with non-negative weights.
    """
    y = np.asarray(y_train)
    n = len(y)
    if n == 0:
        return np.zeros(0, dtype=float)

    weights = np.ones(n, dtype=float)

    if use_class_weight:
        cw = balanced_class_weight(y)
        weights = weights * np.array([cw.get(str(yi), 1.0) for yi in y])

    if extra_class_weight is not None:
        weights = weights * np.array([float(extra_class_weight.get(str(yi), 1.0)) for yi in y])

    if use_recency:
        weights = weights * recency_decay_weights(dates, halflife_days=halflife_days)

    # Normalise so mean weight = 1 (prevents LightGBM from interpreting the
    # weights as a fractional sample count and shrinking effective n).
    if weights.sum() > 0:
        weights = weights * (n / weights.sum())
    return weights
