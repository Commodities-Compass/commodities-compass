"""Monthly retrain layer — Campaign 4 Phase 1.

Trains each specialist on a rolling N-month window ending just before the
prediction month, instead of on the full 2016-2025 window. Tests whether
recent-regime training improves cross-month accuracy on 2026.

User-mandated class-balance preservation (2026-05-17): for window_months >= 6,
anti-bias is FORCED ON regardless of the specialist's Phase 0c spec.
"""

from ensemble.retrain.monthly_retrainer import (
    MonthlyRetrainer,
    MonthlyRetrainResult,
    SpecialistWindowConfig,
)

__all__ = [
    "MonthlyRetrainer",
    "MonthlyRetrainResult",
    "SpecialistWindowConfig",
]
