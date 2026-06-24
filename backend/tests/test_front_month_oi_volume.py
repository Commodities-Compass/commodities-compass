"""Front-month selection by OI AND volume — compute and the VIEW must agree.

Guards the split-brain that crashed the pipeline on 2026-06-23/24: an OI-only
crossover rolled the chain to the next contract (CAZ26) while volume stayed on
the incumbent (CAU26), forking compute-indicators' ``pl_derived_indicators``
rows from the ensemble's ``v_contract_data_chained`` market_history (INNER JOIN
on ``(date, contract_id)`` then drops the latest date).

The roll now requires BOTH oi and volume to lead the next contract; on a split,
the incumbent (earliest ``contract_month``) holds. ``load_all_market_data``
(compute) and the VIEW (ensemble) implement the identical rule, so they must
resolve the SAME front-month for every date.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.engine.runner import load_all_market_data
from app.models.pipeline import PlContractDataDaily
from app.models.reference import RefCommodity, RefContract, RefExchange

# Mirrors alembic c7d8e9f0a1b2 verbatim — keep in sync if either changes.
_VIEW_DDL = """
CREATE OR REPLACE VIEW v_contract_data_chained AS
WITH per_date AS (
    SELECT date, MAX(COALESCE(oi, 0)) AS max_oi, MAX(COALESCE(volume, 0)) AS max_vol
    FROM pl_contract_data_daily WHERE close IS NOT NULL GROUP BY date
)
SELECT DISTINCT ON (d.date)
    d.date, d.display_date, d.contract_id,
    d.open, d.high, d.low, d.close, d.volume, d.oi, d.implied_volatility
FROM pl_contract_data_daily d
JOIN ref_contract c ON c.id = d.contract_id
JOIN per_date pd ON pd.date = d.date
WHERE d.close IS NOT NULL
ORDER BY d.date ASC,
    (COALESCE(d.oi, 0) >= pd.max_oi AND COALESCE(d.volume, 0) >= pd.max_vol) DESC,
    c.contract_month ASC;
"""

_BASE = date(2026, 6, 22)


def _day(i: int) -> date:
    return _BASE + timedelta(days=i)


def _seed_contract(
    session: Session, *, code: str, contract_month: str, is_active: bool = False
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
        contract_month=contract_month,
        is_active=is_active,
    )
    session.add(c)
    session.flush()
    return c.id


def _ohlcv(
    session: Session, contract_id: uuid.UUID, on_date: date, *, oi: int, volume: int
) -> None:
    session.add(
        PlContractDataDaily(
            date=on_date,
            display_date=on_date,
            contract_id=contract_id,
            close=Decimal("3500"),
            oi=oi,
            volume=volume,
        )
    )


@pytest.fixture
def chained_view(sync_db_session: Session):
    sync_db_session.execute(text(_VIEW_DDL))
    yield
    sync_db_session.execute(text("DROP VIEW IF EXISTS v_contract_data_chained;"))


def _norm(d: object) -> date:
    return d.date() if hasattr(d, "date") else d  # type: ignore[return-value]


def _compute_front(session: Session) -> dict[date, str]:
    df = load_all_market_data(session)
    return {_norm(d): c for d, c in zip(df["date"], df["contract_code"])}


def _view_front(session: Session) -> dict[date, str]:
    rows = session.execute(
        text(
            "SELECT v.date, c.code FROM v_contract_data_chained v "
            "JOIN ref_contract c ON c.id = v.contract_id ORDER BY v.date"
        )
    ).fetchall()
    return {_norm(r[0]): r[1] for r in rows}


@pytest.mark.integration
def test_oi_only_crossover_stays_incumbent(
    sync_db_session: Session, chained_view
) -> None:
    """Real 2026-06-23/24 shape: CAZ26 leads OI, CAU26 leads volume → stay CAU26."""
    s = sync_db_session
    cau = _seed_contract(s, code="CAU26", contract_month="2026-09", is_active=True)
    caz = _seed_contract(s, code="CAZ26", contract_month="2026-12")
    for i in range(3):
        _ohlcv(s, cau, _day(i), oi=52000, volume=15000)  # lower OI, HIGHER volume
        _ohlcv(s, caz, _day(i), oi=52500, volume=8000)  # HIGHER OI, lower volume
    s.flush()

    cf, vf = _compute_front(s), _view_front(s)
    for i in range(3):
        assert cf[_day(i)] == "CAU26", f"compute D{i} must stay incumbent CAU26"
        assert vf[_day(i)] == "CAU26", f"view D{i} must stay incumbent CAU26"


@pytest.mark.integration
def test_oi_and_volume_both_lead_rolls_to_next(
    sync_db_session: Session, chained_view
) -> None:
    """Genuine roll: CAZ26 leads BOTH oi and volume → roll to CAZ26."""
    s = sync_db_session
    cau = _seed_contract(s, code="CAU26", contract_month="2026-09", is_active=True)
    caz = _seed_contract(s, code="CAZ26", contract_month="2026-12")
    for i in range(3):
        _ohlcv(s, cau, _day(i), oi=40000, volume=9000)
        _ohlcv(s, caz, _day(i), oi=55000, volume=18000)  # leads BOTH
    s.flush()

    cf, vf = _compute_front(s), _view_front(s)
    for i in range(3):
        assert cf[_day(i)] == "CAZ26", f"compute D{i} must roll to CAZ26"
        assert vf[_day(i)] == "CAZ26", f"view D{i} must roll to CAZ26"


@pytest.mark.integration
def test_incumbent_leads_both_until_next_takes_both(
    sync_db_session: Session, chained_view
) -> None:
    """CAN26 leads both D0..D1, CAU26 takes both D2 → clean monotonic roll."""
    s = sync_db_session
    can = _seed_contract(s, code="CAN26", contract_month="2026-07")
    cau = _seed_contract(s, code="CAU26", contract_month="2026-09", is_active=True)
    for i in range(3):
        _ohlcv(
            s,
            can,
            _day(i),
            oi=60000 if i < 2 else 30000,
            volume=12000 if i < 2 else 5000,
        )
        _ohlcv(
            s,
            cau,
            _day(i),
            oi=40000 if i < 2 else 50000,
            volume=7000 if i < 2 else 16000,
        )
    s.flush()

    cf, vf = _compute_front(s), _view_front(s)
    for i in range(2):
        assert cf[_day(i)] == "CAN26" and vf[_day(i)] == "CAN26", f"D{i} pre-roll CAN26"
    assert cf[_day(2)] == "CAU26" and vf[_day(2)] == "CAU26", "D2 both cross → CAU26"
