"""Regression: get_chart_data must span a contract roll via the chained
front-month series (v_contract_data_chained), for ALL window sizes — including
the short 5-day ticker window — and must not duplicate dates once the daily
back-month scrape writes a 2nd contract per date.

Repro of the 2026-06-17 CAN26→CAU26 incident: after the roll the active
contract (CAU26) had a single row, so the old active-contract-first query with
its row-count fallback returned only that one row for short windows → "only
today's session shows, nothing before the roll".
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline import PlContractDataDaily
from app.models.reference import RefCommodity, RefContract, RefExchange
from app.services.dashboard_service import get_chart_data

_VIEW_DDL = """
CREATE OR REPLACE VIEW v_contract_data_chained AS
SELECT DISTINCT ON (date)
    date, display_date, contract_id,
    open, high, low, close, volume, oi, implied_volatility
FROM pl_contract_data_daily
WHERE close IS NOT NULL
ORDER BY
    date ASC,
    COALESCE(oi, 0) DESC,
    COALESCE(volume, 0) DESC,
    contract_id ASC;
"""

_BASE = date(2026, 6, 10)


def _day(i: int) -> date:
    return _BASE + timedelta(days=i)


async def _contract(db: AsyncSession, code: str) -> uuid.UUID:
    ex = RefExchange(code=f"ICE-{code}", name="ICE", timezone="UTC")
    db.add(ex)
    await db.flush()
    com = RefCommodity(code=f"CC-{code}", name="Cocoa", exchange_id=ex.id)
    db.add(com)
    await db.flush()
    c = RefContract(
        commodity_id=com.id,
        code=code,
        contract_month=code[-3:],
        is_active=(code == "CAU26"),
    )
    db.add(c)
    await db.flush()
    return c.id


async def _ohlcv(
    db: AsyncSession, cid, on_date: date, *, close: float, oi: int
) -> None:
    db.add(
        PlContractDataDaily(
            date=on_date, contract_id=cid, close=Decimal(str(close)), volume=100, oi=oi
        )
    )


@pytest.mark.integration
async def test_chart_data_spans_roll_and_dedups_short_window(
    db_session: AsyncSession,
) -> None:
    can = await _contract(db_session, "CAN26")
    cau = await _contract(db_session, "CAU26")
    caz = await _contract(db_session, "CAZ26")

    # D0..D3 pre-roll = CAN26 (close 2000). D4 = roll day: CAU26 front-month
    # (oi 300, close 3000) + CAZ26 back-month duplicate (oi 50, close 9999 —
    # must be ignored by the front-month-by-OI chain).
    for i in range(4):
        await _ohlcv(db_session, can, _day(i), close=2000, oi=200)
    await _ohlcv(db_session, cau, _day(4), close=3000, oi=300)
    await _ohlcv(db_session, caz, _day(4), close=9999, oi=50)
    await db_session.flush()
    await db_session.execute(text(_VIEW_DDL))

    # days=5 is the exact window the LiveSignalStrip ticker uses — the case
    # the old row-count fallback never fired for.
    rows = await get_chart_data(db_session, days=5, end_date=_day(4))

    dates = [r["date"] for r in rows]
    # Spans the roll: one row per date D0..D4 (no pre-roll history dropped).
    assert dates == [_day(i).strftime("%Y-%m-%d") for i in range(5)]
    # No duplicate dates despite the CAZ26 back-month row on D4.
    assert len(dates) == len(set(dates))

    closes = {r["date"]: r["close"] for r in rows}
    for i in range(4):
        assert closes[_day(i).strftime("%Y-%m-%d")] == 2000.0  # CAN26 pre-roll
    # D4 picks CAU26 (front-month by OI), NOT the CAZ26 back-month (9999).
    assert closes[_day(4).strftime("%Y-%m-%d")] == 3000.0
