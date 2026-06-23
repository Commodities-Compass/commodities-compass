"""Penalty composition for the optimizer objective.

Defined as pure functions so they can be unit-tested without Optuna.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PenaltyConfig:
    ci_includes_zero_penalty: float = 1.0
    cv_regime_threshold: float = 0.30
    cv_regime_weight: float = 2.0
    coverage_min: float = 0.50
    coverage_weight: float = 2.0
    is_oos_gap_max: float = 0.20
    is_oos_gap_weight: float = 1.0


@dataclass(frozen=True)
class PenaltyTerms:
    ci_includes_zero: float
    cv_regime: float
    coverage: float
    is_oos_gap: float

    @property
    def total(self) -> float:
        return self.ci_includes_zero + self.cv_regime + self.coverage + self.is_oos_gap


def compute_penalties(
    *,
    ci_low_oos: float,
    ci_high_oos: float,
    cv_regime: float,
    coverage_oos: float,
    is_eff: float,
    oos_eff: float,
    config: PenaltyConfig | None = None,
) -> PenaltyTerms:
    cfg = config or PenaltyConfig()
    ci_inc_zero = (
        cfg.ci_includes_zero_penalty
        if (ci_low_oos is not None and ci_high_oos is not None and ci_low_oos <= 0.0 <= ci_high_oos)
        else 0.0
    )
    cv_term = (
        cfg.cv_regime_weight * max(0.0, cv_regime - cfg.cv_regime_threshold)
        if cv_regime != float("inf")
        else cfg.cv_regime_weight * 1.0
    )
    cov_term = cfg.coverage_weight * max(0.0, cfg.coverage_min - coverage_oos)
    if abs(is_eff) > 1e-9:
        gap = (is_eff - oos_eff) / abs(is_eff)
    else:
        gap = 0.0
    gap_term = cfg.is_oos_gap_weight * max(0.0, min(1.0, gap - cfg.is_oos_gap_max))
    return PenaltyTerms(
        ci_includes_zero=ci_inc_zero,
        cv_regime=cv_term,
        coverage=cov_term,
        is_oos_gap=gap_term,
    )


def objective_value(oos_eff: float, penalties: PenaltyTerms) -> float:
    """Maximization target."""
    return float(oos_eff) - float(penalties.total)
