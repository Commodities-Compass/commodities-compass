"""Bootstrap CI on any metric. Stationary block bootstrap supported for autocorrelated data.

Spec: methodology/framework-spec.md §4.10.

Public API:
    bootstrap_ci(metric_fn, df, n_bootstrap, block_size, confidence, seed) -> (point, lo, hi)
    bootstrap_diff_ci(metric_fn, df_a, df_b, ...) -> (diff_point, lo, hi)

Notes
-----
Stationary bootstrap (Politis-Romano 1994) draws blocks of geometric length with
mean = ``block_size``. Used when residual autocorrelation makes IID resampling
overconfident.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd

MetricFn = Callable[[pd.DataFrame], float]


def _resample_iid(rng: np.random.Generator, n: int) -> np.ndarray:
    return rng.integers(0, n, size=n)


def _resample_stationary(rng: np.random.Generator, n: int, block_mean: float) -> np.ndarray:
    """Politis-Romano stationary bootstrap: geometric-length blocks wrapped circularly.

    Each step: continue current block with probability 1 - p, where p = 1/block_mean.
    Else start a new block at random index.
    """
    p = 1.0 / max(1.0, float(block_mean))
    out = np.empty(n, dtype=np.int64)
    cur = rng.integers(0, n)
    for i in range(n):
        out[i] = cur
        if rng.random() < p:
            cur = rng.integers(0, n)
        else:
            cur = (cur + 1) % n
    return out


def bootstrap_ci(
    metric_fn: MetricFn,
    df: pd.DataFrame,
    *,
    n_bootstrap: int = 5000,
    block_size: int | None = None,
    confidence: float = 0.95,
    seed: int = 42,
) -> tuple[float, float, float]:
    """Bootstrap confidence interval for an arbitrary metric.

    Args:
        metric_fn: callable(df) -> float. Should be deterministic on a given DataFrame.
        df: input rows. Resampling is over rows.
        n_bootstrap: number of resamples.
        block_size: if not None, uses stationary block bootstrap with mean block length = block_size.
        confidence: e.g. 0.95 for 95% CI.
        seed: RNG seed.

    Returns:
        (point_estimate, ci_low, ci_high). Point estimate is computed on full df,
        NOT on the bootstrap mean.
    """
    if len(df) < 2:
        return float(metric_fn(df)), float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    n = len(df)
    alpha_half = (1.0 - confidence) / 2.0

    df_idx = df.reset_index(drop=True)
    point = float(metric_fn(df_idx))

    boots = np.empty(n_bootstrap, dtype=float)
    for b in range(n_bootstrap):
        idx = (
            _resample_stationary(rng, n, block_mean=float(block_size))
            if (block_size is not None and block_size > 1)
            else _resample_iid(rng, n)
        )
        sample = df_idx.iloc[idx]
        boots[b] = float(metric_fn(sample))

    lo = float(np.percentile(boots, 100.0 * alpha_half))
    hi = float(np.percentile(boots, 100.0 * (1.0 - alpha_half)))
    return point, lo, hi


def bootstrap_diff_ci(
    metric_fn: MetricFn,
    df_a: pd.DataFrame,
    df_b: pd.DataFrame,
    *,
    n_bootstrap: int = 5000,
    block_size: int | None = None,
    confidence: float = 0.95,
    seed: int = 42,
) -> tuple[float, float, float]:
    """Bootstrap CI for ``metric(df_a) - metric(df_b)`` with independent resampling.

    Use when df_a and df_b are *not paired*. For paired data, pass a single df
    with both arms as columns and compute the difference inside `metric_fn`.
    """
    if len(df_a) < 2 or len(df_b) < 2:
        point = float(metric_fn(df_a) - metric_fn(df_b))
        return point, float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    alpha_half = (1.0 - confidence) / 2.0

    da = df_a.reset_index(drop=True)
    db = df_b.reset_index(drop=True)
    point = float(metric_fn(da) - metric_fn(db))

    boots = np.empty(n_bootstrap, dtype=float)
    for b in range(n_bootstrap):
        ia = (
            _resample_stationary(rng, len(da), block_mean=float(block_size))
            if (block_size is not None and block_size > 1)
            else _resample_iid(rng, len(da))
        )
        ib = (
            _resample_stationary(rng, len(db), block_mean=float(block_size))
            if (block_size is not None and block_size > 1)
            else _resample_iid(rng, len(db))
        )
        boots[b] = float(metric_fn(da.iloc[ia]) - metric_fn(db.iloc[ib]))
    lo = float(np.percentile(boots, 100.0 * alpha_half))
    hi = float(np.percentile(boots, 100.0 * (1.0 - alpha_half)))
    return point, lo, hi


def suggested_block_size(n_eff: int) -> int:
    """Politis-Romano rule of thumb: block_size = round(n_eff ** (1/3))."""
    return max(1, int(round(n_eff ** (1.0 / 3.0))))
