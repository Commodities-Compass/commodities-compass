"""Top-level Campaign 5 ensemble entry point.

``EnsemblePipeline.from_loader(loader, training_month)`` reads all 19+
artifacts from a backing store (DB or frozen dir), reconstructs the live
objects, and exposes ``.decide(request)`` — the single function prod calls
once per day.

Layer composition (Campaign 5 v1.0.0):

    1. 14 specialists (Phase 0c top1 configs, fit by the freezer at
       TRAINING_CUTOFF) — produce per-specialist votes for today.
    2. AnomalyVetoModel — emits today's z-scored anomaly (AV-001: positive
       sign, higher z ≈ trust more, NOT a veto).
    3. StructuralPriors — empirical-Bayes prior over (regime, 12m_vol,
       12m_ret) buckets. Falls back to global_prior when today's date is
       beyond the regime_tags coverage (expected for prod days post-cutoff).
    4. RegimeSimilarityModel — softmax cluster weights for the current month
       (RS-001: near-constant on Jan-Apr 2026; informational only — does not
       feed the soft-gate decision in v1.0.0).
    5. SoftGateOrchestrator (Fold B params per EXP-OPTIM-024 sensitivity) —
       Bayesian factor-product over specialist weights.
    6. TransitionProtectionWrapper (TPW-001) — running_acc + cluster_dispersion
       detectors override the soft-gate decision when fired. The wrapper is
       BATCH (consumes trailing window + today); the pipeline appends today's
       row to the prod-provided trailing window and takes the last row of the
       wrapped output.

Day-1 bootstrap responsibility: prod pre-seeds ``pl_orchestrator_decision``
with 5 R&D historical rows so the wrapper's ``running_acc`` detector has
enough trailing committed days to fire. See deployment plan §6.2.
"""

from __future__ import annotations

import json
import pickle
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from ensemble.artifact_io import (
    ArtifactLoader,
    load_json,
    load_pickle,
)
from ensemble.data_loader_protocol import DecideRequest, MacroSignal
from ensemble.long_run.anomaly_veto import AnomalyVetoModel
from ensemble.long_run.regime_similarity import RegimeSimilarityModel
from ensemble.long_run.structural_priors import PriorContext, StructuralPriors
from ensemble.orchestrator.soft_gate import (
    OrchestratorContext,
    OrchestratorDecision,
    SoftGateConfig,
    SoftGateOrchestrator,
)
from ensemble.orchestrator.transition_wrapper import (
    DEFAULT_CLUSTER_MAPPING,
    TransitionProtectionWrapper,
    WrapperConfig,
)


