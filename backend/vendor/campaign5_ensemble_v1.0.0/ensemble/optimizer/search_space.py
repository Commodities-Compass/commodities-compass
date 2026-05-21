"""Search space definition for the Bayesian optimizer.

Each trial samples a TrialConfig — an immutable record describing one candidate
configuration to evaluate via walk-forward + Contrôle stacking + MONITOR rule.

Dimensions sampled (~15 hyperparameters):
    - feature_groups        : subset of {technical (spot/momentum), COT, sentiment, fundamentals_ops}
    - normalization         : {none, rolling_zscore_250, pctrank_50, pctrank_252}
    - target_atr_multiple   : continuous [0.30, 0.80]
    - target_horizon        : fixed at 6 (spec)
    - base_family_spot      : {logistic, random_forest, lightgbm}
    - base_family_mom       : {logistic, random_forest, lightgbm}
    - base_family_fund      : {logistic, random_forest, lightgbm}
    - hyperparams per family (C, n_estimators, max_depth, learning_rate, min_samples_leaf)
    - meta_family           : {logistic, lightgbm}
    - meta_C                : continuous (used when meta_family=logistic)
    - tau_conf              : [0.40, 0.70]
    - tau_diss              : [0.10, 0.40]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import optuna

ModelFamily = Literal["logistic", "random_forest", "lightgbm"]
Normalization = Literal["none", "rolling_zscore_250", "pctrank_50", "pctrank_252"]
FeatureGroup = Literal["technical", "cot", "sentiment", "fundamentals_ops"]
ALL_FEATURE_GROUPS: tuple[FeatureGroup, ...] = (
    "technical",
    "cot",
    "sentiment",
    "fundamentals_ops",
)


@dataclass(frozen=True)
class SearchSpaceSpec:
    horizon: int = 6
    atr_multiple_low: float = 0.30
    atr_multiple_high: float = 0.80
    tau_conf_low: float = 0.40
    tau_conf_high: float = 0.70
    tau_diss_low: float = 0.10
    tau_diss_high: float = 0.40
    candidate_families: tuple[ModelFamily, ...] = ("logistic", "random_forest", "lightgbm")
    meta_families: tuple[ModelFamily, ...] = ("logistic", "lightgbm")
    normalizations: tuple[Normalization, ...] = (
        "none",
        "rolling_zscore_250",
        "pctrank_50",
        "pctrank_252",
    )
    feature_groups: tuple[FeatureGroup, ...] = ALL_FEATURE_GROUPS
    # Phase 0c (2026-05-17): when set, the per-trial feature-group binary toggles are
    # replaced by this fixed tuple. The trial still records the fixed value as a
    # ``fg_*`` parameter so Optuna treats it deterministically.
    feature_groups_force: tuple[FeatureGroup, ...] | None = None


@dataclass(frozen=True)
class TrialConfig:
    feature_groups: tuple[FeatureGroup, ...]
    normalization: Normalization
    target_atr_multiple: float
    base_family_spot: ModelFamily
    base_family_mom: ModelFamily
    base_family_fund: ModelFamily
    base_hp_spot: dict[str, Any]
    base_hp_mom: dict[str, Any]
    base_hp_fund: dict[str, Any]
    meta_family: ModelFamily
    meta_hp: dict[str, Any]
    tau_conf: float
    tau_diss: float
    horizon: int = 6
    seed: int = 42

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_groups": list(self.feature_groups),
            "normalization": self.normalization,
            "target_atr_multiple": self.target_atr_multiple,
            "base_family_spot": self.base_family_spot,
            "base_family_mom": self.base_family_mom,
            "base_family_fund": self.base_family_fund,
            "base_hp_spot": self.base_hp_spot,
            "base_hp_mom": self.base_hp_mom,
            "base_hp_fund": self.base_hp_fund,
            "meta_family": self.meta_family,
            "meta_hp": self.meta_hp,
            "tau_conf": self.tau_conf,
            "tau_diss": self.tau_diss,
            "horizon": self.horizon,
            "seed": self.seed,
        }


def _sample_hp(trial: optuna.Trial, prefix: str, family: ModelFamily) -> dict[str, Any]:
    if family == "logistic":
        return {
            "C": trial.suggest_float(f"{prefix}_C", 1e-2, 1e2, log=True),
            "max_iter": 1000,
        }
    if family == "random_forest":
        return {
            "n_estimators": trial.suggest_int(f"{prefix}_n_estimators", 100, 400, step=100),
            "max_depth": trial.suggest_int(f"{prefix}_max_depth", 3, 10),
            "min_samples_leaf": trial.suggest_int(f"{prefix}_min_samples_leaf", 2, 30),
        }
    if family == "lightgbm":
        return {
            "n_estimators": trial.suggest_int(f"{prefix}_n_estimators", 100, 400, step=100),
            "max_depth": trial.suggest_int(f"{prefix}_max_depth", 3, 8),
            "learning_rate": trial.suggest_float(f"{prefix}_learning_rate", 1e-2, 3e-1, log=True),
            "min_samples_leaf": trial.suggest_int(f"{prefix}_min_samples_leaf", 5, 50),
        }
    raise ValueError(f"Unknown family: {family!r}")


def sample_trial(trial: optuna.Trial, spec: SearchSpaceSpec) -> TrialConfig:
    """Sample a TrialConfig from the search space spec.

    Feature groups are sampled with an at-least-one constraint: if all toggles
    came up False, we force ``technical`` on. If ``spec.feature_groups_force``
    is set (Phase 0c), the per-group toggles are pinned to that fixed tuple.
    """
    if spec.feature_groups_force is not None:
        forced = set(spec.feature_groups_force)
        flags = {g: (g in forced) for g in spec.feature_groups}
        # Record the forced toggles as Optuna parameters so trial replay is deterministic.
        for g in spec.feature_groups:
            trial.suggest_int(f"fg_{g}", int(flags[g]), int(flags[g]))
        sampled_groups = tuple(spec.feature_groups_force)
    else:
        flags = {g: bool(trial.suggest_int(f"fg_{g}", 0, 1)) for g in spec.feature_groups}
        if not any(flags.values()):
            flags["technical"] = True
        sampled_groups = tuple(g for g in spec.feature_groups if flags[g])

    normalization = trial.suggest_categorical("normalization", list(spec.normalizations))
    atr_m = trial.suggest_float("target_atr_multiple", spec.atr_multiple_low, spec.atr_multiple_high)

    family_spot = trial.suggest_categorical("family_spot", list(spec.candidate_families))
    family_mom = trial.suggest_categorical("family_mom", list(spec.candidate_families))
    family_fund = trial.suggest_categorical("family_fund", list(spec.candidate_families))

    hp_spot = _sample_hp(trial, "spot", family_spot)
    hp_mom = _sample_hp(trial, "mom", family_mom)
    hp_fund = _sample_hp(trial, "fund", family_fund)

    meta_family = trial.suggest_categorical("meta_family", list(spec.meta_families))
    meta_hp = _sample_hp(trial, "meta", meta_family)

    tau_conf = trial.suggest_float("tau_conf", spec.tau_conf_low, spec.tau_conf_high)
    tau_diss = trial.suggest_float("tau_diss", spec.tau_diss_low, spec.tau_diss_high)

    return TrialConfig(
        feature_groups=sampled_groups,
        normalization=normalization,  # type: ignore[arg-type]
        target_atr_multiple=atr_m,
        base_family_spot=family_spot,  # type: ignore[arg-type]
        base_family_mom=family_mom,  # type: ignore[arg-type]
        base_family_fund=family_fund,  # type: ignore[arg-type]
        base_hp_spot=hp_spot,
        base_hp_mom=hp_mom,
        base_hp_fund=hp_fund,
        meta_family=meta_family,  # type: ignore[arg-type]
        meta_hp=meta_hp,
        tau_conf=tau_conf,
        tau_diss=tau_diss,
        horizon=spec.horizon,
    )
