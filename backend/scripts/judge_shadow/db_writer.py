"""UPSERT a ``JudgeOutcome`` into ``pl_judge_shadow``.

Idempotent per (date, contract_id, algorithm_version_id): a rerun overwrites
the decision fields but LEAVES ``realized_return`` / ``production_score``
untouched (owned by the future horizon-close scoring pass — a recompute of the
overlay must not wipe a realized label, symmetric with pl_regime_shadow).
"""

from __future__ import annotations

import logging
import uuid
from datetime import date as date_cls

from judge.schema import JudgeOutcome  # type: ignore
from sqlalchemy import text
from sqlalchemy.orm import Session

from scripts.judge_shadow.regime_reader import RegimeShadowRow

logger = logging.getLogger(__name__)

_UPSERT = """
INSERT INTO pl_judge_shadow (
    id, date, contract_id, algorithm_version_id,
    base_source, base_decision, base_confidence, base_direction_label,
    regime_source_date, regime, specialist, prob_up,
    judge_direction, judge_stance, judge_confidence, is_anomaly,
    evidence, drift_summary, disconfirming_case, key_risk,
    weather_series, weather_delta, drift_notes, n_days_window,
    final_decision, changed, rationale,
    prompt_version, model_id
) VALUES (
    gen_random_uuid(), :date, :contract_id, :aid,
    :base_source, :base_decision, :base_confidence, :base_direction_label,
    :regime_source_date, :regime, :specialist, :prob_up,
    :judge_direction, :judge_stance, :judge_confidence, :is_anomaly,
    CAST(:evidence AS jsonb), :drift_summary, :disconfirming_case, :key_risk,
    CAST(:weather_series AS jsonb), :weather_delta,
    CAST(:drift_notes AS jsonb), :n_days_window,
    :final_decision, :changed, :rationale,
    :prompt_version, :model_id
)
ON CONFLICT ON CONSTRAINT uq_judge_shadow DO UPDATE SET
    base_source          = EXCLUDED.base_source,
    base_decision        = EXCLUDED.base_decision,
    base_confidence      = EXCLUDED.base_confidence,
    base_direction_label = EXCLUDED.base_direction_label,
    regime_source_date   = EXCLUDED.regime_source_date,
    regime               = EXCLUDED.regime,
    specialist           = EXCLUDED.specialist,
    prob_up              = EXCLUDED.prob_up,
    judge_direction      = EXCLUDED.judge_direction,
    judge_stance         = EXCLUDED.judge_stance,
    judge_confidence     = EXCLUDED.judge_confidence,
    is_anomaly           = EXCLUDED.is_anomaly,
    evidence             = EXCLUDED.evidence,
    drift_summary        = EXCLUDED.drift_summary,
    disconfirming_case   = EXCLUDED.disconfirming_case,
    key_risk             = EXCLUDED.key_risk,
    weather_series       = EXCLUDED.weather_series,
    weather_delta        = EXCLUDED.weather_delta,
    drift_notes          = EXCLUDED.drift_notes,
    n_days_window        = EXCLUDED.n_days_window,
    final_decision       = EXCLUDED.final_decision,
    changed              = EXCLUDED.changed,
    rationale            = EXCLUDED.rationale,
    prompt_version       = EXCLUDED.prompt_version,
    model_id             = EXCLUDED.model_id
    -- realized_return / production_score intentionally NOT updated
"""


def _jsonl(items) -> str:
    """Serialize a tuple/list to a JSON string (JSONB cast happens in the SQL)."""
    import json

    return json.dumps(list(items) if items is not None else [])


def write_judge_shadow(
    session: Session,
    outcome: JudgeOutcome,
    *,
    session_date: date_cls,
    contract_id: uuid.UUID | str,
    algorithm_version_id: uuid.UUID | str,
    regime_row: RegimeShadowRow,
) -> int:
    """Write one shadow row. Returns 1."""
    verdict = outcome.verdict
    drift = outcome.drift
    log = outcome.log_fields

    # Regime provenance (base_source / regime / specialist / prob_up) is folded
    # into log_fields by run_shadow. We source directly from regime_row so the
    # writer signature is explicit and the runner can populate log without the
    # writer having to reach back into it.
    session.execute(
        text(_UPSERT),
        {
            "date": session_date,
            "contract_id": str(contract_id),
            "aid": str(algorithm_version_id),
            "base_source": str(log.get("base_source", "regime/1.0.0")),
            "base_decision": outcome.base_decision.value,
            "base_confidence": float(log.get("base_confidence", 0.0)),
            "base_direction_label": None,  # kept nullable for now
            "regime_source_date": regime_row.source_date,
            "regime": regime_row.regime,
            "specialist": regime_row.specialist,
            "prob_up": regime_row.prob_up,
            "judge_direction": verdict.suggested_direction.value,
            "judge_stance": verdict.stance.value,
            "judge_confidence": int(verdict.confidence),
            "is_anomaly": bool(verdict.is_anomaly),
            "evidence": _jsonl(verdict.evidence),
            "drift_summary": verdict.drift_summary or None,
            "disconfirming_case": verdict.disconfirming_case or None,
            "key_risk": verdict.key_risk or None,
            "weather_series": _jsonl(drift.weather_impact_series),
            "weather_delta": (
                float(drift.weather_delta) if drift.weather_delta is not None else None
            ),
            "drift_notes": _jsonl(drift.notes),
            "n_days_window": int(drift.n_days),
            "final_decision": outcome.final_decision.value,
            "changed": bool(outcome.changed),
            "rationale": outcome.rationale or None,
            "prompt_version": verdict.prompt_version or "",
            "model_id": verdict.model_id or "",
        },
    )
    return 1
