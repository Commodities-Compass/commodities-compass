"""MAXIMAL_FEATURES: auto-generate FeatureSpecs from every numeric column.

Goal: when the user demands "no raw input data left unused", this module enumerates
every numeric column of the enriched dataset (canonical CSV + ENSO + FX merge) and
emits a FeatureSpec with sensible defaults.

Heuristics for normalization:
    - cols already normalised (suffix `_z_26w`, `_pctile_26w`, sentiment 'sent_*',
      ENSO `oni`/`nino34_anomaly`, ratios like `*_ratio`, shares like `*_share`):
        normalize="none"
    - rolling z-scored cols pre-normalized:
        normalize="none" (use as-is)
    - default for everything else: normalize="rolling_zscore_250"
"""

from __future__ import annotations

import pandas as pd

from ensemble.features import FeatureSpec, _passthrough


# Columns to exclude from feature generation (keys, dates, derived targets)
_EXCLUDED_COLS: frozenset[str] = frozenset({
    "date",
    "contract_code",
    "contract_month",
    "cot_as_of_date",
    "release_date",
    "year",
    "month",
})


def _is_already_normalised(col: str) -> bool:
    """Heuristic: cols that come pre-scaled / pre-z-scored."""
    if col.endswith("_z_26w") or col.endswith("_pctile_26w"):
        return True
    if col.startswith("sent_"):  # sentiment scores already in [-1, 1]
        return True
    if col in {"oni", "nino34_anomaly"}:
        return True
    if col.endswith("_share") or col.endswith("_ratio") or col.endswith("_hhi"):
        return True
    return False


def _is_forward_target(col: str) -> bool:
    return col.startswith("forward_return_")


def build_maximal_features(
    df: pd.DataFrame,
    *,
    drop_extra_cols: tuple[str, ...] = (),
    group_name: str = "fundamental",
) -> list[FeatureSpec]:
    """Generate one FeatureSpec per numeric column of df (minus exclusions).

    Args:
        df: a fully enriched DataFrame (canonical CSV after ENSO + FX merge_external).
        drop_extra_cols: any additional cols to skip.
        group_name: feature group to tag all auto-specs with. Default "fundamental"
            so they sit alongside COT/sentiment in the existing FUND base candidate.

    Returns:
        list[FeatureSpec] — typically ~80 specs after exclusions.
    """
    excluded = set(_EXCLUDED_COLS) | set(drop_extra_cols)
    specs: list[FeatureSpec] = []
    for col in df.columns:
        if col in excluded:
            continue
        if _is_forward_target(col):
            continue
        if not pd.api.types.is_numeric_dtype(df[col]):
            continue
        normalize = "none" if _is_already_normalised(col) else "rolling_zscore_250"
        specs.append(
            FeatureSpec(
                name=col,
                source_cols=(col,),
                transform=_passthrough(col),
                normalize=normalize,
                lag=0,
                group=group_name,  # type: ignore[arg-type]
                allow_missing_sources=True,
            )
        )
    return specs


def maximal_features_from_canonical() -> list[FeatureSpec]:
    """Convenience: load the canonical dataset (merged with ENSO + FX) and build all specs.

    The returned list is *static* (computed once at import time of the runner).
    Each variant runner uses the SAME spec list to ensure overlap is comparable.
    """
    from ensemble.data_loader import load_dataset
    from ensemble.external_data import merge_external

    df = load_dataset(horizon=6)
    df_enriched = merge_external(df, include_enso=True, include_fx=True)
    return build_maximal_features(df_enriched)
