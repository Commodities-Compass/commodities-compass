"""Write ``EnsembleDecision`` back to the 3 prod tables.

- ``pl_specialist_prediction``: 14 rows (one per specialist).
- ``pl_orchestrator_decision``: 1 row (soft-gate + wrapper + diagnostics).
- ``pl_indicator_daily``: 1 row UPDATE (mirrors wrapped_decision as the
  live trade signal). Created via INSERT if missing — the daily compute
  pipeline does not currently pre-seed `pl_indicator_daily` rows for the
  ensemble version, so this writer must be tolerant of the upsert case.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date as date_cls
from decimal import Decimal

from ensemble.ensemble_pipeline import EnsembleDecision
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class EnsembleWriterError(RuntimeError):
    """Raised on FK violations or pipeline-continuity rule breaches."""


_UPSERT_SPECIALIST = """
INSERT INTO pl_specialist_prediction (
    date, contract_id, algorithm_version_id,
    specialist_name, window_months, pred, n_features_used
)
VALUES (
    :date, :contract_id, :algorithm_version_id,
    :specialist_name, :window_months, :pred, NULL
)
ON CONFLICT ON CONSTRAINT uq_specialist_prediction DO UPDATE SET
    pred = EXCLUDED.pred,
    window_months = EXCLUDED.window_months
"""

_UPSERT_ORCHESTRATOR = """
INSERT INTO pl_orchestrator_decision (
    date, contract_id, algorithm_version_id,
    soft_gate_decision, net_score, weights_sum, n_committed_specialists,
    decision_wrapped, wrapper_active,
    fired_running_acc, fired_trend, fired_dispersion, fired_three_way,
    running_acc_5d, realized_return_5d,
    winter_vote_signed, spring_vote_signed,
    macro_direction, macro_surprise, macro_half_life_days,
    anomaly_score_z, prior_open, prior_hedge, prior_monitor
)
VALUES (
    :date, :contract_id, :algorithm_version_id,
    :soft_gate_decision, :net_score, :weights_sum, :n_committed_specialists,
    :decision_wrapped, :wrapper_active,
    :fired_running_acc, :fired_trend, :fired_dispersion, :fired_three_way,
    :running_acc_5d, :realized_return_5d,
    :winter_vote_signed, :spring_vote_signed,
    :macro_direction, :macro_surprise, :macro_half_life_days,
    :anomaly_score_z, :prior_open, :prior_hedge, :prior_monitor
)
ON CONFLICT ON CONSTRAINT uq_orchestrator_decision DO UPDATE SET
    soft_gate_decision = EXCLUDED.soft_gate_decision,
    net_score = EXCLUDED.net_score,
    weights_sum = EXCLUDED.weights_sum,
    n_committed_specialists = EXCLUDED.n_committed_specialists,
    decision_wrapped = EXCLUDED.decision_wrapped,
    wrapper_active = EXCLUDED.wrapper_active,
    fired_running_acc = EXCLUDED.fired_running_acc,
    fired_trend = EXCLUDED.fired_trend,
    fired_dispersion = EXCLUDED.fired_dispersion,
    fired_three_way = EXCLUDED.fired_three_way,
    running_acc_5d = EXCLUDED.running_acc_5d,
    realized_return_5d = EXCLUDED.realized_return_5d,
    winter_vote_signed = EXCLUDED.winter_vote_signed,
    spring_vote_signed = EXCLUDED.spring_vote_signed,
    macro_direction = EXCLUDED.macro_direction,
    macro_surprise = EXCLUDED.macro_surprise,
    macro_half_life_days = EXCLUDED.macro_half_life_days,
    anomaly_score_z = EXCLUDED.anomaly_score_z,
    prior_open = EXCLUDED.prior_open,
    prior_hedge = EXCLUDED.prior_hedge,
    prior_monitor = EXCLUDED.prior_monitor
"""

# pl_indicator_daily mirror — INSERT-or-UPDATE. The legacy compute-indicators
# job creates rows for legacy + power10years versions but does NOT create
# rows for ensemble_v1, so we create the row ourselves. ``id`` has no
# server default on this table; ``gen_random_uuid()`` is supplied here.
_UPSERT_INDICATOR_DAILY = """
INSERT INTO pl_indicator_daily (
    id, date, contract_id, algorithm_version_id,
    decision, conclusion
)
VALUES (
    gen_random_uuid(), :date, :contract_id, :algorithm_version_id,
    :decision, :conclusion
)
ON CONFLICT (date, contract_id, algorithm_version_id) DO UPDATE SET
    decision = EXCLUDED.decision,
    conclusion = EXCLUDED.conclusion
