"""Canonical front-month resolver (async) — the single source of truth for "which contract".

Reads the roll calendar (``ref_contract.active_from``, seeded from the operator's
real roll history and maintained by ``roll-contract``). The front-month for a
date is the contract with the greatest ``active_from`` <= that date.

This replaces the 5 divergent heuristics that caused the recurring roll
split-brain (oi/volume front-month, ``resolve_active_at_date``, the
``resolve_contract_for_date`` completeness cascade, decision-aware front-month).
Every consumer that needs "which contract for date X" must resolve here so the
pipelines can never disagree. See
docs/user-stories/P1-contract-roll-canonical-frontmonth.md.

Sync twin: ``scripts/front_month.py`` (identical rule, sync Session).
"""

import uuid
from datetime import date
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class FrontMonthError(RuntimeError):
    """Raised when the roll calendar has no front-month for the request."""


# front-month for a specific date = contract with greatest active_from <= date
_FRONT_FOR_DATE = text(
    """
    SELECT id, code
    FROM ref_contract
    WHERE active_from IS NOT NULL AND active_from <= :d
    ORDER BY active_from DESC
    LIMIT 1
    """
)

# leading-edge front-month = the most recent roll (greatest active_from)
_ACTIVE_FRONT = text(
    """
    SELECT id, code
    FROM ref_contract
    WHERE active_from IS NOT NULL
    ORDER BY active_from DESC
    LIMIT 1
    """
)


async def front_month_for_date(session: AsyncSession, target_date: date) -> uuid.UUID:
    """Contract id of the front-month on ``target_date``. Fail-loud if unseeded."""
    row = (await session.execute(_FRONT_FOR_DATE, {"d": target_date})).first()
    if row is None:
        raise FrontMonthError(
            f"No front-month in the roll calendar for {target_date} — "
            "is ref_contract.active_from seeded / earlier than this date?"
        )
    return row.id


async def front_month_code_for_date(session: AsyncSession, target_date: date) -> str:
    """Contract code of the front-month on ``target_date``. Fail-loud if unseeded."""
    row = (await session.execute(_FRONT_FOR_DATE, {"d": target_date})).first()
    if row is None:
        raise FrontMonthError(
            f"No front-month in the roll calendar for {target_date} — "
            "is ref_contract.active_from seeded / earlier than this date?"
        )
    return row.code


async def active_front_month(session: AsyncSession) -> uuid.UUID:
    """Contract id of the current (leading-edge) front-month. Fail-loud if empty."""
    row = (await session.execute(_ACTIVE_FRONT)).first()
    if row is None:
        raise FrontMonthError(
            "Roll calendar is empty (no ref_contract.active_from) — seed it."
        )
    return row.id


async def active_front_month_code(session: AsyncSession) -> str:
    """Contract code of the current (leading-edge) front-month. Fail-loud if empty."""
    row = (await session.execute(_ACTIVE_FRONT)).first()
    if row is None:
        raise FrontMonthError(
            "Roll calendar is empty (no ref_contract.active_from) — seed it."
        )
    return row.code


async def front_month_for_date_or_none(
    session: AsyncSession, target_date: date
) -> Optional[uuid.UUID]:
    """Non-raising variant for callers that tolerate a pre-calendar date."""
    row = (await session.execute(_FRONT_FOR_DATE, {"d": target_date})).first()
    return row.id if row is not None else None
