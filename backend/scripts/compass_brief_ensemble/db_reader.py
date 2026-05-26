"""Read all inputs needed by the ensemble brief generator.

Returns one ``EnsembleBriefData`` for the target session date, containing:
  - ensemble decision + narrative (from cc-ensemble-explainer's UPDATE)
  - 25+ diagnostics (from pl_orchestrator_decision)
  - 14 specialist votes
  - press review + meteo (independent agents)
  - last-completed-session technicals

Distinct from legacy ``compass_brief.db_reader`` which is yesterday+today
focused. The ensemble brief is **forward-looking** — it speaks about the
session that's about to open, with a 4-5 day decision horizon.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from scripts.compass_brief_ensemble.config import ALGORITHM_NAME, ALGORITHM_VERSION

logger = logging.getLogger(__name__)


class EnsembleBriefDataMissingError(RuntimeError):
    """Raised when required ensemble data is missing for the target date."""


@dataclass(frozen=True)
class SpecialistVote:
    name: str
    pred: str
    window_months: int


@dataclass(frozen=True)
class EnsembleBriefData:
    """All data needed to render one ensemble brief."""

    target_date: date

    # From pl_indicator_daily (ensemble row, enriched by cc-ensemble-explainer)
    decision: str
    confidence: int | None
    direction: str | None
    conclusion: str | None
    eco: str | None

    # From pl_orchestrator_decision
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

    # From pl_specialist_prediction (14 rows)
    specialists: list[SpecialistVote] = field(default_factory=list)

    # Press review
    press_summary: str = ""
    press_impact: str = ""
    press_sentiment: str = ""

    # Meteo
    meteo_summary: str = ""
    meteo_impact: str = ""

    # Last completed session technicals (string-formatted block)
    technicals_snapshot: str = ""

    # "Persistence" — how many consecutive days the same decision has been
    # in place. Computed by looking back at recent ensemble rows.
    persistence_days: int = 1


def _resolve_algorithm_id(session: Session) -> Any:
    row = session.execute(
        text(
            "SELECT id FROM pl_algorithm_version WHERE name = :name AND version = :ver LIMIT 1"
        ),
        {"name": ALGORITHM_NAME, "ver": ALGORITHM_VERSION},
    ).fetchone()
    if row is None:
        raise EnsembleBriefDataMissingError(
            f"Algorithm version {ALGORITHM_NAME} v{ALGORITHM_VERSION} not in DB."
        )
    return row[0]


def _read_ensemble_row(
    session: Session, target_date: date, contract_id: Any, algo_id: Any
) -> dict:
    row = session.execute(
        text(
            """
            SELECT decision, confidence, direction, conclusion, eco
            FROM pl_indicator_daily
            WHERE date = :date AND contract_id = :contract AND algorithm_version_id = :algo
            LIMIT 1
            """
        ),
        {"date": target_date, "contract": contract_id, "algo": algo_id},
    ).fetchone()
    if row is None:
        raise EnsembleBriefDataMissingError(
            f"No ensemble row in pl_indicator_daily for date={target_date} "
            f"contract={contract_id}."
        )
    return dict(row._mapping)


def _read_orchestrator(
    session: Session, target_date: date, contract_id: Any, algo_id: Any
) -> dict:
    row = session.execute(
        text(
            """
            SELECT soft_gate_decision, wrapper_active, net_score, n_committed_specialists,
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
        raise EnsembleBriefDataMissingError(
            f"No pl_orchestrator_decision row for date={target_date}."
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
    return [SpecialistVote(name=r[0], pred=r[1], window_months=r[2]) for r in rows]


def _read_persistence_days(
    session: Session,
    target_date: date,
    contract_id: Any,
    algo_id: Any,
    decision: str,
    lookback_days: int = 14,
) -> int:
    """Count consecutive trading days ending on target_date with the same
    ``decision`` value in pl_indicator_daily ensemble row.

    Returns 1 if only the current day matches, 2 if today + yesterday match,
    etc. Capped at ``lookback_days``.
    """
    rows = session.execute(
        text(
            """
            SELECT date, decision
            FROM pl_indicator_daily
            WHERE contract_id = :contract AND algorithm_version_id = :algo
              AND date <= :date
            ORDER BY date DESC
            LIMIT :limit
            """
        ),
        {
            "contract": contract_id,
            "algo": algo_id,
            "date": target_date,
            "limit": lookback_days,
        },
    ).all()
    persistence = 0
    for row in rows:
        if row[1] == decision:
            persistence += 1
        else:
            break
    return max(persistence, 1)


def _read_press(session: Session, target_date: date) -> tuple[str, str, str]:
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


def _read_meteo(session: Session, target_date: date) -> tuple[str, str]:
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


def _read_technicals(session: Session, target_date: date, contract_id: Any) -> str:
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
        return "(pas de données technicals)"

    def _fmt(value, unit: str = "", precision: int = 2):
        if value is None:
            return "n/a"
        if isinstance(value, Decimal):
            return f"{float(value):,.{precision}f}{unit}"
        return f"{value}{unit}"

    return (
        f"Date close : {row[0]}\n"
        f"  CLOSE={_fmt(row[1])} | HIGH={_fmt(row[2])} | LOW={_fmt(row[3])}\n"
        f"  VOLUME={_fmt(row[4], '', 0)} | OI={_fmt(row[5], '', 0)} | IV={_fmt(row[6])}\n"
        f"  STOCK_US={_fmt(row[7])} | STOCK_EU={_fmt(row[8])} | COM_NET={_fmt(row[9])}"
    )


def read_brief_data(
    session: Session,
    target_date: date,
    contract_id: Any,
    *,
    data_date: date | None = None,
) -> EnsembleBriefData:
    """Read all rows needed to render the ensemble brief. Fail-loud if the
    ensemble decision row or orchestrator row is missing (cc-ensemble-compute
    must have run first).

    Args:
        target_date: Upcoming session the brief targets — drives filename and
            P2b-keyed lookups (press, meteo).
        contract_id: Active contract.
        data_date: Last completed session — where the ensemble pipeline
            (ensemble-compute + ensemble-explainer) wrote the rows we read.
            Defaults to ``target_date`` for backward compatibility (historical
            backfills where both were the same date).
    """
    effective_data_date = data_date or target_date
    algo_id = _resolve_algorithm_id(session)
    ind = _read_ensemble_row(session, effective_data_date, contract_id, algo_id)
    orc = _read_orchestrator(session, effective_data_date, contract_id, algo_id)
    specialists = _read_specialists(session, effective_data_date, contract_id, algo_id)
    press = _read_press(session, target_date)
    meteo = _read_meteo(session, target_date)
    technicals = _read_technicals(session, effective_data_date, contract_id)
    persistence = _read_persistence_days(
        session, effective_data_date, contract_id, algo_id, ind["decision"]
    )

    logger.info(
        "Brief data assembled: decision=%s specialists=%d persistence=%dj",
        ind["decision"],
        len(specialists),
        persistence,
    )

    return EnsembleBriefData(
        target_date=target_date,
        decision=ind["decision"],
        confidence=ind["confidence"],
        direction=ind["direction"],
        conclusion=ind["conclusion"],
        eco=ind["eco"],
        soft_gate_decision=orc["soft_gate_decision"],
        wrapper_active=bool(orc["wrapper_active"]),
        net_score=orc["net_score"],
        n_committed_specialists=orc["n_committed_specialists"],
        fired_running_acc=bool(orc["fired_running_acc"]),
        fired_trend=bool(orc["fired_trend"]),
        fired_dispersion=bool(orc["fired_dispersion"]),
        fired_three_way=bool(orc["fired_three_way"]),
        running_acc_5d=orc["running_acc_5d"],
        realized_return_5d=orc["realized_return_5d"],
        anomaly_score_z=orc["anomaly_score_z"],
        macro_direction=orc["macro_direction"],
        macro_surprise=orc["macro_surprise"],
        macro_half_life_days=orc["macro_half_life_days"],
        prior_open=orc["prior_open"],
        prior_hedge=orc["prior_hedge"],
        prior_monitor=orc["prior_monitor"],
        winter_vote_signed=orc["winter_vote_signed"],
        spring_vote_signed=orc["spring_vote_signed"],
        specialists=specialists,
        press_summary=press[0],
        press_impact=press[1],
        press_sentiment=press[2],
        meteo_summary=meteo[0],
        meteo_impact=meteo[1],
        technicals_snapshot=technicals,
        persistence_days=persistence,
    )
