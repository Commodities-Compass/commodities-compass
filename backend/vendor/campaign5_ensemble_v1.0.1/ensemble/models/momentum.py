"""Momentum (trend/derivative) candidates. Spec §4.6."""

from __future__ import annotations

from typing import Any

from ensemble.features import MOMENTUM_FEATURES
from ensemble.models.sklearn_candidate import SklearnCandidate


def MomentumLogistic(*, hp: dict[str, Any] | None = None, random_state: int = 42) -> SklearnCandidate:
    return SklearnCandidate(
        name="momentum_logistic",
        feature_specs=MOMENTUM_FEATURES,
        feature_group="momentum",
        family="logistic",
        hp=hp,
        random_state=random_state,
    )


def MomentumRandomForest(*, hp: dict[str, Any] | None = None, random_state: int = 42) -> SklearnCandidate:
    return SklearnCandidate(
        name="momentum_random_forest",
        feature_specs=MOMENTUM_FEATURES,
        feature_group="momentum",
        family="random_forest",
        hp=hp,
        random_state=random_state,
    )


def MomentumGBM(*, hp: dict[str, Any] | None = None, random_state: int = 42) -> SklearnCandidate:
    return SklearnCandidate(
        name="momentum_gbm",
        feature_specs=MOMENTUM_FEATURES,
        feature_group="momentum",
        family="lightgbm",
        hp=hp,
        random_state=random_state,
    )
