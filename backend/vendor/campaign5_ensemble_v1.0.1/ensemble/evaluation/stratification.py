"""Stratified evaluation by HMM regime, year, or contract month. Spec §4.11."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd

from ensemble.config import DEFAULT_REGIME_TAGS_CSV


def load_regime_tags(csv_path: Path = DEFAULT_REGIME_TAGS_CSV) -> pd.DataFrame:
    """Read date -> regime_id table emitted by scripts/extract_regime_tags.py."""
    if not csv_path.exists():
        raise FileNotFoundError(
            f"Regime tags missing at {csv_path}. Run: python scripts/extract_regime_tags.py"
        )
    df = pd.read_csv(csv_path, parse_dates=["date"])
    if "regime_id" not in df.columns:
        raise ValueError(f"{csv_path} missing 'regime_id' column")
    return df[["date", "regime_id", "regime_label"]].copy()


def attach_regime(
    df: pd.DataFrame, regime_tags: pd.DataFrame | None = None
) -> pd.DataFrame:
    """Left-join regime_id onto df on the date column. NaN regime_id is allowed."""
    if regime_tags is None:
        regime_tags = load_regime_tags()
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"])
    out = out.merge(regime_tags, on="date", how="left")
    return out


def stratified_metrics(
    df: pd.DataFrame,
    metric_fn: Callable[[pd.DataFrame], float],
    *,
    stratify_by: str = "regime_id",
) -> pd.DataFrame:
    """Apply metric_fn to each stratum, return long DataFrame {stratum, value, n}."""
    if stratify_by not in df.columns:
        raise ValueError(f"Column {stratify_by!r} not in DataFrame")
    rows = []
    for key, sub in df.groupby(stratify_by, dropna=True):
        rows.append({
            stratify_by: key,
            "value": float(metric_fn(sub)),
            "n": int(len(sub)),
        })
    return pd.DataFrame(rows)


def regime_cv(values: np.ndarray | list[float]) -> float:
    """Coefficient of variation across regimes (std / |mean|).

    Returns inf if mean is ~0; that's a legitimate signal that regime
    performance averages to zero (no robust skill).
    """
    arr = np.asarray(values, dtype=float)
    mu = float(np.mean(arr))
    sigma = float(np.std(arr, ddof=0))
    if abs(mu) < 1e-9:
        return float("inf")
    return sigma / abs(mu)
