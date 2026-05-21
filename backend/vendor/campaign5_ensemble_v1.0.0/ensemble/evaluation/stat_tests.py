"""Statistical tests for pairwise candidate comparison + multiple-comparison correction.

Spec §4.12.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import stats


def diebold_mariano(
    losses_a: np.ndarray,
    losses_b: np.ndarray,
    *,
    h: int = 6,
) -> tuple[float, float]:
    """Diebold-Mariano test for equal predictive accuracy.

    H0: E[losses_a - losses_b] = 0 (equal accuracy).
    Uses Harvey-Leybourne-Newbold correction for small samples.

    Args:
        losses_a, losses_b: per-period loss arrays (same length).
        h: forecast horizon, for HAC bandwidth.

    Returns:
        (dm_statistic, two_sided_p_value)
    """
    a = np.asarray(losses_a, dtype=float)
    b = np.asarray(losses_b, dtype=float)
    if a.shape != b.shape:
        raise ValueError(f"shape mismatch: {a.shape} vs {b.shape}")
    d = a - b
    n = len(d)
    if n < 4:
        return 0.0, 1.0
    mean_d = float(np.mean(d))

    # Newey-West variance with bandwidth h-1
    gamma_0 = float(np.mean((d - mean_d) ** 2))
    var_d = gamma_0
    for k in range(1, h):
        gamma_k = float(np.mean((d[k:] - mean_d) * (d[:-k] - mean_d)))
        var_d += 2.0 * (1.0 - k / h) * gamma_k
    var_d = max(var_d, 1e-12)
    dm = mean_d / np.sqrt(var_d / n)
    # Harvey-Leybourne-Newbold correction
    corr = ((n + 1 - 2 * h + h * (h - 1) / n) / n) ** 0.5
    dm_corr = float(dm * corr)
    # Two-sided p-value from t(n-1)
    p = 2.0 * float(1.0 - stats.t.cdf(abs(dm_corr), df=n - 1))
    return dm_corr, p


def mcnemar_test(
    y_true: np.ndarray | list,
    y_pred_a: np.ndarray | list,
    y_pred_b: np.ndarray | list,
) -> tuple[float, float]:
    """McNemar test (with continuity correction) on paired binary correctness.

    Returns (chi2_statistic, p_value).
    """
    yt = np.asarray(y_true)
    pa = np.asarray(y_pred_a)
    pb = np.asarray(y_pred_b)
    ca = pa == yt
    cb = pb == yt
    # b = A wrong, B right; c = A right, B wrong
    b = int(((~ca) & cb).sum())
    c = int((ca & (~cb)).sum())
    denom = b + c
    if denom == 0:
        return 0.0, 1.0
    chi2 = (abs(b - c) - 1.0) ** 2 / denom
    p = float(1.0 - stats.chi2.cdf(chi2, df=1))
    return float(chi2), p


def benjamini_hochberg(p_values: list[float] | np.ndarray, alpha: float = 0.05) -> np.ndarray:
    """Return boolean array indicating which hypotheses to reject under BH-FDR."""
    p = np.asarray(p_values, dtype=float)
    n = len(p)
    if n == 0:
        return np.zeros(0, dtype=bool)
    order = np.argsort(p)
    ranked = p[order]
    thresholds = (np.arange(1, n + 1) / n) * alpha
    reject_ranked = ranked <= thresholds
    if not reject_ranked.any():
        return np.zeros(n, dtype=bool)
    cutoff_rank = int(np.max(np.where(reject_ranked)[0]))
    reject = np.zeros(n, dtype=bool)
    reject[order[: cutoff_rank + 1]] = True
    return reject


@dataclass
class HypothesisRegistry:
    """Tracks cumulative tests on the same dataset (data snooping guard).

    Use ``.register(name, p_value)`` after every statistical test, then
    ``.adjusted_p_values(method='bh')`` before reporting.
    """

    _records: list[tuple[str, float]] = field(default_factory=list)

    def register(self, name: str, p_value: float) -> None:
        if not (0.0 <= float(p_value) <= 1.0):
            raise ValueError(f"p_value out of [0,1]: {p_value}")
        self._records.append((str(name), float(p_value)))

    def adjusted_p_values(self, method: str = "bh", alpha: float = 0.05) -> pd.DataFrame:
        if not self._records:
            return pd.DataFrame(columns=["name", "p_raw", "p_adj", "reject"])
        names = [r[0] for r in self._records]
        raws = np.array([r[1] for r in self._records])
        if method == "bh":
            rej = benjamini_hochberg(raws, alpha=alpha)
            n = len(raws)
            order = np.argsort(raws)
            ranks = np.empty(n, dtype=int)
            ranks[order] = np.arange(1, n + 1)
            adj = np.minimum(1.0, raws * n / ranks)
            # enforce monotonicity
            adj_sorted = adj[order]
            for i in range(n - 2, -1, -1):
                adj_sorted[i] = min(adj_sorted[i], adj_sorted[i + 1])
            adj_out = np.empty(n, dtype=float)
            adj_out[order] = adj_sorted
        elif method == "bonferroni":
            adj_out = np.minimum(1.0, raws * len(raws))
            rej = adj_out <= alpha
        else:
            raise ValueError(f"Unknown method: {method!r}")
        return pd.DataFrame({"name": names, "p_raw": raws, "p_adj": adj_out, "reject": rej})

    def __len__(self) -> int:
        return len(self._records)
