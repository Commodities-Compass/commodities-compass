"""Canonical front-month roll calendar — resolver + VIEW regression tests.

Guards the split-brain bug class (7 prod incidents, latest 2026-07-17): the
front-month is now the operator's roll calendar (``ref_contract.active_from``),
NOT a liquidity heuristic. A contract that leads OI **and** volume but was never
rolled to (no ``active_from``) must NEVER be picked — that premature-roll to
CAZ26 in July 2026 is exactly what crashed daily-analysis and dropped the
"À surveiller" block.

The VIEW is created by Alembic migration d5e6f7a8b9c0, not by
``Base.metadata.create_all()``; we re-create it per test so the suite doesn't
depend on Alembic ordering.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.pipeline import PlContractDataDaily
from app.models.reference import RefCommodity, RefContract, RefExchange

# Calendar VIEW — must stay in sync with migration d5e6f7a8b9c0 (_NEW_VIEW).
_CALENDAR_VIEW_DDL = """
CREATE OR REPLACE VIEW v_contract_data_chained AS
WITH front AS (
    SELECT dd.date,
           (SELECT c.id FROM ref_contract c
             WHERE c.active_from IS NOT NULL
               AND c.active_from <= dd.date
             ORDER BY c.active_from DESC LIMIT 1) AS front_id
    FROM (SELECT DISTINCT date FROM pl_contract_data_daily
           WHERE close IS NOT NULL) dd
)
SELECT d.date, d.display_date, d.contract_id,
       d.open, d.high, d.low, d.close,
       d.volume, d.oi, d.implied_volatility
FROM pl_contract_data_daily d
JOIN front f ON f.date = d.date AND f.front_id = d.contract_id
WHERE d.close IS NOT NULL;
"""


def _contract(
    session: Session,
    *,
    code: str,
    active: bool = False,
    active_from: date | None = None,
) -> uuid.UUID:
    ex = RefExchange(code=f"ICE-{code}", name="ICE", timezone="UTC")
    session.add(ex)
    session.flush()
    com = RefCommodity(code=f"COCOA-{code}", name="Cocoa", exchange_id=ex.id)
    session.add(com)
    session.flush()
    c = RefContract(
        commodity_id=com.id,
        code=code,
        contract_month=code[-3:],
        is_active=active,
        active_from=active_from,
    )
    session.add(c)
    session.flush()
    return c.id


def _daily(session: Session, cid: uuid.UUID, on: date, *, oi: int, volume: int) -> None:
    session.add(
        PlContractDataDaily(
            date=on, contract_id=cid, close=Decimal("4000"), volume=volume, oi=oi
        )
    )


@pytest.fixture
def calendar_view(sync_db_session: Session):
    sync_db_session.execute(text(_CALENDAR_VIEW_DDL))
    yield
    sync_db_session.execute(text("DROP VIEW IF EXISTS v_contract_data_chained;"))


# --------------------------------------------------------------------------
# Resolver (sync)
# --------------------------------------------------------------------------
@pytest.mark.integration
def test_front_month_for_date_follows_calendar(sync_db_session: Session) -> None:
    from scripts.front_month import active_front_month, front_month_for_date

    can = _contract(sync_db_session, code="CAN26", active_from=date(2026, 4, 10))
    cau = _contract(
        sync_db_session, code="CAU26", active=True, active_from=date(2026, 6, 17)
    )

    # A May date is still CAN26; a July date is CAU26.
    assert front_month_for_date(sync_db_session, date(2026, 5, 20)) == can
    assert front_month_for_date(sync_db_session, date(2026, 7, 20)) == cau
    # The roll boundary is exact.
    assert front_month_for_date(sync_db_session, date(2026, 6, 16)) == can
    assert front_month_for_date(sync_db_session, date(2026, 6, 17)) == cau
    # Leading edge = latest roll.
    assert active_front_month(sync_db_session) == cau


@pytest.mark.integration
def test_front_month_raises_before_calendar_start(sync_db_session: Session) -> None:
    from scripts.front_month import FrontMonthError, front_month_for_date

    _contract(sync_db_session, code="CAU26", active=True, active_from=date(2026, 6, 17))
    # A date before any active_from has no front-month → fail-loud.
    with pytest.raises(FrontMonthError):
        front_month_for_date(sync_db_session, date(2026, 1, 1))


# --------------------------------------------------------------------------
# The 7th-incident guard: liquidity domination must NOT roll the chain
# --------------------------------------------------------------------------
@pytest.mark.integration
def test_liquidity_domination_does_not_roll_without_calendar(
    sync_db_session: Session, calendar_view
) -> None:
    """CAZ26 leads OI AND volume on a July date but was never rolled to
    (no active_from). The calendar VIEW must keep the date on CAU26 — the exact
    premature-roll the old oi/volume rule got wrong on 2026-07-17.
    """
    cau = _contract(
        sync_db_session, code="CAU26", active=True, active_from=date(2026, 6, 17)
    )
    caz = _contract(sync_db_session, code="CAZ26")  # NO active_from — never rolled

    day = date(2026, 7, 17)
    _daily(sync_db_session, cau, day, oi=45_000, volume=10_121)  # incumbent
    _daily(sync_db_session, caz, day, oi=60_000, volume=10_775)  # leads BOTH
    sync_db_session.flush()

    rows = sync_db_session.execute(
        text("SELECT contract_id FROM v_contract_data_chained WHERE date = :d"),
        {"d": day},
    ).all()

    assert len(rows) == 1
    assert rows[0].contract_id == cau  # calendar wins; CAZ26 is NOT selected


# --------------------------------------------------------------------------
# Resolver (async) — mirror
# --------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_async_resolver_matches_calendar(db_session) -> None:
    from app.utils.front_month import (
        active_front_month,
        front_month_for_date,
        front_month_for_date_or_none,
    )

    ex = RefExchange(code="ICE-AS", name="ICE", timezone="UTC")
    db_session.add(ex)
    await db_session.flush()
    com = RefCommodity(code="COCOA-AS", name="Cocoa", exchange_id=ex.id)
    db_session.add(com)
    await db_session.flush()
    cau = RefContract(
        commodity_id=com.id,
        code="CAU26",
        contract_month="U26",
        is_active=True,
        active_from=date(2026, 6, 17),
    )
    db_session.add(cau)
    await db_session.flush()

    assert await front_month_for_date(db_session, date(2026, 7, 1)) == cau.id
    assert await active_front_month(db_session) == cau.id
    # Non-raising variant returns None before the calendar starts.
    assert await front_month_for_date_or_none(db_session, date(2026, 1, 1)) is None
