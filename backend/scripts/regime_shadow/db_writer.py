"""UPSERT a ``RegimeDecision`` into ``pl_regime_shadow``.

Idempotent per (date, contract_id, algorithm_version_id): a rerun overwrites the
decision fields but LEAVES ``realized_return`` / ``production_score`` untouched
(those are owned by the separate horizon-close scoring pass — a recompute of the
decision must not wipe a realized label).
"""

from __future__ import annotations

import logging
import uuid
from datetime import date as date_cls

from regime.data_loader_protocol import RegimeDecision
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_UPSERT = """
INSERT INTO pl_regime_shadow (
    id, date, contract_id, algorithm_version_id,
    decision, regime, specialist, prob_up,
    state_rsi_14d, state_atr_14d, state_trend20
) VALUES (
    gen_random_uuid(), :date, :contract_id, :aid,
    :decision, :regime, :specialist, :prob_up,
    :rsi, :atr, :trend20
)
ON CONFLICT ON CONSTRAINT uq_regime_shadow DO UPDATE SET
    decision      = EXCLUDED.decision,
    regime        = EXCLUDED.regime,
    specialist    = EXCLUDED.specialist,
    prob_up       = EXCLUDED.prob_up,
    state_rsi_14d = EXCLUDED.state_rsi_14d,
    state_atr_14d = EXCLUDED.state_atr_14d,
    state_trend20 = EXCLUDED.state_trend20
"""


def _num(states: dict, key: str) -> float | None:
    val = states.get(key)
    return float(val) if val is not None else None


def write_regime_shadow(
    session: Session,
    decision: RegimeDecision,
    *,
    session_date: date_cls,
    contract_id: uuid.UUID | str,
    algorithm_version_id: uuid.UUID | str,
) -> int:
    """Write one shadow row. Returns 1."""
    states = decision.states or {}
    session.execute(
        text(_UPSERT),
        {
            "date": session_date,
            "contract_id": str(contract_id),
            "aid": str(algorithm_version_id),
            "decision": str(decision.decision),
            "regime": str(decision.regime),
            "specialist": str(decision.specialist),
            "prob_up": float(decision.prob_up),
            "rsi": _num(states, "rsi_14d"),
            "atr": _num(states, "atr_14d"),
            "trend20": _num(states, "trend20"),
        },
    )
    return 1
