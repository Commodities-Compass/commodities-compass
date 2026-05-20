"""Candidate factory (production-side subset).

The R&D version of this module also defined ``_evaluate_config`` and
``build_objective`` — the Optuna walk-forward trial runner. Those depend on
``ensemble.validation.walk_forward`` which is intentionally NOT shipped in the
production package (rule §2.5 of the R&D deliverable plan: ``methodology/
validation/`` is R&D-only). Production code never runs Optuna sweeps; it loads
persisted top1_config.json files via ``MonthlyRetrainer.from_top1_path`` which
calls ``_build_candidate`` directly.

Exports retained for production:
    - ``SPOT_FACTORIES`` / ``MOM_FACTORIES`` / ``FUND_FACTORIES`` — factory
      registries consumed by ``MonthlyRetrainer`` and ``tools/freeze_artifacts.py``.
    - ``_build_candidate`` — rebuilds a SklearnCandidate from a family name +
      HP dict + feature_specs override.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ensemble.features import FeatureSpec
from ensemble.models.base import CandidateModel
from ensemble.models.fundamentals import FundGBM, FundLogistic, FundRandomForest
from ensemble.models.momentum import MomentumGBM, MomentumLogistic, MomentumRandomForest
from ensemble.models.spot import SpotGBM, SpotLogistic, SpotRandomForest


SPOT_FACTORIES: dict[str, Callable[..., CandidateModel]] = {
    "logistic": SpotLogistic,
    "random_forest": SpotRandomForest,
    "lightgbm": SpotGBM,
}
MOM_FACTORIES: dict[str, Callable[..., CandidateModel]] = {
    "logistic": MomentumLogistic,
    "random_forest": MomentumRandomForest,
    "lightgbm": MomentumGBM,
}
FUND_FACTORIES: dict[str, Callable[..., CandidateModel]] = {
    "logistic": FundLogistic,
    "random_forest": FundRandomForest,
    "lightgbm": FundGBM,
}


def _build_candidate(
    factory_map: dict[str, Callable[..., CandidateModel]],
    family: str,
    feature_specs: list[FeatureSpec],
    hp: dict[str, Any],
    random_state: int,
) -> CandidateModel:
    """Construct a SklearnCandidate via the factory and override its feature_specs.

    Mirrors the R&D objective's _build_candidate contract: the factory wraps a
    sklearn-style estimator with a default feature spec list; we replace that
    list with the (possibly specialist-pinned) feature_specs for the trial /
    refit.
    """
    fn = factory_map[family]
    cand = fn(hp=hp, random_state=random_state)
    cand._feature_specs = tuple(feature_specs)  # type: ignore[attr-defined]
    return cand
