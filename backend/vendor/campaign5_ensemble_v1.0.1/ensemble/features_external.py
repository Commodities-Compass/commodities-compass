"""Feature specs for the external columns (ENSO + FX) joined via merge_external."""

from __future__ import annotations

import functools

import numpy as np
import pandas as pd

from ensemble.features import FeatureSpec, _passthrough


def _zscore_60d_impl(col: str, df: pd.DataFrame) -> pd.Series:
    s = df[col].astype(float)
    mu = s.rolling(60, min_periods=20).mean()
    sd = s.rolling(60, min_periods=20).std(ddof=0)
    return (s - mu) / sd.replace(0.0, np.nan)


def _zscore_60d(col: str):
    """Module-level partial — picklable, unlike a local closure."""
    return functools.partial(_zscore_60d_impl, col)


ENSO_FEATURES: tuple[FeatureSpec, ...] = (
    FeatureSpec(
        name="enso_oni",
        source_cols=("oni",),
        transform=_passthrough("oni"),
        normalize="none",
        lag=0,
        group="fundamental",
        allow_missing_sources=True,
    ),
    FeatureSpec(
        name="enso_nino34_anomaly",
        source_cols=("nino34_anomaly",),
        transform=_passthrough("nino34_anomaly"),
        normalize="none",
        lag=0,
        group="fundamental",
        allow_missing_sources=True,
    ),
)


FX_FEATURES: tuple[FeatureSpec, ...] = (
    FeatureSpec(
        name="fx_dxy_proxy_zscore_60d",
        source_cols=("fx_dxy_proxy",),
        transform=_zscore_60d("fx_dxy_proxy"),
        normalize="none",
        lag=0,
        group="fundamental",
        allow_missing_sources=True,
    ),
    FeatureSpec(
        name="fx_gbpusd_zscore_60d",
        source_cols=("fx_gbpusd",),
        transform=_zscore_60d("fx_gbpusd"),
        normalize="none",
        lag=0,
        group="fundamental",
        allow_missing_sources=True,
    ),
)
