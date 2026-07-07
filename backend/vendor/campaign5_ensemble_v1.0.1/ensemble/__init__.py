"""Compass methodology framework.

Implements the spec in methodology/framework-spec.md:
- data_loader, targets, features (data layer)
- models.base, models.baselines, models.spot, models.momentum, models.fundamentals, models.meta
- evaluation (metrics, bootstrap, stratification, stat_tests)
- validation (walk_forward, bias_checks, sensitivity)
- reports (experiment_report)
- optimizer (search_space, objective, study)

Reproducibility (CLAUDE.md non-negotiable):
- Module-level RNG seeded at 42
- All estimators must accept and set random_state=42
- bootstrap, walk-forward, optimizer all seeded
"""

from __future__ import annotations

import numpy as np

__version__ = "0.1.0"

SEED: int = 42
RNG: np.random.Generator = np.random.default_rng(seed=SEED)