# ---------------------------------------------------------------------------
# Decision struct prod writes back to all 3 tables
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class EnsembleDecision:
    """The pipeline's output for one day.

    Prod writes the relevant slices to:
        - ``pl_specialist_prediction`` (one row per name in ``per_specialist_votes``).
        - ``pl_orchestrator_decision`` (one row with ``soft_gate_decision`` +
          ``wrapped_decision`` + the diagnostic columns).
        - ``pl_indicator_daily`` (the live trade decision = ``wrapped_decision``).
    """

    today: pd.Timestamp
    contract_id: str
    # Soft-gate layer
    soft_gate_decision: OrchestratorDecision
    per_specialist_votes: dict[str, str]
    # Wrapper layer
    wrapped_decision: str            # "OPEN" | "HEDGE" | "MONITOR"
    wrapper_fired_running_acc: bool
    wrapper_fired_cluster_dispersion: bool
    wrapper_fired_trend: bool            # v1.0.1 §9.9 — was dropped (hardcoded False prod-side)
    wrapper_fired_three_way: bool        # v1.0.1 §9.9
    # Soft-gate weight diagnostics — needed for the §6 decision-collapse metric
    weights_sum: float                   # v1.0.1 §9.9 — Σ committed-specialist weights
    n_committed_specialists: int         # v1.0.1 §9.9
    # Diagnostics (always populated, even when no detector fired)
    running_acc_5d: float
    realized_return_5d: float
    winter_vote_signed: int
    spring_vote_signed: int


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
class EnsemblePipeline:
    """Assembled production ensemble. Construct via ``from_loader``."""

    def __init__(
        self,
        specialists: dict[str, Any],
        anomaly_veto: AnomalyVetoModel,
        structural_priors: StructuralPriors,
        regime_similarity: RegimeSimilarityModel,
        soft_gate: SoftGateOrchestrator,
        wrapper: TransitionProtectionWrapper,
        regime_tags: pd.DataFrame,
    ) -> None:
        self.specialists = specialists
        self.anomaly_veto = anomaly_veto
        self.structural_priors = structural_priors
        self.regime_similarity = regime_similarity
        self.soft_gate = soft_gate
        self.wrapper = wrapper
        self.regime_tags = regime_tags.copy()
        self.regime_tags["date"] = pd.to_datetime(self.regime_tags["date"])

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    @classmethod
    def from_loader(
        cls,
        loader: ArtifactLoader,
        training_month: str,
        *,
        specialist_names: tuple[str, ...] | None = None,
        cluster_mapping: dict[str, str] | None = None,
    ) -> "EnsemblePipeline":
        """Reconstruct the pipeline from a backing artifact store.

        Args:
            loader: ``DBArtifactLoader`` (prod) or ``FrozenDirLoader`` (R&D / tests).
            training_month: 'YYYY-MM' — which monthly retrain to load specialists from.
            specialist_names: explicit name list; defaults to the keys of
                ``cluster_mapping`` (or ``DEFAULT_CLUSTER_MAPPING``).
            cluster_mapping: specialist_name -> 'winter'|'spring'. Production must
                pass the mapping loaded from ``pl_algorithm_config`` (rule §0 #5);
                the default mapping is shipped for R&D tests only.
        """
        mapping = dict(cluster_mapping or DEFAULT_CLUSTER_MAPPING)
        names = tuple(specialist_names or sorted(mapping.keys()))

        # 1) specialists --------------------------------------------------
        specialists: dict[str, Any] = {}
        for name in names:
            specialists[name] = load_pickle(loader, "specialist_model", name, training_month)

        # 2) long-run -----------------------------------------------------
        anomaly_payload = pickle.loads(
            loader.load("long_run_anomaly", "anomaly_veto_10y", None).payload
        )
        anomaly = AnomalyVetoModel.from_payload(anomaly_payload)

        priors_payload = json.loads(
            loader.load("long_run_priors", "structural_priors_10y", None).payload.decode("utf-8")
        )
        priors = StructuralPriors.from_payload(priors_payload)

        regime_sim_payload = json.loads(
            loader.load("long_run_regime_clusters", "regime_clusters_10y", None).payload.decode("utf-8")
        )
        regime_sim = RegimeSimilarityModel.from_payload(regime_sim_payload)

        # 3) tuned configs ------------------------------------------------
        soft_gate_cfg_dict = load_json(loader, "soft_gate_config", "softgate_v1_foldB", None)
        soft_gate = SoftGateOrchestrator(config=SoftGateConfig(**soft_gate_cfg_dict))

        wrapper_cfg_dict = load_json(loader, "wrapper_config", "tpw_v1", None)
        wrapper = TransitionProtectionWrapper(
            config=WrapperConfig(**wrapper_cfg_dict),
            cluster_mapping=mapping,
        )

        # 4) regime_tags snapshot (canonical reference data) -------------
        regime_tags_rec = loader.load("canonical_snapshot", _regime_tags_artifact_name(loader), None)
        regime_tags = pd.read_csv(pd.io.common.BytesIO(regime_tags_rec.payload))

        return cls(
            specialists=specialists,
            anomaly_veto=anomaly,
            structural_priors=priors,
            regime_similarity=regime_sim,
            soft_gate=soft_gate,
            wrapper=wrapper,
            regime_tags=regime_tags,
        )

    # ------------------------------------------------------------------
    # Decision
    # ------------------------------------------------------------------
    def decide(self, request: DecideRequest) -> EnsembleDecision:
        """Produce today's wrapped decision.

        Steps:
            1. Run all 14 specialists on ``market_history`` (take last row's pred).
            2. Compute anomaly z-score, priors, cluster weights for today.
            3. Build ``OrchestratorContext`` + run ``SoftGateOrchestrator``.
            4. Append today's row to ``recent_decisions`` + ``recent_votes``,
               build trailing returns_series, run ``TransitionProtectionWrapper``,
               read the LAST row of the wrapped output.
        """
        today = pd.Timestamp(request.today).normalize()
        history = request.market_history.copy()
        history["date"] = pd.to_datetime(history["date"]).dt.normalize()
        history = history.sort_values("date").reset_index(drop=True)
        if today not in set(history["date"]):
            raise ValueError(
                f"today={today.date()} not present in market_history "
                f"({history['date'].min()} .. {history['date'].max()})"
            )

        # 1) Specialist votes for today --------------------------------------
        votes: dict[str, str] = {}
        for name, cand in self.specialists.items():
            preds = cand.predict_label(history)
            votes[name] = str(preds.iloc[-1] if hasattr(preds, "iloc") else preds[-1])

        # 2) Anomaly z, priors, cluster weights ------------------------------
        anomaly_z = float(self.anomaly_veto.anomaly_score(history)[-1])

        priors_dict = self._priors_for_today(history, today)
        cluster_weights = self._cluster_weights_for_today(history, today)

        # 3) Soft-gate decision ----------------------------------------------
        context = OrchestratorContext(
            date=today,
            macro_direction=int(request.macro.direction),
            macro_surprise=float(request.macro.surprise),
            macro_confidence=float(request.macro.confidence),
            prior_open=float(priors_dict["OPEN"]),
            prior_hedge=float(priors_dict["HEDGE"]),
            prior_monitor=float(priors_dict["MONITOR"]),
            anomaly_score_z=anomaly_z,
            cluster_weights=cluster_weights,
        )
        soft_decision = self.soft_gate.decide(votes, context)

        # 4) Wrapper (batch over trailing window + today) --------------------
        wrapped, diag = self._apply_wrapper(
            soft_decision=soft_decision,
            today=today,
            history=history,
            recent_decisions=request.recent_decisions,
            recent_votes=request.recent_votes,
            votes=votes,
        )

        return EnsembleDecision(
            today=today,
            contract_id=str(request.contract_id),
            soft_gate_decision=soft_decision,
            per_specialist_votes=dict(votes),
            wrapped_decision=wrapped,
            wrapper_fired_running_acc=bool(diag.get("fired_running_acc", False)),
            wrapper_fired_cluster_dispersion=bool(diag.get("fired_dispersion", False)),
            wrapper_fired_trend=bool(diag.get("fired_trend", False)),
            wrapper_fired_three_way=bool(diag.get("fired_three_way", False)),
            weights_sum=float(soft_decision.weights_sum),
            n_committed_specialists=int(soft_decision.n_committed_specialists),
            running_acc_5d=float(diag.get("running_acc_5d", float("nan"))),
            realized_return_5d=float(diag.get("realized_return_5d", float("nan"))),
            winter_vote_signed=int(diag.get("winter_vote_signed", 0)),
            spring_vote_signed=int(diag.get("spring_vote_signed", 0)),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _priors_for_today(self, history: pd.DataFrame, today: pd.Timestamp) -> dict[str, float]:
        """Compute today's (P(OPEN), P(HEDGE), P(MONITOR)).

        Uses ``structural_priors.attach_priors`` which derives the (regime,
        vol_tercile, ret_tercile) bucket from rolling 12m vol/return on
        ``daily_return``. If today's date is outside ``regime_tags`` coverage
        (expected post-cutoff), the implementation falls back to global_prior.
        """
        # Pass the trailing window so vol/return terciles can be computed,
        # but only ask attach_priors about today.
        try:
            attached = self.structural_priors.attach_priors(
                history.tail(260),  # enough for the 252-day rolling window
                self.regime_tags,
            )
            row = attached[attached["date"] == today]
            if not row.empty:
                return {
                    "OPEN": float(row["prior_open"].iloc[-1]),
                    "HEDGE": float(row["prior_hedge"].iloc[-1]),
                    "MONITOR": float(row["prior_monitor"].iloc[-1]),
                }
        except (KeyError, ValueError):
            pass
        # Fall back to global prior — the soft-gate's prior_alignment factor
        # becomes uninformative, which is fine: the soft-gate still has macro
        # + anomaly + base accuracy to score on.
        return {"OPEN": 1 / 3, "HEDGE": 1 / 3, "MONITOR": 1 / 3}

    def _cluster_weights_for_today(
        self, history: pd.DataFrame, today: pd.Timestamp
    ) -> dict[int, float]:
        """Take this month's softmax cluster weights from regime_similarity.

        Per RS-001 the weights are near-constant across Jan-Apr 2026, so the
        soft-gate doesn't use them today. Populated anyway for the audit row
        in ``pl_orchestrator_decision``.
        """
        try:
            weights_df = self.regime_similarity.cluster_weights(history.tail(260), self.regime_tags)
            if weights_df.empty:
                return {}
            last = weights_df.iloc[-1]
            return {
                int(col.split("_")[1]): float(last[col])
                for col in weights_df.columns
                if col.startswith("cluster_") and col.endswith("_weight")
            }
        except (KeyError, ValueError, RuntimeError):
            return {}

    def _apply_wrapper(
        self,
        *,
        soft_decision: OrchestratorDecision,
        today: pd.Timestamp,
        history: pd.DataFrame,
        recent_decisions: pd.DataFrame,
        recent_votes: pd.DataFrame,
        votes: dict[str, str],
    ) -> tuple[str, dict[str, Any]]:
        """Glue layer: append today to trailing decisions + votes, run the
        wrapper batch, extract today's row.
        """
        # Build today's decision row in the schema TransitionProtectionWrapper.apply expects
        today_row = {
            "date": today,
            "decision": soft_decision.decision,
            "net_score": soft_decision.net_score,
            "macro_direction": soft_decision.context.macro_direction,
            "prior_open": soft_decision.context.prior_open,
            "prior_hedge": soft_decision.context.prior_hedge,
            "prior_monitor": soft_decision.context.prior_monitor,
            # For TODAY, committed status is known (decision != MONITOR) but
            # correctness is unknown (no forward return yet). The wrapper's
            # running_acc detector only reads PRIOR rows, so today's correct=NaN
            # is harmless.
            "committed": soft_decision.decision != "MONITOR",
            "correct": False,
        }
        decisions_df = pd.concat(
            [recent_decisions, pd.DataFrame([today_row])],
            ignore_index=True,
        )

        # Build votes_long: prepend prior + today's per-specialist rows
        today_votes = pd.DataFrame([
            {"date": today, "specialist_name": name, "pred": pred}
            for name, pred in votes.items()
        ])
        votes_long = pd.concat([recent_votes, today_votes], ignore_index=True)

        # Daily-return series for the trend detector — defensive in case it's disabled
        if "daily_return" in history.columns:
            returns_series = pd.Series(
                history["daily_return"].astype(float).values,
                index=pd.to_datetime(history["date"]).values,
            )
        else:
            returns_series = pd.Series(dtype=float)

        wrapped_df, diag_df = self.wrapper.apply(decisions_df, votes_long, returns_series)
        last = wrapped_df[pd.to_datetime(wrapped_df["date"]) == today]
        if last.empty:
            raise RuntimeError(
                f"wrapper.apply did not emit a row for today={today.date()}; "
                f"emitted {len(wrapped_df)} rows total"
            )
        wrapped_decision = str(last["decision_wrapped"].iloc[-1])

        diag_last = diag_df[pd.to_datetime(diag_df["date"]) == today]
        diag_dict: dict[str, Any] = {}
        if not diag_last.empty:
            diag_dict = diag_last.iloc[-1].to_dict()
        return wrapped_decision, diag_dict


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------
def _regime_tags_artifact_name(loader: ArtifactLoader) -> str:
    """Probe ``loader`` for the regime_tags canonical_snapshot row.

    The name is dated ('regime_tags_rd_2026-04-30'); we don't hardcode the date
    here — the freezer emits it from ``TRAINING_CUTOFF``. Instead, the loader
    is expected to expose a manifest-style index OR we fall back to the
    canonical default.
    """
    # When using FrozenDirLoader, the manifest is parsed at construction; use
    # its _index to find the regime_tags row. For DBArtifactLoader, we don't
    # have a manifest, so prod must pass the explicit name via
    # ``EnsemblePipeline`` construction overrides if the cutoff differs from
    # the v1.0.0 default.
    idx = getattr(loader, "_index", None)
    if isinstance(idx, dict):
        for kind, name, _tm in idx.keys():
            if kind == "canonical_snapshot" and name.startswith("regime_tags_rd_"):
                return name
    # DBArtifactLoader has no manifest index — discover the dated row from the DB
    # so a cutoff bump (v1.0.1 -> regime_tags_rd_2026-06-11) doesn't break prod.
    find = getattr(loader, "find_name", None)
    if callable(find):
        found = find("canonical_snapshot", "regime_tags_rd_")
        if found:
            return found
    return "regime_tags_rd_2026-04-30"
