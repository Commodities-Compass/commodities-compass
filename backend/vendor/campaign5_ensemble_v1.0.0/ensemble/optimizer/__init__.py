"""Optimizer package (production-side subset).

Only exports the pieces needed at inference / monthly retrain time:
    - SPECIALISTS registry + SpecialistArchitecture (resolves a top1_config to
      the trio of feature_specs / target_fn / sample_weight_fn).
    - SearchSpaceSpec / TrialConfig / sample_trial (TrialConfig reconstruction
      from a persisted top1_config.json — required by MonthlyRetrainer).
    - _build_candidate (factory used by MonthlyRetrainer.from_top1_path to
      rebuild Spot/Mom/Fund candidates from HPs).

R&D-only pieces are NOT re-exported:
    - build_objective / _evaluate_config (Optuna walk-forward trial runner —
      depends on ensemble.validation.walk_forward, excluded from this package).
    - run_study (Optuna study driver; prod does not run sweeps directly).
"""

from ensemble.optimizer.objective import _build_candidate
from ensemble.optimizer.search_space import SearchSpaceSpec, TrialConfig, sample_trial
from ensemble.optimizer.specialists import (
    SPECIALISTS,
    SpecialistArchitecture,
    specialists_by_name,
)

__all__ = [
    "SearchSpaceSpec",
    "TrialConfig",
    "sample_trial",
    "_build_candidate",
    "SPECIALISTS",
    "SpecialistArchitecture",
    "specialists_by_name",
]
