"""Roll watchdog — the liquidity-vs-calendar divergence query.

Guards the direction fix: a liquidity front-month NOT yet in the calendar
(active_from IS NULL) is a genuine forward-roll candidate → alert; one already in
the calendar is a backward blip that must NOT trigger a roll suggestion.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.models.pipeline import PlContractDataDaily
from app.models.reference import RefCommodity, RefContract, RefExchange
from scripts.roll_watchdog.main import _QUERY


def _contract(
    session: Session, code: str, *, active_from: date | None = None
) -> uuid.UUID:
    ex = RefExchange(code=f"ICE-{code}", name="ICE", timezone="UTC")
    session.add(ex)
    session.flush()
    com = RefCommodity(code=f"CC-{code}", name="Cocoa", exchange_id=ex.id)
    session.add(com)
    session.flush()
    c = RefContract(
        commodity_id=com.id,
        code=code,
        contract_month=code[-3:],
        is_active=active_from is not None,
        active_from=active_from,
    )
    session.add(c)
    session.flush()
    return c.id


def _daily(session: Session, cid: uuid.UUID, on: date, *, oi: int, vol: int) -> None:
    session.add(
        PlContractDataDaily(
            date=on, contract_id=cid, close=Decimal("4000"), volume=vol, oi=oi
        )
    )


@pytest.mark.integration
def test_query_flags_forward_divergence(sync_db_session: Session) -> None:
    """CAZ26 leads OI+volume but has no active_from → liq=CAZ26, cal=CAU26,
    liq_active_from=None → the watchdog alerts (genuine forward roll-due)."""
    cau = _contract(sync_db_session, "CAU26", active_from=date(2026, 6, 17))
    caz = _contract(sync_db_session, "CAZ26")  # never rolled to — no active_from
    day = date(2026, 7, 17)
    _daily(sync_db_session, cau, day, oi=45000, vol=10121)  # incumbent
    _daily(sync_db_session, caz, day, oi=60000, vol=10775)  # leads BOTH
    sync_db_session.flush()

    rows = sync_db_session.execute(_QUERY, {"lookback": 8}).all()
    assert len(rows) == 1
    r = rows[0]
    assert r.liq_code == "CAZ26"
    assert r.cal_code == "CAU26"
    assert r.liq_active_from is None  # → forward roll-due (alert)


@pytest.mark.integration
def test_query_no_divergence_when_incumbent_leads(sync_db_session: Session) -> None:
    """When the calendar front-month also leads OI+volume, liq == cal (quiet)."""
    cau = _contract(sync_db_session, "CAU26", active_from=date(2026, 6, 17))
    caz = _contract(sync_db_session, "CAZ26")
    day = date(2026, 7, 17)
    _daily(sync_db_session, cau, day, oi=60000, vol=15000)  # incumbent leads both
    _daily(sync_db_session, caz, day, oi=45000, vol=8000)
    sync_db_session.flush()

    rows = sync_db_session.execute(_QUERY, {"lookback": 8}).all()
    assert len(rows) == 1
    assert rows[0].liq_code == "CAU26"
    assert rows[0].cal_code == "CAU26"  # no divergence
