"""Tests for the v_contract_data_chained VIEW (front-month-by-OI series).

The VIEW is created by Alembic migration n8i9j0k1l2m3, not by
``Base.metadata.create_all()``. We re-create it explicitly per test so
the regression suite doesn't depend on Alembic ordering.
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


_VIEW_DDL = """
CREATE OR REPLACE VIEW v_contract_data_chained AS
SELECT DISTINCT ON (date)
    date, display_date, contract_id,
    open, high, low, close, volume, oi, implied_volatility,
    stock_us, stock_eu_bags60kg, com_net_us
FROM pl_contract_data_daily
WHERE close IS NOT NULL
ORDER BY
    date ASC,
    COALESCE(oi, 0) DESC,
    COALESCE(volume, 0) DESC,
    contract_id ASC;
"""


def _seed_contract(session: Session, *, code: str) -> uuid.UUID:
    """Seed a ref_exchange → ref_commodity → ref_contract chain."""
    exchange = RefExchange(code=f"ICE-{code}", name="ICE", timezone="UTC")
    session.add(exchange)
    session.flush()
    commodity = RefCommodity(
        code=f"COCOA-{code}",
        name="Cocoa",
        exchange_id=exchange.id,
    )
    session.add(commodity)
    session.flush()
    contract = RefContract(
        commodity_id=commodity.id,
        code=code,
        contract_month=code[-3:],
        is_active=False,
    )
    session.add(contract)
    session.flush()
    return contract.id


def _seed_daily(
    session: Session,
    *,
    contract_id: uuid.UUID,
    on_date: date,
    close: float,
    oi: int,
    volume: int = 100,
) -> None:
    row = PlContractDataDaily(
        date=on_date,
        contract_id=contract_id,
        close=Decimal(str(close)),
        volume=volume,
        oi=oi,
    )
    session.add(row)


@pytest.fixture
def chained_view(sync_db_session: Session):
    """Create v_contract_data_chained for this test, drop it after."""
    sync_db_session.execute(text(_VIEW_DDL))
    yield
    sync_db_session.execute(text("DROP VIEW IF EXISTS v_contract_data_chained;"))


@pytest.mark.integration
def test_chained_view_picks_highest_oi_per_date(
    sync_db_session: Session, chained_view
) -> None:
    """When two contracts trade on the same date, the higher-OI row wins."""
    c1 = _seed_contract(sync_db_session, code="CAH26")
    c2 = _seed_contract(sync_db_session, code="CAK26")

    # Day where CAH26 dominates (higher OI).
    _seed_daily(
        sync_db_session,
        contract_id=c1,
        on_date=date(2026, 2, 25),
        close=8000.0,
        oi=50000,
    )
    _seed_daily(
        sync_db_session,
        contract_id=c2,
        on_date=date(2026, 2, 25),
        close=8050.0,
        oi=20000,
    )

    # Day after roll: CAK26 dominates.
    _seed_daily(
        sync_db_session,
        contract_id=c1,
        on_date=date(2026, 3, 2),
        close=8100.0,
        oi=10000,
    )
    _seed_daily(
        sync_db_session,
        contract_id=c2,
        on_date=date(2026, 3, 2),
        close=8150.0,
        oi=60000,
    )
    sync_db_session.flush()

    rows = sync_db_session.execute(
        text(
            "SELECT date, contract_id, close, oi "
            "FROM v_contract_data_chained "
            "WHERE date BETWEEN '2026-02-25' AND '2026-03-02' "
            "ORDER BY date ASC"
        )
    ).fetchall()
    assert len(rows) == 2
    # Pre-roll: CAH26 wins (oi=50k).
    assert rows[0].contract_id == c1
    assert float(rows[0].close) == 8000.0
    # Post-roll: CAK26 wins (oi=60k).
    assert rows[1].contract_id == c2
    assert float(rows[1].close) == 8150.0


@pytest.mark.integration
def test_chained_view_continuous_across_roll(
    sync_db_session: Session, chained_view
) -> None:
    """Seed two contracts across a roll boundary; the VIEW returns one row per date."""
    c1 = _seed_contract(sync_db_session, code="CAH26")
    c2 = _seed_contract(sync_db_session, code="CAK26")

    # CAH26 trades Feb 23-27. CAK26 trades Feb 26 onwards. Roll on Mar 2.
    for day, oi_h, oi_k in [
        (23, 60000, 5000),  # CAH26 front
        (24, 60000, 6000),
        (25, 58000, 8000),
        (26, 55000, 15000),
        (27, 52000, 25000),
        # Mar 2: roll — CAK26 takes over.
    ]:
        _seed_daily(
            sync_db_session,
            contract_id=c1,
            on_date=date(2026, 2, day),
            close=8000.0 + day,
            oi=oi_h,
        )
        _seed_daily(
            sync_db_session,
            contract_id=c2,
            on_date=date(2026, 2, day),
            close=8050.0 + day,
            oi=oi_k,
        )
    _seed_daily(
        sync_db_session,
        contract_id=c2,
        on_date=date(2026, 3, 2),
        close=8100.0,
        oi=60000,
    )
    sync_db_session.flush()

    rows = sync_db_session.execute(
        text(
            "SELECT date, contract_id FROM v_contract_data_chained "
            "WHERE date >= '2026-02-23' ORDER BY date ASC"
        )
    ).fetchall()
    # 5 dates of dual trading + 1 day post-roll = 6 distinct dates.
    assert len(rows) == 6
    # All pre-roll dates should pick CAH26 (higher OI).
    pre_roll = [r for r in rows if r.date < date(2026, 3, 2)]
    assert len(pre_roll) == 5
    assert all(r.contract_id == c1 for r in pre_roll)
    # Post-roll: only CAK26 exists → that's the chained pick.
    post_roll = [r for r in rows if r.date >= date(2026, 3, 2)]
    assert len(post_roll) == 1
    assert post_roll[0].contract_id == c2


@pytest.mark.integration
def test_chained_view_excludes_null_close(
    sync_db_session: Session, chained_view
) -> None:
    """Rows with NULL close are excluded from the VIEW."""
    c1 = _seed_contract(sync_db_session, code="CAH26")
    # Row with NULL close
    sync_db_session.add(
        PlContractDataDaily(
            date=date(2026, 2, 25),
            contract_id=c1,
            close=None,
            oi=50000,
            volume=100,
        )
    )
    sync_db_session.flush()

    rows = sync_db_session.execute(
        text(
            "SELECT COUNT(*) AS n FROM v_contract_data_chained "
            "WHERE date = '2026-02-25'"
        )
    ).fetchone()
    assert rows is not None and rows.n == 0
