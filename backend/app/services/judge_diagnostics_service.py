"""Judge diagnostics — the regime+judge conviction surface.

Replaces the ensemble's ``/ensemble-diagnostics`` + ``/specialist-votes`` pair
for the Campaign-6 track. Same commercial row of the offer matrix ("Conviction"),
different machinery underneath: where the ensemble reported a vote count across
14 specialists, regime+judge reports a routed regime, the model's probability,
and what the macro overlay did with that call.

Three sources, one payload:
  * ``pl_regime_shadow``  — Layer 1+2: routed regime, specialist, prob_up, base call
  * ``pl_judge_shadow``   — Layer 3: stance, direction, confidence, drift, evidence
  * ``pl_indicator_daily``— the served row: confidence + its rationale, per language

**``rationale`` is never returned.** ``pl_judge_shadow.rationale`` is the
deterministic trace of ``policy.fuse`` ("ABSTAIN HEDGE->MONITOR: judge
contradicts at conf=3") — audit material for the judge's own replay. It is not
in the brief prompt and it is not served; the user-facing sentence is
``confidence_rationale``, written natively per language by ``cc-regime-brief``.

Returns None when the session has no regime row — the caller maps that to 404
and the frontend hides the block, exactly as it did for ensemble dates.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date as date_cls
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline import PlIndicatorDaily, PlJudgeShadow, PlRegimeShadow
from app.services.dashboard_service import compute_running_accuracy

logger = logging.getLogger(__name__)


async def get_judge_diagnostics(
    db: AsyncSession,
    target_date: date_cls,
    *,
    contract_id: Optional[uuid.UUID] = None,
    algo_id: uuid.UUID,
    algo_name: str,
    language: str = "fr",
) -> Optional[dict[str, Any]]:
    """Return the regime call + judge overlay for ``target_date``, or None.

    The regime row is required: it is the decision itself. The judge row is
    optional — the overlay can be absent on a session where the LLM leg failed,
    and the technical call still stands on its own. Reporting the base call with
    an empty overlay is honest; inventing a neutral verdict is not.
    """
    regime_q = select(PlRegimeShadow).where(
        PlRegimeShadow.date == target_date,
        PlRegimeShadow.algorithm_version_id == algo_id,
    )
    if contract_id is not None:
        regime_q = regime_q.where(PlRegimeShadow.contract_id == contract_id)
    regime = (await db.execute(regime_q.limit(1))).scalar_one_or_none()
    if regime is None:
        return None

    judge_q = select(PlJudgeShadow).where(
        PlJudgeShadow.date == target_date,
        PlJudgeShadow.algorithm_version_id == algo_id,
    )
    if contract_id is not None:
        judge_q = judge_q.where(PlJudgeShadow.contract_id == contract_id)
    judge = (await db.execute(judge_q.limit(1))).scalar_one_or_none()
    if judge is None:
        logger.warning(
            "No judge overlay for %s on algorithm %s — serving the technical "
            "call alone",
            target_date,
            algo_name,
        )

    confidence, confidence_rationale = await _read_served_confidence(
        db, target_date, algo_id=algo_id, contract_id=contract_id, language=language
    )

    payload: dict[str, Any] = {
        "date": target_date.isoformat(),
        "algorithm_version": algo_name,
        # --- Layer 1+2 — the technical call ---
        "regime": regime.regime,
        "specialist": regime.specialist,
        "prob_up": float(regime.prob_up),
        "base_decision": regime.decision,
        # --- the served narrative ---
        "confidence": confidence,
        "confidence_rationale": confidence_rationale,
        "running_acc_5d": await compute_running_accuracy(
            db, target_date, algorithm_name=algo_name
        ),
    }

    if judge is None:
        payload.update(
            {
                "judge_direction": None,
                "judge_stance": None,
                "judge_confidence": None,
                "is_anomaly": None,
                "changed": None,
                "final_decision": regime.decision,
                "drift_summary": None,
                "key_risk": None,
                "disconfirming_case": None,
                "evidence": [],
                "weather_delta": None,
                "n_days_window": None,
            }
        )
        return payload

    payload.update(
        {
            "judge_direction": judge.judge_direction,
            "judge_stance": judge.judge_stance,
            "judge_confidence": int(judge.judge_confidence),
            "is_anomaly": bool(judge.is_anomaly),
            "changed": bool(judge.changed),
            "final_decision": judge.final_decision,
            "drift_summary": judge.drift_summary,
            "key_risk": judge.key_risk,
            "disconfirming_case": judge.disconfirming_case,
            "evidence": _clean_evidence(judge.evidence),
            "weather_delta": _to_float(judge.weather_delta),
            "n_days_window": int(judge.n_days_window),
        }
    )
    return payload


async def _read_served_confidence(
    db: AsyncSession,
    target_date: date_cls,
    *,
    algo_id: uuid.UUID,
    contract_id: Optional[uuid.UUID],
    language: str,
) -> tuple[Optional[int], Optional[str]]:
    """Confidence + its user-facing sentence from the served row.

    Both are written by ``cc-regime-brief`` in the row's own language. Absent
    until that job has run for the session — the tile then shows the score with
    no caption rather than borrowing another language's sentence.
    """
    q = select(
        PlIndicatorDaily.confidence, PlIndicatorDaily.confidence_rationale
    ).where(
        PlIndicatorDaily.date == target_date,
        PlIndicatorDaily.algorithm_version_id == algo_id,
        PlIndicatorDaily.language == language,
    )
    if contract_id is not None:
        q = q.where(PlIndicatorDaily.contract_id == contract_id)
    row = (await db.execute(q.limit(1))).first()
    if row is None:
        return None, None
    confidence = int(row[0]) if row[0] is not None else None
    rationale = str(row[1]) if row[1] else None
    return confidence, rationale


def _clean_evidence(raw: Any) -> list[dict[str, Any]]:
    """Normalise the judge's evidence list into serialisable dicts.

    Stored as JSONB, so its shape is whatever the LLM leg wrote. Anything that
    is not a mapping is dropped rather than passed through — the frontend renders
    these as quotes and a stray string would surface as an empty card.
    """
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _to_float(v: Any) -> Optional[float]:
    return float(v) if v is not None else None
