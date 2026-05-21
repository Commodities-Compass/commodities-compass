"""Gate 1 — every shipped module must import cleanly.

Catches:
    - leftover ``from methodology.X import Y`` that survived the sed rename;
    - missing dependencies (e.g. a stripped module that another file still
      imports);
    - broken __init__.py exports.
"""

from __future__ import annotations

import importlib

import pytest


CORE_MODULES = [
    "ensemble.config",
    "ensemble.features",
    "ensemble.features_external",
    "ensemble.features_garch",
    "ensemble.features_maximal",
    "ensemble.targets",
    "ensemble.targets_calibrated",
    "ensemble.targets_triple_barrier",
    "ensemble.external_data",
    "ensemble.training_utils.anti_bias",
    "ensemble.models.base",
    "ensemble.models.sklearn_candidate",
    "ensemble.models.spot",
    "ensemble.models.momentum",
    "ensemble.models.fundamentals",
    "ensemble.models.meta",
    "ensemble.optimizer",
    "ensemble.optimizer.specialists",
    "ensemble.optimizer.objective",
    "ensemble.optimizer.search_space",
    "ensemble.optimizer.regularization",
    "ensemble.long_run",
    "ensemble.long_run.anomaly_veto",
    "ensemble.long_run.structural_priors",
    "ensemble.long_run.regime_similarity",
    "ensemble.macro_events.pipeline",
    "ensemble.orchestrator",
    "ensemble.orchestrator.soft_gate",
    "ensemble.orchestrator.transition_wrapper",
    "ensemble.retrain.monthly_retrainer",
    "ensemble.evaluation.metrics",
    "ensemble.evaluation.bootstrap",
    "ensemble.evaluation.stratification",
    # New deliverable modules
    "ensemble.artifact_io",
    "ensemble.data_loader_protocol",
    "ensemble.ensemble_pipeline",
]


@pytest.mark.unit
@pytest.mark.parametrize("module_name", CORE_MODULES)
def test_module_imports(module_name: str) -> None:
    importlib.import_module(module_name)


@pytest.mark.unit
def test_optimizer_does_not_reexport_build_objective() -> None:
    """build_objective + run_study are R&D-only; prod must not see them."""
    import ensemble.optimizer as opt

    assert not hasattr(opt, "build_objective"), \
        "optimizer.build_objective leaked into the prod package (depends on excluded validation.walk_forward)"
    assert not hasattr(opt, "run_study"), \
        "optimizer.run_study leaked into the prod package (Optuna studies are R&D-only)"


@pytest.mark.unit
def test_orchestrator_does_not_export_learned_moe() -> None:
    """The failed Phase 5 learned-MoE (`ME-001`) must not be in the deliverable."""
    import ensemble.orchestrator as orch

    assert not hasattr(orch, "LearnedMoEOrchestrator"), \
        "learned_moe imports survived the cut — ME-001 says ship without it"
