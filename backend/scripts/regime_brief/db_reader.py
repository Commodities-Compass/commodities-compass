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

from scripts._shared.brief_common import (
    compute_ytd_score,
    read_meteo,
    read_press,
    read_seasonal_trajectory,
    read_technicals,
)
from scripts._shared.farmgate_brief import read_farmgate
from scripts.regime_brief.config import ALGORITHM_NAME

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
    """Everything one brief needs, in one language.

    The brief is the whole of Compass, not just the algorithm's call — so this
    carries the market-wide inputs (press, weather, campaign trajectory,
    technicals, guaranteed farmgate price, YTD) alongside the two decision
    layers. Only the editorial section is track-specific; every field below is
    read by the same shared readers the other tracks use.
    """

    session_date: date_cls
    target_date: date_cls
    contract_id: uuid.UUID
    contract_code: str
    language: str
    regime: RegimeCall
    judge: JudgeCall
    technicals: Technicals
    technicals_snapshot: str
    watch_lines: tuple[str, ...]
    ytd_score: Optional[float]
    farmgate: object | None
    press_summary: str
    press_impact: str
    press_sentiment: str
    meteo_summary: str
    meteo_impact: str
    meteo_trajectory: str
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


def _require(value: str, *, what: str, session_date: date_cls, language: str) -> str:
    """Turn a shared reader's empty string into a loud failure.

    The shared readers degrade to "" because other consumers treat those
    sections as optional context. For this brief they are not optional: a brief
    published without its press review or weather is a silently amputated
    product, and the podcast prompt expects both sections to exist.
    """
    if not value.strip():
        raise BriefDataMissingError(
            f"No {language} {what} at {session_date} — the brief cannot be "
            "published without it"
        )
    return value


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


def _next_session(session: Session, session_date: date_cls) -> date_cls:
    """The session this brief decides for — the row date's next trading day."""
    from scripts.db import get_next_session_date

    return get_next_session_date(session_date)


def _build_watch_lines(technicals: Technicals, language: str) -> tuple[str, ...]:
    """The "TO WATCH" block — pivot levels the podcast reads out as prose.

    Deterministic, straight from pl_derived_indicators: these are the numbers a
    listener acts on, so they are never written by a model.
    """
    if technicals.s1 is None and technicals.r1 is None:
        return ()

    def _level(value: Decimal) -> str:
        # Pivots are DECIMAL(15,6) in DB; a level read aloud as
        # "seven thousand eight hundred fifty point zero zero zero zero zero
        # zero" is unusable. Two decimals, as the brief has always shown them.
        return f"{float(value):,.2f}".replace(",", " ")

    header = "> À SURVEILLER AUJOURD'HUI :" if language != "en" else "> TO WATCH TODAY:"
    lines = [header]
    if technicals.s1 is not None:
        level = _level(technicals.s1)
        lines.append(
            f"        • Baissier si le cours casse le SUPPORT 1 ({level})."
            if language != "en"
            else f"        • Bearish if CLOSE breaks below SUPPORT 1 ({level})."
        )
    if technicals.r1 is not None:
        level = _level(technicals.r1)
        lines.append(
            f"        • Haussier si le cours franchit la RÉSISTANCE 1 ({level})."
            if language != "en"
            else f"        • Bullish if CLOSE clears RESISTANCE 1 ({level})."
        )
    return tuple(lines)


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
    weather_body = _fetch_weather(session, session_date, language)
    contract_code = _fetch_contract_code(session, contract_id)

    # Market-wide inputs — the same readers every track uses. They describe the
    # market, not a decision, so they are shared rather than reimplemented per
    # track (scripts/_shared/brief_common.py).
    press_summary, press_impact, press_sentiment = read_press(
        session, session_date, language
    )
    press_summary = _require(
        press_summary, what="press review", session_date=session_date, language=language
    )
    meteo_summary, meteo_impact = read_meteo(session, session_date, language)
    _require(
        meteo_summary or meteo_impact,
        what="weather bulletin",
        session_date=session_date,
        language=language,
    )
    meteo_trajectory = read_seasonal_trajectory(session, session_date, language)
    technicals_snapshot = read_technicals(session, session_date, contract_id, language)
    farmgate = read_farmgate(session, session_date)
    ytd_score = compute_ytd_score(
        session, session_date, algorithm_version_id, ALGORITHM_NAME
    )
    watch_lines = _build_watch_lines(technicals, language)

    return BriefData(
        session_date=session_date,
        target_date=_next_session(session, session_date),
        contract_id=contract_id,
        contract_code=contract_code,
        language=language,
        regime=regime,
        judge=judge,
        technicals=technicals,
        technicals_snapshot=technicals_snapshot,
        watch_lines=watch_lines,
        ytd_score=ytd_score,
        farmgate=farmgate,
        press_summary=press_summary,
        press_impact=press_impact,
        press_sentiment=press_sentiment,
        meteo_summary=meteo_summary,
        meteo_impact=meteo_impact,
        meteo_trajectory=meteo_trajectory,
        weather_body=weather_body,
    )
