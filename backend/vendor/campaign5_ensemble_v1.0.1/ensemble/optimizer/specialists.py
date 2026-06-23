"""SpecialistArchitecture registry — Campaign 4 Phase 0c.

Each entry pins ONE specialist's architecture (target_fn, feature panel,
sample_weight policy, horizon, fixed model families). The remaining
hyperparameters (HPs, normalization, decision thresholds tau_*, ATR multiple)
are explored by Optuna under the architecture-conditioned SearchSpaceSpec.

The verified pool (n_committed_per_month >= 10, max 2 specialists per source
family) drawn from `output/exp_optim_018b/` clustering + manual diversity audit:

Winter (Jan-Feb specialists):
    W1 - exp_optim_002  (Triple-Barrier labels, baseline features)
    W2 - exp_optim_005  (GARCH(1,1) residual added to momentum bag)
    W3 - exp_optim_006  (3-week horizon, h=22, baseline target)
    W4 - exp_optim_011  (FX + ENSO macro features in fundamental bag)

Spring (Mar-Apr specialists, from EXP-OPTIM-017 Phase B bull/bear):
    S1 - exp_optim_017_bear_4  (DOWN-weighted, FX features, calibrated-TB target)
    S2 - exp_optim_017_bear_8  (DOWN-weighted, FX+ENSO features)
    S3 - exp_optim_017_bull_5  (UP-weighted, baseline features, Logistic meta)
    S4 - exp_optim_017_bull_7  (UP-weighted, FX features)
    S5 - exp_optim_017_bull_8  (UP-weighted, MAXIMAL feature panel)
    S6 - exp_optim_017_bull_4  (UP-weighted, FX features, alt class weights)

(Wrapper-style specialists - exp_optim_003 MetaLabeling, exp_optim_013
Selective, exp_optim_016/017_det_v2/017_llm_v2 ensembles - are skipped at
Phase 0c because they require additional plumbing beyond what the Optuna
objective currently supports. Their tuning lands in a future phase.)
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd

from ensemble.features import (
    FUNDAMENTAL_FEATURES,
    MOMENTUM_FEATURES,
    SPOT_FEATURES,
    FeatureSpec,
)
from ensemble.features_external import ENSO_FEATURES, FX_FEATURES
from ensemble.features_garch import garch_residual_series
from ensemble.features_maximal import maximal_features_from_canonical
from ensemble.optimizer.search_space import FeatureGroup, ModelFamily, SearchSpaceSpec
from ensemble.targets_calibrated import compute_calibrated_tb_labels
from ensemble.targets_triple_barrier import compute_triple_barrier_labels
from ensemble.training_utils.anti_bias import composed_sample_weights

ClusterName = Literal["winter", "spring"]


# ============================================================================
# Lazy resources (computed once, cached process-wide)
# ============================================================================
_GARCH_CACHE: dict[str, pd.Series] = {}


def _key(df: pd.DataFrame) -> str:
    return f"{len(df)}_{df['date'].iloc[0]}_{df['date'].iloc[-1]}"


def _garch_series(df: pd.DataFrame) -> pd.Series:
    k = _key(df)
    if k not in _GARCH_CACHE:
        _GARCH_CACHE[k] = garch_residual_series(df, fit_window=500, refit_every=22)
    return _GARCH_CACHE[k]


def _garch_spec() -> FeatureSpec:
    return FeatureSpec(
        name="garch_resid_w500",
        source_cols=("daily_return",),
        transform=_garch_series,
        normalize="none",
        lag=0,
        group="momentum",
        allow_missing_sources=False,
    )


# ============================================================================
# Sample-weight factories
# ============================================================================
def make_antibias_sw_fn(
    *,
    halflife_days: int = 180,
    extra_class_weight: dict[str, float] | None = None,
):
    """Return a callable(train, y_train) -> sample_weight array per the
    Campaign 3 Phase A anti-bias scheme (balanced class weight + recency decay
    + optional asymmetric extra weight for bull/bear specialists)."""

    def _fn(train: pd.DataFrame, y_train: pd.Series) -> np.ndarray:
        return composed_sample_weights(
            y_train,
            train["date"],
            use_class_weight=True,
            use_recency=True,
            halflife_days=halflife_days,
            extra_class_weight=extra_class_weight,
        )

    return _fn


# ============================================================================
# Specialist architecture
# ============================================================================
FeatureSpecsT = tuple[list[FeatureSpec], list[FeatureSpec], list[FeatureSpec]]


@dataclass(frozen=True)
class SpecialistArchitecture:
    name: str  # short id, e.g. "exp_optim_002"
    cluster: ClusterName
    title: str
    horizon: int
    target_fn: Callable[..., pd.Series] | None  # None => baseline 3-class ATR
    target_kwargs: dict[str, Any] = field(default_factory=dict)
    with_enso: bool = False
    with_fx: bool = False
    feature_panel: str = "baseline"  # "baseline" | "fx_focus" | "fx_enso_focus" | "maximal" | "+garch"
    extra_class_weight: dict[str, float] | None = None
    use_antibias: bool = False
    halflife_days: int = 180
    feature_groups_force: tuple[FeatureGroup, ...] = ("technical", "cot", "sentiment", "fundamentals_ops")
    # Optional family restrictions (Phase 0c keeps the full {logistic, RF, lightgbm}
    # set unless the architecture pins a specific family for historical reasons).
    candidate_families: tuple[ModelFamily, ...] | None = None
    meta_families: tuple[ModelFamily, ...] | None = None

    @property
    def min_window_months(self) -> int:
        """Minimum monthly-retrain window length supported by this architecture.

        Derived from architectural constraints, NOT a heuristic guess:
        - GARCH residual feature: needs >=500 trading days for the rolling
          fit_window to be meaningful -> 24 months.
        - calibrated-TB target: needs calibration_window_months (default 12)
          of data to back-fit the barrier multiples to target_balance.
        - Triple-Barrier target: needs at least max_horizon * ~3 training days
          for barrier hits to be observed in both directions, otherwise labels
          collapse to single-class. max_horizon default 22 -> ~3 months effective
          training requires >=6 calendar months window.
        - Baseline 3-class ATR target: no special requirement -> 3 months floor.

        The runner uses this to filter the user-requested window list. Windows
        below this minimum are SKIPPED with a logged reason; they are not silently
        clamped or fallen-back. The architecture either supports a window or it
        doesn't.
        """
        if self.feature_panel.startswith("+garch"):
            return 24
        if self.target_fn is None:
            return 3
        # Inspect the target_fn name to detect calibrated-TB vs vanilla TB
        target_name = getattr(self.target_fn, "__name__", "")
        if target_name == "compute_calibrated_tb_labels":
            return max(12, int(self.target_kwargs.get("calibration_window_months", 12)))
        if target_name == "compute_triple_barrier_labels":
            return 6
        return 3

    def build_feature_specs(self) -> FeatureSpecsT:
        """Return (spot_specs, mom_specs, fund_specs) for this architecture.

        Feature panel grammar:
            "baseline"             -> SPOT + MOMENTUM + FUNDAMENTAL
            "maximal"              -> all-numeric maximal (≈ 91 specs per bag)
            "fx_focus"             -> baseline + FX in fund
            "fx_enso_focus"        -> baseline + FX + ENSO in fund
            "+garch"               -> baseline + GARCH residual in mom
            "+garch_fx_focus"      -> baseline + GARCH in mom + FX in fund
            "+garch_fx_enso_focus" -> baseline + GARCH in mom + FX+ENSO in fund
        """
        spot = list(SPOT_FEATURES)
        mom = list(MOMENTUM_FEATURES)
        fund = list(FUNDAMENTAL_FEATURES)
        panel = self.feature_panel
        if panel == "maximal":
            maximal = list(maximal_features_from_canonical())
            return maximal, maximal, maximal
        # Parse fund-side macro additions
        if panel in ("fx_focus", "+garch_fx_focus"):
            fund = fund + list(FX_FEATURES)
        elif panel in ("fx_enso_focus", "+garch_fx_enso_focus"):
            fund = fund + list(FX_FEATURES) + list(ENSO_FEATURES)
        # Parse mom-side GARCH augmentation
        if panel in ("+garch", "+garch_fx_focus", "+garch_fx_enso_focus"):
            mom = mom + [_garch_spec()]
        return spot, mom, fund

    def build_search_space(self) -> SearchSpaceSpec:
        kwargs: dict[str, Any] = {
            "horizon": self.horizon,
            "feature_groups_force": self.feature_groups_force,
        }
        if self.candidate_families is not None:
            kwargs["candidate_families"] = self.candidate_families
        if self.meta_families is not None:
            kwargs["meta_families"] = self.meta_families
        return SearchSpaceSpec(**kwargs)

    def build_sample_weight_fn(self):
        if not self.use_antibias:
            return None
        return make_antibias_sw_fn(
            halflife_days=self.halflife_days,
            extra_class_weight=self.extra_class_weight,
        )

    def load_data(self) -> pd.DataFrame:
        return load_dataset(with_enso=self.with_enso, with_fx=self.with_fx, horizon=self.horizon)


# ============================================================================
# Registry — verified pool from Phase 0b (n_committed_per_month >= 10).
# ============================================================================
SPECIALISTS: tuple[SpecialistArchitecture, ...] = (
    # ---------------- Winter (Jan-Feb) ----------------
    SpecialistArchitecture(
        name="exp_optim_002",
        cluster="winter",
        title="W1 — Triple-Barrier (LdP §3.3) baseline features",
        horizon=6,
        target_fn=compute_triple_barrier_labels,
        target_kwargs={"atr_tp_mult": 2.0, "atr_sl_mult": 1.0, "max_horizon": 22},
    ),
    SpecialistArchitecture(
        name="exp_optim_005",
        cluster="winter",
        title="W2 — GARCH(1,1) residual in momentum bag (NM-002)",
        horizon=6,
        target_fn=None,
        feature_panel="+garch",
    ),
    SpecialistArchitecture(
        name="exp_optim_006",
        cluster="winter",
        title="W3 — Baseline candidate at h=22 (3-week horizon)",
        horizon=22,
        target_fn=None,
    ),
    SpecialistArchitecture(
        name="exp_optim_011",
        cluster="winter",
        title="W4 — Macro combined (ENSO + FX) in fundamental bag",
        horizon=6,
        target_fn=None,
        with_enso=True,
        with_fx=True,
        feature_panel="fx_enso_focus",
    ),
    # ---------------- Spring (Mar-Apr) — bear specialists ----------------
    SpecialistArchitecture(
        name="exp_optim_017_bear_4",
        cluster="spring",
        title="S1 — Bear specialist DOWN:3 + FX features + calibrated-TB",
        horizon=6,
        target_fn=compute_calibrated_tb_labels,
        target_kwargs={"calibration_window_months": 12, "target_balance": (0.33, 0.33, 0.34), "max_horizon": 22},
        with_fx=True,
        feature_panel="fx_focus",
        extra_class_weight={"DOWN": 3.0, "FLAT": 1.0, "UP": 0.5},
        use_antibias=True,
        halflife_days=180,
    ),
    SpecialistArchitecture(
        name="exp_optim_017_bear_8",
        cluster="spring",
        title="S2 — Bear specialist DOWN:2 + FX+ENSO features",
        horizon=6,
        target_fn=compute_calibrated_tb_labels,
        target_kwargs={"calibration_window_months": 12, "target_balance": (0.33, 0.33, 0.34), "max_horizon": 22},
        with_enso=True,
        with_fx=True,
        feature_panel="fx_enso_focus",
        extra_class_weight={"DOWN": 2.0, "FLAT": 1.0, "UP": 1.0},
        use_antibias=True,
        halflife_days=180,
    ),
    # ---------------- Spring — bull specialists ----------------
    SpecialistArchitecture(
        name="exp_optim_017_bull_4",
        cluster="spring",
        title="S3 — Bull specialist UP:2 + FX features",
        horizon=6,
        target_fn=compute_calibrated_tb_labels,
        target_kwargs={"calibration_window_months": 12, "target_balance": (0.33, 0.33, 0.34), "max_horizon": 22},
        with_fx=True,
        feature_panel="fx_focus",
        extra_class_weight={"UP": 2.0, "FLAT": 1.0, "DOWN": 1.0},
        use_antibias=True,
        halflife_days=180,
    ),
    SpecialistArchitecture(
        name="exp_optim_017_bull_5",
        cluster="spring",
        title="S4 — Bull specialist UP:3 + Logistic meta + baseline features",
        horizon=6,
        target_fn=compute_calibrated_tb_labels,
        target_kwargs={"calibration_window_months": 12, "target_balance": (0.33, 0.33, 0.34), "max_horizon": 22},
        feature_panel="baseline",
        extra_class_weight={"UP": 3.0, "FLAT": 1.0, "DOWN": 0.5},
        use_antibias=True,
        halflife_days=180,
        meta_families=("logistic",),
    ),
    SpecialistArchitecture(
        name="exp_optim_017_bull_7",
        cluster="spring",
        title="S5 — Bull specialist UP:3 + FX features",
        horizon=6,
        target_fn=compute_calibrated_tb_labels,
        target_kwargs={"calibration_window_months": 12, "target_balance": (0.33, 0.33, 0.34), "max_horizon": 22},
        with_fx=True,
        feature_panel="fx_focus",
        extra_class_weight={"UP": 3.0, "FLAT": 1.0, "DOWN": 0.5},
        use_antibias=True,
        halflife_days=180,
    ),
    SpecialistArchitecture(
        name="exp_optim_017_bull_8",
        cluster="spring",
        title="S6 — Bull specialist UP:2 + MAXIMAL features",
        horizon=6,
        target_fn=compute_calibrated_tb_labels,
        target_kwargs={"calibration_window_months": 12, "target_balance": (0.33, 0.33, 0.34), "max_horizon": 22},
        feature_panel="maximal",
        extra_class_weight={"UP": 2.0, "FLAT": 1.0, "DOWN": 1.0},
        use_antibias=True,
        halflife_days=180,
    ),
    # ---------------- Phase 0d cross-pollinated specialists (2026-05-17) ----------------
    # Combine proven Campaign 2-3 ingredients into new architectures never tested before.
    SpecialistArchitecture(
        name="xpol_W_TB_garch",
        cluster="winter",
        title="X1 — Triple-Barrier labels + GARCH residual (W1 ⊗ W2)",
        horizon=6,
        target_fn=compute_triple_barrier_labels,
        target_kwargs={"atr_tp_mult": 2.0, "atr_sl_mult": 1.0, "max_horizon": 22},
        feature_panel="+garch",
    ),
    SpecialistArchitecture(
        name="xpol_W_TB_macro",
        cluster="winter",
        title="X2 — Triple-Barrier labels + FX+ENSO macro features (W1 ⊗ W4)",
        horizon=6,
        target_fn=compute_triple_barrier_labels,
        target_kwargs={"atr_tp_mult": 2.0, "atr_sl_mult": 1.0, "max_horizon": 22},
        with_enso=True,
        with_fx=True,
        feature_panel="fx_enso_focus",
    ),
    SpecialistArchitecture(
        name="xpol_S_bull_garch_fx",
        cluster="spring",
        title="X3 — Bull specialist UP:3 + GARCH residual + FX (S4 ⊗ W2)",
        horizon=6,
        target_fn=compute_calibrated_tb_labels,
        target_kwargs={"calibration_window_months": 12, "target_balance": (0.33, 0.33, 0.34), "max_horizon": 22},
        with_fx=True,
        feature_panel="+garch_fx_focus",
        extra_class_weight={"UP": 3.0, "FLAT": 1.0, "DOWN": 0.5},
        use_antibias=True,
        halflife_days=180,
    ),
    SpecialistArchitecture(
        name="xpol_S_bear_garch_macro",
        cluster="spring",
        title="X4 — Bear specialist DOWN:3 + GARCH residual + FX+ENSO (S1 ⊗ W2 ⊗ W4)",
        horizon=6,
        target_fn=compute_calibrated_tb_labels,
        target_kwargs={"calibration_window_months": 12, "target_balance": (0.33, 0.33, 0.34), "max_horizon": 22},
        with_enso=True,
        with_fx=True,
        feature_panel="+garch_fx_enso_focus",
        extra_class_weight={"DOWN": 3.0, "FLAT": 1.0, "UP": 0.5},
        use_antibias=True,
        halflife_days=180,
    ),
)


def specialists_by_name() -> dict[str, SpecialistArchitecture]:
    return {s.name: s for s in SPECIALISTS}
