"""Campaign 4 Phase 4-5 orchestrator layer (production deliverable).

Combines:
    - 14 specialist per-day predictions (Phase 1 monthly retrains).
    - Anomaly score (Phase 2) as informative feature (NOT veto per `AV-001`).
    - Structural priors (Phase 2) for Bayesian update of specialist confidence.
    - Macro events (Phase 3) for bear-aligned amplify (bull leg disabled by MAC-002).
    - Regime-similarity weights (Phase 3.5) — near-constant on Jan-Apr 2026 window per `RS-001`.

Variant A — SoftGateOrchestrator (Bayesian factor composition).
Wrapped by TransitionProtectionWrapper (Campaign 5 Step 1 winning meta-gate, `TPW-001`).

The learned-MoE variant (Phase 5) is NOT included in this deliverable per `ME-001`
(failed validation: 51.2% global, Apr collapse).
"""

from ensemble.orchestrator.soft_gate import (
    OrchestratorContext,
    OrchestratorDecision,
    SoftGateConfig,
    SoftGateOrchestrator,
    select_best_window_per_specialist,
)
from ensemble.orchestrator.transition_wrapper import (
    TransitionProtectionWrapper,
    WrapperConfig,
)

__all__ = [
    "OrchestratorContext",
    "OrchestratorDecision",
    "SoftGateConfig",
    "SoftGateOrchestrator",
    "select_best_window_per_specialist",
    "TransitionProtectionWrapper",
    "WrapperConfig",
]
