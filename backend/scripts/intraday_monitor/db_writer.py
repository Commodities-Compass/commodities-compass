"""DB I/O for the intraday monitor — loaders + append-only writers.

Every written column traces back to a computed/scraped value or an explicit
caller parameter (pipeline-continuity rule). Dedup is enforced at the data
level: INSERT ... ON CONFLICT DO NOTHING on UNIQUE(rule_id, session_date,
crossing_seq) — a manual re-run can never re-send.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import (
    AudAlertEvent,
    PlAlgorithmVersion,
    PlContractDataDaily,
    PlContractDataIntraday,
    PlDerivedIndicators,
    PlIndicatorDaily,
    RefAlertRule,
)
from scripts.intraday_monitor.config import ENSEMBLE_VERSION_NAME, SOURCE_LABEL
from scripts.intraday_monitor.engine import Firing, RuleSpec

logger = logging.getLogger(__name__)

# Pivot columns exposed to the engine ({level_column: value}).
_LEVEL_COLUMNS = ("s1", "s2", "r1", "r2", "pivot")


class LevelsMissingError(Exception):
    """No pl_derived_indicators row for the reference session — upstream gap."""


class PrevPriceMissingError(Exception):
    """No previous observation nor daily close to compare against."""


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def load_enabled_rules(session: Session) -> list[RuleSpec]:
    rows = (
        session.execute(
            select(RefAlertRule)
            .where(RefAlertRule.enabled.is_(True))
            .order_by(RefAlertRule.rule_key)
        )
        .scalars()
        .all()
    )
    return [
        RuleSpec(
            id=row.id,
            rule_key=row.rule_key,
            level_column=row.level_column,
            level_label=row.level_label,
            comparator=row.comparator,
            direction=row.direction,
            severity=row.severity,
            message_template_key=row.message_template_key,
        )
        for row in rows
    ]


def load_levels(
    session: Session, contract_id: uuid.UUID, levels_date: date
) -> dict[str, Decimal | None]:
    """Pivot levels from the last COMPLETED session (levels shown on the
    dashboard today are computed from the previous session's H/L/C)."""
    row = session.execute(
        select(PlDerivedIndicators).where(
            PlDerivedIndicators.contract_id == contract_id,
            PlDerivedIndicators.date == levels_date,
        )
    ).scalar_one_or_none()
    if row is None:
        raise LevelsMissingError(
            f"No pl_derived_indicators row at {levels_date} for contract "
            f"{contract_id} — did cc-compute-indicators run?"
        )
    return {col: getattr(row, col) for col in _LEVEL_COLUMNS}


def load_prev_price(
    session: Session,
    *,
    contract_id: uuid.UUID,
    session_date: date,
    fallback_date: date,
) -> Decimal:
    """Previous observed price: last intraday tick of this session, else the
    previous session's daily close (first tick of the day)."""
    last_obs = session.execute(
        select(PlContractDataIntraday.last_price)
        .where(
            PlContractDataIntraday.contract_id == contract_id,
            PlContractDataIntraday.session_date == session_date,
        )
        .order_by(PlContractDataIntraday.observed_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if last_obs is not None:
        return last_obs

    daily_close = session.execute(
        select(PlContractDataDaily.close).where(
            PlContractDataDaily.contract_id == contract_id,
            PlContractDataDaily.date == fallback_date,
        )
    ).scalar_one_or_none()
    if daily_close is not None:
        return daily_close

    raise PrevPriceMissingError(
        f"No intraday observation for session {session_date} and no daily "
        f"close at {fallback_date} for contract {contract_id}"
    )


def load_signal_decision(
    session: Session, contract_id: uuid.UUID, levels_date: date
) -> str | None:
    """Today's displayed decision (ensemble-preferred, fr row) — message
    context only; None degrades gracefully (consumer-side)."""
    decision = session.execute(
        select(PlIndicatorDaily.decision)
        .join(
            PlAlgorithmVersion,
            PlAlgorithmVersion.id == PlIndicatorDaily.algorithm_version_id,
        )
        .where(
            PlIndicatorDaily.contract_id == contract_id,
            PlIndicatorDaily.date == levels_date,
            PlIndicatorDaily.language == "fr",
        )
        .order_by(
            (PlAlgorithmVersion.name == ENSEMBLE_VERSION_NAME).desc(),
            PlAlgorithmVersion.created_at.desc(),
        )
        .limit(1)
    ).scalar_one_or_none()
    if decision is None:
        logger.warning(
            "No pl_indicator_daily decision at %s for contract %s "
            "(message will omit the signal name)",
            levels_date,
            contract_id,
        )
    return decision


# ---------------------------------------------------------------------------
# Writers (append-only)
# ---------------------------------------------------------------------------


def append_observation(
    session: Session,
    *,
    contract_id: uuid.UUID,
    session_date: date,
    observed_at: datetime,
    last_price: Decimal,
    trade_time: datetime | None,
) -> None:
    """Append one intraday observation (idempotent on (contract, observed_at))."""
    stmt = (
        pg_insert(PlContractDataIntraday)
        .values(
            contract_id=contract_id,
            session_date=session_date,
            observed_at=observed_at,
            last_price=last_price,
            trade_time=trade_time,
            source=SOURCE_LABEL,
        )
        .on_conflict_do_nothing(constraint="uq_contract_data_intraday")
    )
    session.execute(stmt)


def insert_alert_event(
    session: Session,
    *,
    firing: Firing,
    contract_id: uuid.UUID,
    session_date: date,
    observed_at: datetime,
    signal_decision: str | None,
    channel: str,
) -> uuid.UUID | None:
    """Insert the fired-alert row. Returns the event id, or None when the
    (rule, session) already fired — the dedup guard, first-cross-only."""
    stmt = (
        pg_insert(AudAlertEvent)
        .values(
            rule_id=firing.rule.id,
            contract_id=contract_id,
            session_date=session_date,
            crossing_seq=1,
            level_value=firing.level_value,
            observed_price=firing.curr_price,
            observed_at=observed_at,
            signal_decision=signal_decision,
            channel=channel,
        )
        .on_conflict_do_nothing(constraint="uq_alert_event_dedup")
        .returning(AudAlertEvent.id)
    )
    return session.execute(stmt).scalar_one_or_none()


def update_delivery(
    session: Session,
    *,
    event_id: uuid.UUID,
    status: str,
    provider_message_id: str | None,
    payload: dict | None = None,
) -> None:
    """Record the delivery outcome on the alert event row."""
    event = session.get(AudAlertEvent, event_id)
    if event is None:
        raise RuntimeError(f"aud_alert_event {event_id} vanished before update")
    event.delivery_status = status
    event.provider_message_id = provider_message_id
    if payload is not None:
        event.payload = payload
