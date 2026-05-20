"""SoftGateOrchestrator — Campaign 4 Phase 4 (variant A).

Bayesian factor-product combination of specialist votes:

    weight_i(t) = base_acc_i
                × (1 + α_macro × is_macro_aligned_i(t))
                × (1 + α_prior × is_prior_aligned_i(t))
                × (1 + α_anom  × anomaly_z_capped(t))      # capped at +2.5

    net_score(t) = Σ weight_i × vote_i(t) / Σ weight_i

    decision(t) =
        OPEN     if net_score >= commit_threshold
        HEDGE    if net_score <= -commit_threshold
        MONITOR  otherwise

Where:
    vote_i = +1 if specialist i predicts OPEN, -1 if HEDGE, 0 if MONITOR.
    base_acc_i = the rolling 30-day accuracy of specialist i (Phase 1 monthly_v2 supplies
        per-month accuracy; we use the cumulative-prior-months average leading up to t).
    is_macro_aligned_i =  +1 if macro direction matches specialist's vote, -1 if opposite, 0 if no event.
    is_prior_aligned_i =  +1 if specialist's vote agrees with the strongest prior class, 0 otherwise.
    anomaly_z_capped = anomaly_score_z clipped to [-2.5, +2.5]. AV-001 finding: HIGHER
        anomaly z correlated with HIGHER v1 accuracy, so the sign is POSITIVE not negative.

The 4 multipliers (α_macro, α_prior, α_anom, commit_threshold) are Optuna-tuned
on a held-out portion of the prediction window in the driver script.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
import json

import numpy as np
import pandas as pd

Decision = Literal["OPEN", "HEDGE", "MONITOR"]
DECISIONS: tuple[Decision, ...] = ("OPEN", "HEDGE", "MONITOR")
EPS: float = 1e-9


# ---------------------------------------------------------------------------
# Pool assembly
# ---------------------------------------------------------------------------
def select_best_window_per_specialist(
    monthly_v2: pd.DataFrame,
    *,
    coverage_clip: float = 0.50,
) -> dict[str, int]:
    """For each specialist, pick the window that maximises median_accuracy × min(coverage, coverage_clip).

    Returns dict {specialist_name: best_window_months}.
    """
    grouped = monthly_v2.groupby(["specialist_name", "window_months"]).agg(
        median_acc=("accuracy", lambda s: float(np.nanmedian(s))),
        mean_cov=("coverage", "mean"),
        n_total_committed=("n_committed", "sum"),
    ).reset_index()
    grouped["score"] = grouped["median_acc"] * np.minimum(grouped["mean_cov"], coverage_clip)
    grouped = grouped.dropna(subset=["score"])
    out: dict[str, int] = {}
    for name, sub in grouped.groupby("specialist_name"):
        if sub.empty:
            continue
        best = sub.sort_values(["score", "n_total_committed"], ascending=[False, False]).iloc[0]
        out[str(name)] = int(best["window_months"])
    return out


# ---------------------------------------------------------------------------
# Config and context dataclasses
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SoftGateConfig:
    """Tunable factor intensities + commit threshold. All non-negative."""
    alpha_macro: float = 0.5
    alpha_prior: float = 0.3
    alpha_anomaly: float = 0.2  # AV-001: positive sign (high anomaly z ≈ trust more)
    commit_threshold: float = 0.20
    anomaly_clip_abs: float = 2.5


@dataclass(frozen=True)
class OrchestratorContext:
    """All exogenous signals visible to the orchestrator on day t."""
    date: pd.Timestamp
    macro_direction: int          # {-1, 0, +1}
    macro_surprise: float         # [0, 1]
    macro_confidence: float       # [0, 1]
    prior_open: float
    prior_hedge: float
    prior_monitor: float
    anomaly_score_z: float        # per AV-001 we use this with POSITIVE sign
    cluster_weights: dict[int, float]   # regime-similarity cluster weights (RS-001)


@dataclass(frozen=True)
class OrchestratorDecision:
    """The orchestrator's output for one day, with full audit trail."""
    date: pd.Timestamp
    decision: Decision
    net_score: float
    n_committed_specialists: int
    weights_sum: float
    per_specialist_votes: dict[str, int]
    per_specialist_weights: dict[str, float]
    context: OrchestratorContext

    def to_dict(self) -> dict:
        return {
            "date": pd.Timestamp(self.date),
            "decision": str(self.decision),
            "net_score": float(self.net_score),
            "n_committed_specialists": int(self.n_committed_specialists),
            "weights_sum": float(self.weights_sum),
            "macro_direction": int(self.context.macro_direction),
            "macro_surprise": float(self.context.macro_surprise),
            "prior_open": float(self.context.prior_open),
            "prior_hedge": float(self.context.prior_hedge),
            "anomaly_score_z": float(self.context.anomaly_score_z),
        }


