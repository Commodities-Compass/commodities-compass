"""Read inputs needed to build the LLM prompt: ensemble row + orchestrator
diagnostics + 14 specialist votes + press review + meteo + recent technicals.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from scripts.ensemble_explainer.config import ALGORITHM_NAME, ALGORITHM_VERSION

logger = logging.getLogger(__name__)


class ExplainerDataMissingError(RuntimeError):
    """Raised when required ensemble rows are not present for the target date."""


@dataclass(frozen=True)
class SpecialistVote:
    name: str
    pred: str
    window_months: int


@dataclass(frozen=True)
class ExplainerInputs:
    """All inputs assembled for the LLM call."""

    target_date: date
    contract_id: Any
    algorithm_version_id: Any

    # Ensemble decision + diagnostics (from pl_orchestrator_decision)
    decision: str
    soft_gate_decision: str
    wrapper_active: bool
    net_score: Decimal | None
    n_committed_specialists: int | None
    fired_running_acc: bool
    fired_trend: bool
    fired_dispersion: bool
    fired_three_way: bool
    running_acc_5d: Decimal | None
    realized_return_5d: Decimal | None
    anomaly_score_z: Decimal | None
    macro_direction: int | None
    macro_surprise: Decimal | None
    macro_half_life_days: int | None
    prior_open: Decimal | None
    prior_hedge: Decimal | None
    prior_monitor: Decimal | None
    winter_vote_signed: int | None
    spring_vote_signed: int | None

    specialists: list[SpecialistVote] = field(default_factory=list)

    # Press review (latest is_active row)
    press_summary: str = ""
    press_impact: str = ""
    press_sentiment: str = ""

    # Meteo (latest row)
    meteo_summary: str = ""
    meteo_impact: str = ""

    # Technicals snapshot (string-formatted block)
    technicals_snapshot: str = ""


def _resolve_algorithm_version_id(session: Session) -> Any:
    """Look up the ensemble algorithm version id."""
    row = session.execute(
        text(
            "SELECT id FROM pl_algorithm_version WHERE name = :name "
            "AND version = :ver LIMIT 1"
        ),
        {"name": ALGORITHM_NAME, "ver": ALGORITHM_VERSION},
    ).fetchone()
    if row is None:
        raise ExplainerDataMissingError(
            f"Algorithm version {ALGORITHM_NAME} v{ALGORITHM_VERSION} not in DB."
        )
    return row[0]


def _read_orchestrator_decision(
    session: Session, target_date: date, contract_id: Any, algo_id: Any
) -> dict:
    row = session.execute(
        text(
            """
            SELECT decision_wrapped, soft_gate_decision, wrapper_active,
                   net_score, n_committed_specialists,
                   fired_running_acc, fired_trend, fired_dispersion, fired_three_way,
                   running_acc_5d, realized_return_5d, anomaly_score_z,
                   macro_direction, macro_surprise, macro_half_life_days,
                   prior_open, prior_hedge, prior_monitor,
                   winter_vote_signed, spring_vote_signed
            FROM pl_orchestrator_decision
            WHERE date = :date AND contract_id = :contract AND algorithm_version_id = :algo
            LIMIT 1
            """
        ),
        {"date": target_date, "contract": contract_id, "algo": algo_id},
    ).fetchone()
    if row is None:
        raise ExplainerDataMissingError(
            f"No pl_orchestrator_decision row for date={target_date} "
            f"contract={contract_id} algo={algo_id}."
        )
    return dict(row._mapping)


def _read_specialists(
    session: Session, target_date: date, contract_id: Any, algo_id: Any
) -> list[SpecialistVote]:
    rows = session.execute(
        text(
            """
            SELECT specialist_name, pred, window_months
            FROM pl_specialist_prediction
            WHERE date = :date AND contract_id = :contract AND algorithm_version_id = :algo
            ORDER BY specialist_name ASC
            """
        ),
        {"date": target_date, "contract": contract_id, "algo": algo_id},
    ).all()
    if not rows:
        raise ExplainerDataMissingError(
            f"No pl_specialist_prediction rows for date={target_date} algo={algo_id}."
        )
    return [SpecialistVote(name=r[0], pred=r[1], window_months=r[2]) for r in rows]


def _read_latest_press(session: Session, target_date: date) -> tuple[str, str, str]:
    """Return (summary, impact_synthesis, sentiment) for the most recent
    pl_fundamental_article on or before target_date with is_active=true.
    Fallback to empty strings if none found (does not raise — press is optional).
    """
    row = session.execute(
        text(
            """
            SELECT summary, impact_synthesis, COALESCE(sentiment, '')
            FROM pl_fundamental_article
            WHERE is_active = true AND date <= :date
            ORDER BY date DESC LIMIT 1
            """
        ),
        {"date": target_date},
    ).fetchone()
    if row is None:
        return "", "", ""
    return (row[0] or "", row[1] or "", row[2] or "")


def _read_latest_meteo(session: Session, target_date: date) -> tuple[str, str]:
    """Return (summary, impact_assessment) of the most recent pl_weather_observation."""
    row = session.execute(
        text(
            """
            SELECT summary, impact_assessment
            FROM pl_weather_observation
            WHERE date <= :date
            ORDER BY date DESC LIMIT 1
            """
        ),
        {"date": target_date},
    ).fetchone()
    if row is None:
        return "", ""
    return (row[0] or "", row[1] or "")


def _read_technicals_snapshot(
    session: Session, target_date: date, contract_id: Any
) -> str:
    """Return a compact text snapshot of the last completed session technicals.

    Reads pl_contract_data_daily for the most recent date <= target_date
    (which should be the previous trading session). Formats key fields as a
    short bullet list.
    """
    row = session.execute(
        text(
            """
            SELECT date, close, high, low, volume, oi, implied_volatility,
                   stock_us, stock_eu_bags60kg, com_net_us
            FROM pl_contract_data_daily
            WHERE contract_id = :contract AND date <= :date
            ORDER BY date DESC LIMIT 1
            """
        ),
        {"date": target_date, "contract": contract_id},
    ).fetchone()
    if row is None:
        return "(pas de données technicals disponibles)"

    def _fmt(value: Any, unit: str = "", precision: int = 2) -> str:
        if value is None:
            return "n/a"
        if isinstance(value, Decimal):
            return f"{float(value):,.{precision}f}{unit}"
        return f"{value}{unit}"

    return (
        f"Date close: {row[0]}\n"
        f"  CLOSE={_fmt(row[1])} | HIGH={_fmt(row[2])} | LOW={_fmt(row[3])}\n"
        f"  VOLUME={_fmt(row[4], '', 0)} | OI={_fmt(row[5], '', 0)} | IV={_fmt(row[6])}\n"
        f"  STOCK_US={_fmt(row[7])} | STOCK_EU={_fmt(row[8])} | COM_NET={_fmt(row[9])}"
    )


def read_explainer_inputs(
    session: Session, target_date: date, contract_id: Any
) -> ExplainerInputs:
    """Read all inputs needed for the LLM prompt. Fail-loud if ensemble rows
    are missing — the explainer cannot work without them."""
    algo_id = _resolve_algorithm_version_id(session)
    orchestrator = _read_orchestrator_decision(
        session, target_date, contract_id, algo_id
    )
    specialists = _read_specialists(session, target_date, contract_id, algo_id)
    press_summary, press_impact, press_sentiment = _read_latest_press(
        session, target_date
    )
    meteo_summary, meteo_impact = _read_latest_meteo(session, target_date)
    technicals_snapshot = _read_technicals_snapshot(session, target_date, contract_id)

    logger.info(
        "Explainer inputs: decision=%s specialists=%d press_len=%d meteo_len=%d",
        orchestrator["decision_wrapped"],
        len(specialists),
        len(press_summary),
        len(meteo_summary),
    )

    return ExplainerInputs(
        target_date=target_date,
        contract_id=contract_id,
        algorithm_version_id=algo_id,
        decision=orchestrator["decision_wrapped"],
        soft_gate_decision=orchestrator["soft_gate_decision"],
        wrapper_active=bool(orchestrator["wrapper_active"]),
        net_score=orchestrator["net_score"],
        n_committed_specialists=orchestrator["n_committed_specialists"],
        fired_running_acc=bool(orchestrator["fired_running_acc"]),
        fired_trend=bool(orchestrator["fired_trend"]),
        fired_dispersion=bool(orchestrator["fired_dispersion"]),
        fired_three_way=bool(orchestrator["fired_three_way"]),
        running_acc_5d=orchestrator["running_acc_5d"],
        realized_return_5d=orchestrator["realized_return_5d"],
        anomaly_score_z=orchestrator["anomaly_score_z"],
        macro_direction=orchestrator["macro_direction"],
        macro_surprise=orchestrator["macro_surprise"],
        macro_half_life_days=orchestrator["macro_half_life_days"],
        prior_open=orchestrator["prior_open"],
        prior_hedge=orchestrator["prior_hedge"],
        prior_monitor=orchestrator["prior_monitor"],
        winter_vote_signed=orchestrator["winter_vote_signed"],
        spring_vote_signed=orchestrator["spring_vote_signed"],
        specialists=specialists,
        press_summary=press_summary,
        press_impact=press_impact,
        press_sentiment=press_sentiment,
        meteo_summary=meteo_summary,
        meteo_impact=meteo_impact,
        technicals_snapshot=technicals_snapshot,
    )
