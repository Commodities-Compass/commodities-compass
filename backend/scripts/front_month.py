"""Canonical front-month resolver (sync) — the single source of truth for "which contract".

Sync twin of ``app/utils/front_month.py`` for jobs/scripts (sync ``Session``).
The front-month for a date = the contract with the greatest ``ref_contract.active_from``
<= that date. Replaces the divergent heuristics (oi/volume, resolve_active_at_date,
resolve_contract_for_date cascade, decision-aware) — every consumer resolves here.
See docs/user-stories/P1-contract-roll-canonical-frontmonth.md.
"""

import uuid
from datetime import date
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session


class FrontMonthError(RuntimeError):
    """Raised when the roll calendar has no front-month for the request."""


_FRONT_FOR_DATE = text(
    """
    SELECT id, code
    FROM ref_contract
    WHERE active_from IS NOT NULL AND active_from <= :d
    ORDER BY active_from DESC
    LIMIT 1
    """
)

_ACTIVE_FRONT = text(
    """
    SELECT id, code
    FROM ref_contract
    WHERE active_from IS NOT NULL
    ORDER BY active_from DESC
    LIMIT 1
    """
)


def front_month_for_date(session: Session, target_date: date) -> uuid.UUID:
    """Contract id of the front-month on ``target_date``. Fail-loud if unseeded."""
    row = session.execute(_FRONT_FOR_DATE, {"d": target_date}).first()
    if row is None:
        raise FrontMonthError(
            f"No front-month in the roll calendar for {target_date} — "
            "is ref_contract.active_from seeded / earlier than this date?"
        )
    return row.id


def front_month_code_for_date(session: Session, target_date: date) -> str:
    """Contract code of the front-month on ``target_date``. Fail-loud if unseeded."""
    row = session.execute(_FRONT_FOR_DATE, {"d": target_date}).first()
    if row is None:
        raise FrontMonthError(
            f"No front-month in the roll calendar for {target_date} — "
            "is ref_contract.active_from seeded / earlier than this date?"
        )
    return row.code


def active_front_month(session: Session) -> uuid.UUID:
    """Contract id of the current (leading-edge) front-month. Fail-loud if empty."""
    row = session.execute(_ACTIVE_FRONT).first()
    if row is None:
        raise FrontMonthError(
            "Roll calendar is empty (no ref_contract.active_from) — seed it."
        )
    return row.id


def active_front_month_code(session: Session) -> str:
    """Contract code of the current (leading-edge) front-month. Fail-loud if empty."""
    row = session.execute(_ACTIVE_FRONT).first()
    if row is None:
        raise FrontMonthError(
            "Roll calendar is empty (no ref_contract.active_from) — seed it."
        )
    return row.code


def front_month_for_date_or_none(
    session: Session, target_date: date
) -> Optional[uuid.UUID]:
    """Non-raising variant for callers that tolerate a pre-calendar date."""
    row = session.execute(_FRONT_FOR_DATE, {"d": target_date}).first()
    return row.id if row is not None else None
