"""Spot (range/mean-reversion) candidates. Spec §4.5."""

from __future__ import annotations

from typing import Any

from ensemble.features import SPOT_FEATURES
from ensemble.models.sklearn_candidate import SklearnCandidate


def SpotLogistic(*, hp: dict[str, Any] | None = None, random_state: int = 42) -> SklearnCandidate:
    return SklearnCandidate(
        name="spot_logistic",
        feature_specs=SPOT_FEATURES,
        feature_group="spot",
        family="logistic",
        hp=hp,
        random_state=random_state,
    )


def SpotRandomForest(*, hp: dict[str, Any] | None = None, random_state: int = 42) -> SklearnCandidate:
    return SklearnCandidate(
        name="spot_random_forest",
        feature_specs=SPOT_FEATURES,
        feature_group="spot",
        family="random_forest",
        hp=hp,
        random_state=random_state,
    )


def SpotGBM(*, hp: dict[str, Any] | None = None, random_state: int = 42) -> SklearnCandidate:
    return SklearnCandidate(
        name="spot_gbm",
        feature_specs=SPOT_FEATURES,
        feature_group="spot",
        family="lightgbm",
        hp=hp,
        random_state=random_state,
    )
