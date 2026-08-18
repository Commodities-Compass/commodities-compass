"""Read everything the regime brief needs — fail-loud, single algorithm.

Every read is scoped to the regime+judge system. There is no cross-algorithm
lookup anywhere in this module: from this algorithm on, the pipeline behaves as
though no other algorithm exists. A missing input raises instead of degrading —
a brief built on a silently-absent section is worse than no brief, because
nobody notices.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date as date_cls
from decimal import Decimal
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class BriefDataMissingError(RuntimeError):
    """A required input for the brief is absent for this session."""


@dataclass(frozen=True)
class RegimeCall:
    """Layer 1+2 — the technical call."""

    decision: str
    regime: str
    specialist: str
    prob_up: float


@dataclass(frozen=True)
class JudgeCall:
    """Layer 3 — the macro overlay.

    ``rationale`` is deliberately absent: it is the deterministic trace of
    policy.fuse ("ABSTAIN HEDGE->MONITOR: judge contradicts at conf=3"), kept in
    pl_judge_shadow for the judge's own replay and for audit. It is not
    editorial material and must never reach the narrator's prompt.
    """

    final_decision: str
    direction: str
    stance: str
    confidence: int
    is_anomaly: bool
    changed: bool
    drift_summary: Optional[str]
    key_risk: Optional[str]
    disconfirming_case: Optional[str]
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class Technicals:
    close: Optional[Decimal]
    close_prev: Optional[Decimal]
    volume: Optional[int]
    oi: Optional[int]
    rsi_14d: Optional[Decimal]
    s1: Optional[Decimal]
    r1: Optional[Decimal]


@dataclass(frozen=True)
class BriefData:
    session_date: date_cls
    contract_id: uuid.UUID
    contract_code: str
    language: str
    regime: RegimeCall
    judge: JudgeCall
    technicals: Technicals
    press_summary: str
    press_impact: str
    weather_body: str


def _fetch_regime(
    session: Session, session_date: date_cls, algorithm_version_id: uuid.UUID | str
) -> tuple[RegimeCall, uuid.UUID]:
    row = session.execute(
        text(
            """
            SELECT contract_id, decision, regime, specialist, prob_up
            FROM pl_regime_shadow
            WHERE date = :d AND algorithm_version_id = :a
            """
        ),
        {"d": session_date, "a": str(algorithm_version_id)},
    ).fetchone()
    if row is None:
        raise BriefDataMissingError(
            f"No pl_regime_shadow row at {session_date} — cc-regime-daily has "
            "not produced a decision for this session"
        )
    contract_id = (
        row.contract_id
        if isinstance(row.contract_id, uuid.UUID)
        else uuid.UUID(str(row.contract_id))
    )
    return (
        RegimeCall(
            decision=str(row.decision),
            regime=str(row.regime),
            specialist=str(row.specialist),
            prob_up=float(row.prob_up),
        ),
        contract_id,
    )


def _fetch_judge(session: Session, session_date: date_cls) -> JudgeCall:
    row = session.execute(
        text(
            """
            SELECT final_decision, judge_direction, judge_stance, judge_confidence,
                   is_anomaly, changed, drift_summary, key_risk,
                   disconfirming_case, evidence
            FROM pl_judge_shadow
            WHERE date = :d
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"d": session_date},
    ).fetchone()
    if row is None:
        raise BriefDataMissingError(
            f"No pl_judge_shadow row at {session_date} — the macro overlay is "
            "part of the published decision, so the brief cannot be written "
            "without it"
        )
    raw_evidence = row.evidence or []
    evidence = tuple(
        str(item).strip()
        for item in raw_evidence
        if isinstance(item, str) and item.strip()
    )
    return JudgeCall(
        final_decision=str(row.final_decision),
        direction=str(row.judge_direction),
        stance=str(row.judge_stance),
        confidence=int(row.judge_confidence),
        is_anomaly=bool(row.is_anomaly),
        changed=bool(row.changed),
        drift_summary=row.drift_summary,
        key_risk=row.key_risk,
        disconfirming_case=row.disconfirming_case,
        evidence=evidence,
    )


def _fetch_technicals(
    session: Session, session_date: date_cls, contract_id: uuid.UUID
) -> Technicals:
    row = session.execute(
        text(
            """
            SELECT c.close, c.volume, c.oi, d.rsi_14d, d.s1, d.r1,
                   (SELECT close FROM pl_contract_data_daily p
                     WHERE p.contract_id = c.contract_id AND p.date < c.date
                     ORDER BY p.date DESC LIMIT 1) AS close_prev
            FROM pl_contract_data_daily c
            LEFT JOIN pl_derived_indicators d
                   ON d.date = c.date AND d.contract_id = c.contract_id
            WHERE c.date = :d AND c.contract_id = :c
            """
        ),
        {"d": session_date, "c": str(contract_id)},
    ).fetchone()
    if row is None:
        raise BriefDataMissingError(
            f"No pl_contract_data_daily row at {session_date} for contract "
            f"{contract_id} — the session has no market data"
        )
    return Technicals(
        close=row.close,
        close_prev=row.close_prev,
        volume=row.volume,
        oi=row.oi,
        rsi_14d=row.rsi_14d,
        s1=row.s1,
        r1=row.r1,
    )


def _fetch_press(
    session: Session, session_date: date_cls, language: str
) -> tuple[str, str]:
    row = session.execute(
        text(
            """
            SELECT summary, COALESCE(impact_synthesis, '') AS impact
            FROM pl_fundamental_article
            WHERE date = :d AND language = :l AND is_active = true
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"d": session_date, "l": language},
    ).fetchone()
    if row is None or not row.summary:
        raise BriefDataMissingError(
            f"No active {language} press article at {session_date}"
        )
    return str(row.summary), str(row.impact)


def _fetch_weather(session: Session, session_date: date_cls, language: str) -> str:
    row = session.execute(
        text(
            """
            SELECT impact_assessment
            FROM pl_weather_observation
            WHERE date = :d AND language = :l
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"d": session_date, "l": language},
    ).fetchone()
    if row is None or not row.impact_assessment:
        raise BriefDataMissingError(
            f"No {language} weather observation at {session_date}"
        )
    return str(row.impact_assessment)


def _fetch_contract_code(session: Session, contract_id: uuid.UUID) -> str:
    row = session.execute(
        text("SELECT code FROM ref_contract WHERE id = :c"),
        {"c": str(contract_id)},
    ).fetchone()
    if row is None:
        raise BriefDataMissingError(f"Unknown contract {contract_id}")
    return str(row.code)


def read_brief_data(
    session: Session,
    *,
    session_date: date_cls,
    algorithm_version_id: uuid.UUID | str,
    language: str,
) -> BriefData:
    """Assemble every input for one session in one language.

    Raises ``BriefDataMissingError`` on the first missing piece — the caller
    turns that into a non-zero exit so the gap is visible the same evening.
    """
    regime, contract_id = _fetch_regime(session, session_date, algorithm_version_id)
    judge = _fetch_judge(session, session_date)
    technicals = _fetch_technicals(session, session_date, contract_id)
    press_summary, press_impact = _fetch_press(session, session_date, language)
    weather_body = _fetch_weather(session, session_date, language)
    contract_code = _fetch_contract_code(session, contract_id)

    return BriefData(
        session_date=session_date,
        contract_id=contract_id,
        contract_code=contract_code,
        language=language,
        regime=regime,
        judge=judge,
        technicals=technicals,
        press_summary=press_summary,
        press_impact=press_impact,
        weather_body=weather_body,
    )
