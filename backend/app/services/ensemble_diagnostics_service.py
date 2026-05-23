"""Ensemble diagnostics service — soft-gate + wrapper audit + 14 specialist votes.

Reads ``pl_orchestrator_decision`` (one row per ensemble date) and
``pl_specialist_prediction`` (14 rows). Cluster mapping for the 14
specialists is read from ``pl_algorithm_config`` (config-as-data). Empty
result on dates without an ensemble row — the API layer maps that to 404
so the frontend can hide Section VII conditionally.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date as date_cls
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline import (
    PlAlgorithmConfig,
    PlOrchestratorDecision,
    PlSpecialistPrediction,
)

logger = logging.getLogger(__name__)

# Pred → signed vote convention used by the wrapper's cluster-dispersion test.
_SIGNED_VOTE = {"OPEN": 1, "HEDGE": -1, "MONITOR": 0}

# Cluster mapping parameter name in pl_algorithm_config (set by R&D vendor pack).
CLUSTER_MAP_PARAM = "specialist_cluster_map"


async def get_ensemble_diagnostics(
    db: AsyncSession,
    target_date: date_cls,
    *,
    contract_id: Optional[uuid.UUID] = None,
    algo_id: uuid.UUID,
    algo_name: str,
) -> Optional[dict[str, Any]]:
    """Return the orchestrator diagnostics row for ``target_date`` or None.

    Returns None if no row exists (legacy dates or future dates) — caller
    maps to HTTP 404.
    """
    q = select(PlOrchestratorDecision).where(
        PlOrchestratorDecision.date == target_date,
        PlOrchestratorDecision.algorithm_version_id == algo_id,
    )
    if contract_id is not None:
        q = q.where(PlOrchestratorDecision.contract_id == contract_id)

    row = (await db.execute(q.limit(1))).scalar_one_or_none()
    if row is None:
        return None

    return {
        "date": target_date.isoformat(),
        "algorithm_version": algo_name,
        "soft_gate_decision": row.soft_gate_decision,
        "net_score": float(row.net_score),
        "weights_sum": float(row.weights_sum),
        "n_committed_specialists": int(row.n_committed_specialists),
        "decision_wrapped": row.decision_wrapped,
        "wrapper_active": bool(row.wrapper_active),
        "fired_running_acc": bool(row.fired_running_acc),
        "fired_trend": bool(row.fired_trend),
        "fired_dispersion": bool(row.fired_dispersion),
        "fired_three_way": bool(row.fired_three_way),
        "running_acc_5d": _to_float(row.running_acc_5d),
        "realized_return_5d": _to_float(row.realized_return_5d),
        "winter_vote_signed": _to_int(row.winter_vote_signed),
        "spring_vote_signed": _to_int(row.spring_vote_signed),
        "macro_direction": _to_int(row.macro_direction),
        "macro_surprise": _to_float(row.macro_surprise),
        "macro_half_life_days": _to_int(row.macro_half_life_days),
        "anomaly_score_z": _to_float(row.anomaly_score_z),
        "prior_open": _to_float(row.prior_open),
        "prior_hedge": _to_float(row.prior_hedge),
        "prior_monitor": _to_float(row.prior_monitor),
    }


async def get_specialist_votes(
    db: AsyncSession,
    target_date: date_cls,
    *,
    contract_id: Optional[uuid.UUID] = None,
    algo_id: uuid.UUID,
    algo_name: str,
) -> Optional[dict[str, Any]]:
    """Return 14 specialist votes + cluster mapping for ``target_date``.

    Returns None if no rows exist (legacy dates) — caller maps to 404.
    """
    q = select(PlSpecialistPrediction).where(
        PlSpecialistPrediction.date == target_date,
        PlSpecialistPrediction.algorithm_version_id == algo_id,
    )
    if contract_id is not None:
        q = q.where(PlSpecialistPrediction.contract_id == contract_id)
    rows = (
        (await db.execute(q.order_by(PlSpecialistPrediction.specialist_name)))
        .scalars()
        .all()
    )
    if not rows:
        return None

    cluster_map = await _load_cluster_map(db, algo_id)
    votes: list[dict[str, Any]] = []
    winter_signed = 0
    spring_signed = 0
    have_winter = False
    have_spring = False

    for r in rows:
        cluster = cluster_map.get(r.specialist_name, "unmapped")
        signed = _SIGNED_VOTE.get(r.pred.upper(), 0)
        if cluster == "winter":
            winter_signed += signed
            have_winter = True
        elif cluster == "spring":
            spring_signed += signed
            have_spring = True

        votes.append(
            {
                "specialist_name": r.specialist_name,
                "cluster": cluster,
                "pred": r.pred,
                "window_months": int(r.window_months),
                "n_features_used": _to_int(r.n_features_used),
            }
        )

    return {
        "date": target_date.isoformat(),
        "algorithm_version": algo_name,
        "votes": votes,
        "winter_signed": winter_signed if have_winter else None,
        "spring_signed": spring_signed if have_spring else None,
    }


async def _load_cluster_map(db: AsyncSession, algo_id: uuid.UUID) -> dict[str, str]:
    """Read the specialist→cluster mapping from pl_algorithm_config.

    Stored as a JSON string under ``specialist_cluster_map``. Returns {} if
    the config row is missing — clusters will fall back to "unmapped" and
    winter/spring sums become None.
    """
    row = (
        await db.execute(
            select(PlAlgorithmConfig.value).where(
                PlAlgorithmConfig.algorithm_version_id == algo_id,
                PlAlgorithmConfig.parameter_name == CLUSTER_MAP_PARAM,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return {}
    try:
        parsed = json.loads(row)
        if isinstance(parsed, dict):
            return {str(k): str(v) for k, v in parsed.items()}
    except (json.JSONDecodeError, TypeError):
        logger.warning(
            "specialist_cluster_map for algo %s is not valid JSON; ignoring", algo_id
        )
    return {}


def _to_float(v: Any) -> Optional[float]:
    return float(v) if v is not None else None


def _to_int(v: Any) -> Optional[int]:
    return int(v) if v is not None else None