# ---------------------------------------------------------------------------
# Core orchestrator
# ---------------------------------------------------------------------------
class SoftGateOrchestrator:
    """Bayesian factor-product orchestrator (Phase 4)."""

    def __init__(
        self,
        config: SoftGateConfig | None = None,
        base_accuracy: dict[str, float] | None = None,
    ) -> None:
        self.config: SoftGateConfig = config or SoftGateConfig()
        # base_accuracy: per-specialist running accuracy on prior committed days.
        # If None, the orchestrator falls back to uniform weight 1.0 per specialist.
        self.base_accuracy: dict[str, float] = dict(base_accuracy or {})

    # ------------------------------------------------------------------
    # Vote helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _vote(pred: str) -> int:
        if pred == "OPEN":
            return +1
        if pred == "HEDGE":
            return -1
        return 0  # MONITOR

    def _base_weight(self, name: str) -> float:
        """Per-specialist base weight derived from running accuracy.

        Maps acc ∈ [0, 1] -> base_weight ∈ [0, 2]: 0.5 acc -> 1.0; 0.65 -> 1.30; 0.85 -> 1.70.
        Specialists with no history yet get base_weight = 1.0 (neutral).
        """
        acc = float(self.base_accuracy.get(name, 0.5))
        # Linear: w = 1 + 2*(acc - 0.5). Clipped to [0, 2].
        return float(max(0.0, min(2.0, 1.0 + 2.0 * (acc - 0.5))))

    def _macro_alignment(self, vote: int, macro_direction: int) -> int:
        """Per-specialist signed macro alignment.

        +1 macro AND vote OPEN → aligned (+1).
        -1 macro AND vote HEDGE → aligned (+1).
        Opposite vote vs direction → anti-aligned (-1).
        No macro event OR specialist abstains → 0.
        """
        if macro_direction == 0 or vote == 0:
            return 0
        # vote +1 means OPEN (bull-side bet), macro +1 means bull news.
        return +1 if vote * macro_direction > 0 else -1

    @staticmethod
    def _prior_strongest_class(prior_open: float, prior_hedge: float, prior_monitor: float) -> int:
        """Returns the vote that matches the strongest-class prior:
        +1 if P(OPEN) is strongest, -1 if P(HEDGE), 0 if P(MONITOR).
        """
        if prior_open >= max(prior_hedge, prior_monitor):
            return +1
        if prior_hedge >= max(prior_open, prior_monitor):
            return -1
        return 0

    def _prior_alignment(self, vote: int, prior_open: float, prior_hedge: float, prior_monitor: float) -> int:
        """+1 if specialist's vote agrees with the strongest prior class, 0 otherwise.

        Note: NOT signed negatively when misaligned, because the prior here is mild
        (per `SP-001`, max bucket skew ±10pp). A misaligned vote is INFORMATIVE
        only weakly — we don't actively suppress it.
        """
        if vote == 0:
            return 0
        return 1 if vote == self._prior_strongest_class(prior_open, prior_hedge, prior_monitor) else 0

    # ------------------------------------------------------------------
    # Decision
    # ------------------------------------------------------------------
    def decide(
        self,
        specialist_votes: dict[str, str],   # {specialist_name -> "OPEN"|"HEDGE"|"MONITOR"}
        context: OrchestratorContext,
    ) -> OrchestratorDecision:
        cfg = self.config
        anomaly_clipped = float(np.clip(context.anomaly_score_z, -cfg.anomaly_clip_abs, cfg.anomaly_clip_abs))

        per_w: dict[str, float] = {}
        per_v: dict[str, int] = {}
        weighted_sum = 0.0
        weight_total = 0.0
        n_committed = 0
        for name, pred in specialist_votes.items():
            vote = self._vote(pred)
            per_v[name] = vote
            if vote == 0:
                # Abstention: contributes 0 to the score but the specialist's
                # weight is also 0 in the denominator — they sit out today.
                per_w[name] = 0.0
                continue
            n_committed += 1
            base = self._base_weight(name)
            macro_align = self._macro_alignment(vote, context.macro_direction)
            prior_align = self._prior_alignment(vote, context.prior_open, context.prior_hedge, context.prior_monitor)
            # AV-001: positive sign on anomaly — higher z → trust more.
            anomaly_term = 1.0 + cfg.alpha_anomaly * anomaly_clipped
            anomaly_term = max(0.0, anomaly_term)  # don't allow negative weights
            weight = (
                base
                * (1.0 + cfg.alpha_macro * macro_align)
                * (1.0 + cfg.alpha_prior * prior_align)
                * anomaly_term
            )
            weight = max(0.0, weight)
            per_w[name] = weight
            weighted_sum += weight * vote
            weight_total += weight

        if weight_total <= EPS or n_committed == 0:
            net_score = 0.0
        else:
            net_score = float(weighted_sum / weight_total)

        if net_score >= cfg.commit_threshold:
            decision: Decision = "OPEN"
        elif net_score <= -cfg.commit_threshold:
            decision = "HEDGE"
        else:
            decision = "MONITOR"

        return OrchestratorDecision(
            date=pd.Timestamp(context.date),
            decision=decision,
            net_score=net_score,
            n_committed_specialists=n_committed,
            weights_sum=weight_total,
            per_specialist_votes=dict(per_v),
            per_specialist_weights=dict(per_w),
            context=context,
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def save_config(self, path: Path) -> None:
        path.write_text(
            json.dumps(
                {
                    "config": self.config.__dict__,
                    "base_accuracy": dict(self.base_accuracy),
                },
                indent=2,
            )
        )
