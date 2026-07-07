"""Feature engineering with zero-leakage guarantees.

Spec: methodology/framework-spec.md §4.3.

A FeatureSpec describes ONE feature: which source columns it depends on, what
transform to apply, what normalization, and lag (in trading days). All
transformations are CAUSAL.

Groups:
    SPOT_FEATURES         — range/mean-reversion (close_pivot, bollinger, stoch, MR)
    MOMENTUM_FEATURES     — trend/derivative (MACD, RSI, ATR, return, vol_oi)
    FUNDAMENTAL_FEATURES  — COT positioning, sentiment scores, procurement
    REGIME_FEATURES       — vol_state, atr_state (NOT regime_id — that comes from a fold-local HMM)

assert_no_lookahead runs a shuffle-future randomized check.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd


Normalization = Literal["none", "rolling_zscore_250", "pctrank_50", "pctrank_252"]
FeatureGroup = Literal["spot", "momentum", "fundamental", "regime"]


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    source_cols: tuple[str, ...]
    transform: Callable[[pd.DataFrame], pd.Series]
    normalize: Normalization = "rolling_zscore_250"
    lag: int = 0
    group: FeatureGroup = "spot"
    allow_missing_sources: bool = False


def _passthrough_impl(col: str, df: pd.DataFrame) -> pd.Series:
    return df[col].astype(float)


def _diff_impl(col_a: str, col_b: str, df: pd.DataFrame) -> pd.Series:
    return df[col_a].astype(float) - df[col_b].astype(float)


def _ratio_impl(col_a: str, col_b: str, df: pd.DataFrame) -> pd.Series:
    b = df[col_b].astype(float).replace(0.0, np.nan)
    return df[col_a].astype(float) / b


# Factories return module-level partials so the resulting callables are
# pickle-friendly (closures over local-scope variables are NOT picklable, which
# blocks the freezer when sklearn tries to serialize the fit candidate).
def _passthrough(col: str) -> Callable[[pd.DataFrame], pd.Series]:
    return functools.partial(_passthrough_impl, col)


def _diff(col_a: str, col_b: str) -> Callable[[pd.DataFrame], pd.Series]:
    return functools.partial(_diff_impl, col_a, col_b)


def _ratio(col_a: str, col_b: str) -> Callable[[pd.DataFrame], pd.Series]:
    return functools.partial(_ratio_impl, col_a, col_b)


SPOT_FEATURES: tuple[FeatureSpec, ...] = (
    FeatureSpec("close_pivot_ratio", ("close_pivot_ratio",), _passthrough("close_pivot_ratio"), normalize="rolling_zscore_250", group="spot"),
    FeatureSpec("bollinger_width", ("bollinger_width",), _passthrough("bollinger_width"), normalize="rolling_zscore_250", group="spot", allow_missing_sources=True),
    FeatureSpec("stochastic_d_14", ("stochastic_d_14",), _passthrough("stochastic_d_14"), normalize="none", group="spot"),
    FeatureSpec("rsi_14d", ("rsi_14d",), _passthrough("rsi_14d"), normalize="none", group="spot"),
)


MOMENTUM_FEATURES: tuple[FeatureSpec, ...] = (
    FeatureSpec("macd", ("macd",), _passthrough("macd"), normalize="rolling_zscore_250", group="momentum"),
    FeatureSpec("macd_signal", ("macd_signal",), _passthrough("macd_signal"), normalize="rolling_zscore_250", group="momentum"),
    FeatureSpec("macd_minus_signal", ("macd", "macd_signal"), _diff("macd", "macd_signal"), normalize="rolling_zscore_250", group="momentum"),
    FeatureSpec("atr_14d", ("atr_14d",), _passthrough("atr_14d"), normalize="rolling_zscore_250", group="momentum"),
    FeatureSpec("daily_return", ("daily_return",), _passthrough("daily_return"), normalize="none", group="momentum"),
    FeatureSpec("volume_oi_ratio", ("volume_oi_ratio",), _passthrough("volume_oi_ratio"), normalize="rolling_zscore_250", group="momentum", allow_missing_sources=True),
)


FUNDAMENTAL_FEATURES: tuple[FeatureSpec, ...] = (
    FeatureSpec("cot_m_money_net_z_26w", ("cot_m_money_net_z_26w",), _passthrough("cot_m_money_net_z_26w"), normalize="none", group="fundamental", allow_missing_sources=True),
    FeatureSpec("cot_prod_merc_net_z_26w", ("cot_prod_merc_net_z_26w",), _passthrough("cot_prod_merc_net_z_26w"), normalize="none", group="fundamental", allow_missing_sources=True),
    FeatureSpec("cot_m_money_net_pctile_26w", ("cot_m_money_net_pctile_26w",), _passthrough("cot_m_money_net_pctile_26w"), normalize="none", group="fundamental", allow_missing_sources=True),
    FeatureSpec("sent_all_production", ("sent_all_production",), _passthrough("sent_all_production"), normalize="rolling_zscore_250", group="fundamental", allow_missing_sources=True),
    FeatureSpec("sent_all_chocolat", ("sent_all_chocolat",), _passthrough("sent_all_chocolat"), normalize="rolling_zscore_250", group="fundamental", allow_missing_sources=True),
    FeatureSpec("sent_afrique_ouest_production", ("sent_afrique_ouest_production",), _passthrough("sent_afrique_ouest_production"), normalize="rolling_zscore_250", group="fundamental", allow_missing_sources=True),
    FeatureSpec("feves_share", ("feves_share",), _passthrough("feves_share"), normalize="rolling_zscore_250", group="fundamental", allow_missing_sources=True),
    FeatureSpec("processing_ratio", ("processing_ratio",), _passthrough("processing_ratio"), normalize="rolling_zscore_250", group="fundamental", allow_missing_sources=True),
    FeatureSpec("procurement_hhi", ("procurement_hhi",), _passthrough("procurement_hhi"), normalize="rolling_zscore_250", group="fundamental", allow_missing_sources=True),
    FeatureSpec("top3_exporter_share", ("top3_exporter_share",), _passthrough("top3_exporter_share"), normalize="rolling_zscore_250", group="fundamental", allow_missing_sources=True),
)


REGIME_FEATURES: tuple[FeatureSpec, ...] = (
    # vol_state: atr_14d quantile bucket (low/mid/high) -- computed as rolling pctrank
    FeatureSpec("atr_pctrank_252", ("atr_14d",), _passthrough("atr_14d"), normalize="pctrank_252", group="regime"),
)


ALL_GROUPS: dict[str, tuple[FeatureSpec, ...]] = {
    "spot": SPOT_FEATURES,
    "momentum": MOMENTUM_FEATURES,
    "fundamental": FUNDAMENTAL_FEATURES,
    "regime": REGIME_FEATURES,
}


def _rolling_zscore(s: pd.Series, window: int = 250, min_periods: int = 50) -> pd.Series:
    mean = s.rolling(window, min_periods=min_periods).mean()
    std = s.rolling(window, min_periods=min_periods).std(ddof=0)
    z = (s - mean) / std.replace(0.0, np.nan)
    return z


def _pctrank(s: pd.Series, window: int) -> pd.Series:
    # pct rank within rolling window, causal
    return s.rolling(window, min_periods=max(10, window // 5)).rank(pct=True)


def apply_normalization(s: pd.Series, kind: Normalization) -> pd.Series:
    if kind == "none":
        return s
    if kind == "rolling_zscore_250":
        return _rolling_zscore(s, window=250, min_periods=50)
    if kind == "pctrank_50":
        return _pctrank(s, window=50)
    if kind == "pctrank_252":
        return _pctrank(s, window=252)
    raise ValueError(f"Unknown normalization: {kind}")


def build_feature_matrix(
    df: pd.DataFrame,
    specs: list[FeatureSpec] | tuple[FeatureSpec, ...],
    *,
    normalize_override: Normalization | None = None,
    skip_missing: bool = True,
    enforce_no_leak: bool = False,
    no_leak_seed: int = 42,
) -> pd.DataFrame:
    """Apply each spec, normalize, lag.

    Args:
        df: source DataFrame with the canonical columns.
        specs: feature specs to build.
        normalize_override: if provided, override every spec's `normalize`.
        skip_missing: if a spec's source col is missing and `allow_missing_sources`,
            skip silently; otherwise raise.
        enforce_no_leak: run a randomized shuffle-future check.
        no_leak_seed: RNG seed for the shuffle check.

    Returns:
        DataFrame indexed like ``df`` with one column per built spec. Column name = spec.name.
    """
    built: dict[str, pd.Series] = {}
    for spec in specs:
        missing = [c for c in spec.source_cols if c not in df.columns]
        if missing:
            if spec.allow_missing_sources and skip_missing:
                continue
            raise ValueError(f"FeatureSpec {spec.name!r} missing sources: {missing}")
        raw = spec.transform(df)
        norm_kind = normalize_override if normalize_override is not None else spec.normalize
        normed = apply_normalization(raw, norm_kind)
        if spec.lag > 0:
            normed = normed.shift(spec.lag)
        elif spec.lag < 0:
            raise ValueError(f"FeatureSpec {spec.name!r} has negative lag {spec.lag} (would leak)")
        built[spec.name] = normed
    out = pd.DataFrame(built, index=df.index)
    if enforce_no_leak:
        assert_no_lookahead(out, df, specs=list(specs), seed=no_leak_seed, normalize_override=normalize_override)
    return out


def assert_no_lookahead(
    features: pd.DataFrame,
    df_source: pd.DataFrame,
    *,
    specs: list[FeatureSpec],
    seed: int = 42,
    normalize_override: Normalization | None = None,
    perturb_fraction: float = 0.5,
) -> None:
    """Shuffle a random subset of the FUTURE half of ``df_source`` and verify that
    features at PAST indices are unchanged.

    If any past-index feature value changes after perturbing future data, there
    is a look-ahead leak. Raises AssertionError describing the offending column.
    """
    rng = np.random.default_rng(seed)
    n = len(df_source)
    pivot = n // 2

    perturbed = df_source.copy()
    future_idx = np.arange(pivot, n)
    if len(future_idx) == 0:
        return
    # Always include the first `boundary_band` future indices so that shift(-k) leaks
    # are caught deterministically for small k. Then sample the rest randomly.
    boundary_band = min(20, len(future_idx))
    forced = future_idx[:boundary_band]
    remaining = future_idx[boundary_band:]
    n_random = int(perturb_fraction * len(remaining))
    if n_random > 0:
        sampled = rng.choice(remaining, size=n_random, replace=False)
        target_idx = np.concatenate([forced, sampled])
    else:
        target_idx = forced
    if len(target_idx) == 0:
        return

    numeric_cols = perturbed.select_dtypes(include=[np.number]).columns.tolist()
    n_target = len(target_idx)
    for col in numeric_cols:
        col_vals = perturbed[col].to_numpy(copy=True)
        col_vals[target_idx] = col_vals[target_idx] + rng.standard_normal(n_target) * (
            np.nanstd(col_vals) + 1e-9
        )
        perturbed[col] = col_vals

    rebuilt = build_feature_matrix(
        perturbed,
        specs,
        normalize_override=normalize_override,
        enforce_no_leak=False,
    )

    past_slice = slice(0, pivot)
    for col in features.columns:
        if col not in rebuilt.columns:
            continue
        a = features[col].iloc[past_slice].to_numpy()
        b = rebuilt[col].iloc[past_slice].to_numpy()
        both_nan = np.isnan(a) & np.isnan(b)
        diff = np.where(both_nan, 0.0, np.abs(np.nan_to_num(a) - np.nan_to_num(b)))
        max_diff = float(np.nanmax(diff))
        if max_diff > 1e-9:
            raise AssertionError(
                f"Look-ahead leak detected in feature {col!r}: "
                f"past-index values changed when future-index source data was perturbed "
                f"(max diff = {max_diff:.3e})"
            )


def specs_for_groups(groups: list[str]) -> list[FeatureSpec]:
    """Convenience: collect all feature specs for the requested groups."""
    out: list[FeatureSpec] = []
    for g in groups:
        if g not in ALL_GROUPS:
            raise ValueError(f"Unknown feature group: {g}")
        out.extend(ALL_GROUPS[g])
    return out
