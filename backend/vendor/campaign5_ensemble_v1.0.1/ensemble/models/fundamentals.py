"""Fundamentals candidates (COT + sentiment + procurement ops). Spec §4.6 placeholder."""

from __future__ import annotations

from typing import Any

from ensemble.features import FUNDAMENTAL_FEATURES
from ensemble.models.sklearn_candidate import SklearnCandidate


def FundLogistic(*, hp: dict[str, Any] | None = None, random_state: int = 42) -> SklearnCandidate:
    return SklearnCandidate(
        name="fundamentals_logistic",
        feature_specs=FUNDAMENTAL_FEATURES,
        feature_group="fundamental",
        family="logistic",
        hp=hp,
        random_state=random_state,
        fill_max_null=0.85,  # fundamentals are sparser
    )


def FundRandomForest(*, hp: dict[str, Any] | None = None, random_state: int = 42) -> SklearnCandidate:
    return SklearnCandidate(
        name="fundamentals_random_forest",
        feature_specs=FUNDAMENTAL_FEATURES,
        feature_group="fundamental",
        family="random_forest",
        hp=hp,
        random_state=random_state,
        fill_max_null=0.85,
    )


def FundGBM(*, hp: dict[str, Any] | None = None, random_state: int = 42) -> SklearnCandidate:
    return SklearnCandidate(
        name="fundamentals_gbm",
        feature_specs=FUNDAMENTAL_FEATURES,
        feature_group="fundamental",
        family="lightgbm",
        hp=hp,
        random_state=random_state,
        fill_max_null=0.85,
    )