"""


_WINDOW_MONTHS_BY_PREFIX = {
    "xpol_W_TB_garch": 24,
    "xpol_S_bull_garch_fx": 24,
    "xpol_S_bear_garch_macro": 24,
}


def _window_months_for(specialist_name: str) -> int:
    """Resolve the trailing-window months used by each specialist family.

    GARCH-using specialists are 24m baseline; everything else is 12m
    (matches R&D pool config in ensemble.optimizer.specialists).
    """
    if specialist_name in _WINDOW_MONTHS_BY_PREFIX:
        return _WINDOW_MONTHS_BY_PREFIX[specialist_name]
    return 12


def _decimal_or_none(x: float | None) -> Decimal | None:
    """Convert a NaN/float to Decimal-or-None for nullable diagnostic columns.

    Per rule §0 #3 (pipeline-continuity), NULL is preferred over a silent
    0.0 placeholder when the wrapper couldn't compute the value.
    """
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return Decimal(f"{f:.6f}")


def _int_or_none(x: int | None) -> int | None:
    if x is None:
        return None
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def write_decision(
    session: Session,
    *,
    target_date: date_cls,
    contract_id: uuid.UUID,
    algorithm_version_id: uuid.UUID,
    decision: EnsembleDecision,
    diagnostics: dict,
) -> dict[str, int]:
    """Write all 3 tables for one (date, contract, ensemble_version) tuple.

    ``diagnostics`` is the dict returned alongside ``EnsembleDecision`` by
    the wrapper (anomaly_z, priors, weights_sum, etc. — keys passed
    through from the diag_df last row).

    Returns counts (mostly for logging / smoke assertions).
    """
    # 1) per-specialist
    n_specialist = 0
    for name, pred in decision.per_specialist_votes.items():
        session.execute(
            text(_UPSERT_SPECIALIST),
            {
                "date": target_date,
                "contract_id": contract_id,
                "algorithm_version_id": algorithm_version_id,
                "specialist_name": name,
                "window_months": _window_months_for(name),
                "pred": pred,
            },
        )
        n_specialist += 1

    # 2) orchestrator
    sg = decision.soft_gate_decision
    session.execute(
        text(_UPSERT_ORCHESTRATOR),
        {
            "date": target_date,
            "contract_id": contract_id,
            "algorithm_version_id": algorithm_version_id,
            "soft_gate_decision": str(sg.decision),
            "net_score": _decimal_or_none(getattr(sg, "net_score", None))
            or Decimal("0"),
            "weights_sum": _decimal_or_none(diagnostics.get("weights_sum"))
            or Decimal("0"),
            "n_committed_specialists": _int_or_none(
                diagnostics.get("n_committed_specialists")
            )
            or 0,
            "decision_wrapped": str(decision.wrapped_decision),
            "wrapper_active": bool(diagnostics.get("wrapper_active", False)),
            "fired_running_acc": bool(decision.wrapper_fired_running_acc),
            "fired_trend": bool(diagnostics.get("fired_trend", False)),
            "fired_dispersion": bool(decision.wrapper_fired_cluster_dispersion),
            "fired_three_way": bool(diagnostics.get("fired_three_way", False)),
            "running_acc_5d": _decimal_or_none(decision.running_acc_5d),
            "realized_return_5d": _decimal_or_none(decision.realized_return_5d),
            "winter_vote_signed": _int_or_none(decision.winter_vote_signed),
            "spring_vote_signed": _int_or_none(decision.spring_vote_signed),
            "macro_direction": _int_or_none(
                getattr(sg.context, "macro_direction", None)
            ),
            "macro_surprise": _decimal_or_none(
                getattr(sg.context, "macro_surprise", None)
            ),
            "macro_half_life_days": _int_or_none(
                diagnostics.get("macro_half_life_days")
            ),
            "anomaly_score_z": _decimal_or_none(
                getattr(sg.context, "anomaly_score_z", None)
            ),
            "prior_open": _decimal_or_none(getattr(sg.context, "prior_open", None)),
            "prior_hedge": _decimal_or_none(getattr(sg.context, "prior_hedge", None)),
            "prior_monitor": _decimal_or_none(
                getattr(sg.context, "prior_monitor", None)
            ),
        },
    )

    # 3) indicator_daily mirror — fail-loud if the FK can't bind
    session.execute(
        text(_UPSERT_INDICATOR_DAILY),
        {
            "date": target_date,
            "contract_id": contract_id,
            "algorithm_version_id": algorithm_version_id,
            "decision": str(decision.wrapped_decision),
            "conclusion": _build_conclusion_text(decision),
        },
    )

    session.flush()
    return {"specialist": n_specialist, "orchestrator": 1, "indicator_daily": 1}


def _build_conclusion_text(decision: EnsembleDecision) -> str:
    """Human-readable summary mirrored to pl_indicator_daily.conclusion."""
    fired = []
    if decision.wrapper_fired_running_acc:
        fired.append("running_acc")
    if decision.wrapper_fired_cluster_dispersion:
        fired.append("dispersion")
    fired_str = ", ".join(fired) if fired else "none"
    return (
        f"C5 ensemble decision={decision.wrapped_decision} "
        f"(soft-gate={decision.soft_gate_decision.decision}, "
        f"wrapper_fired=[{fired_str}], "
        f"winter={decision.winter_vote_signed:+d}, "
        f"spring={decision.spring_vote_signed:+d})"
    )
