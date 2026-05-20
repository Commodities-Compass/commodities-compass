"""Training utilities: anti-bias sample weights, threshold tuning, regime filtering.

These modules patch the SklearnCandidate training pipeline without touching the
upstream framework. Each function is pure and unit-testable.
"""

from ensemble.training_utils.anti_bias import (
    balanced_class_weight,
    composed_sample_weights,
    recency_decay_weights,
)

__all__ = [
    "balanced_class_weight",
    "recency_decay_weights",
    "composed_sample_weights",
]
