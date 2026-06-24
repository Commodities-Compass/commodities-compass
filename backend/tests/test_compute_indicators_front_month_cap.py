"""Integration tests: compute-indicators front-month chain is capped at is_active.

Guards the roll-split-brain fix in ``app.engine.runner.load_all_market_data``:
the front-month-by-OI chain must never roll onto a contract whose delivery month
is later than ``ref_contract.is_active``. A premature/marginal OI crossover on a
not-yet-activated future contract (CAZ26 OI nudging past CAU26 in June, months
before the real Sep -> Dec roll) must NOT fork the indicator row onto CAZ26 while
daily-analysis / ensemble / dashboard stay on CAU26 — that divergence crashed
cc-daily-analysis on 2026-06-23 ("No indicator data found for CAU26 / legacy").
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.engine.runner import load_all_market_data
from app.models.pipeline import PlContractDataDaily
from app.models.reference import RefCommodity, RefContract, RefExchange

_BASE = date(2026, 6, 17)


def _day(i: int) -> date:
    return _BASE + timedelta(days=i)


def _seed_contract(
    session: Session, *, code: str, contract_month: str, is_active: bool
) -> uuid.UUID:
    exchange = RefExchange(code=f"ICE-{code}", name="ICE", timezone="UTC")
    session.add(exchange)
    session.flush()
    commodity = RefCommodity(
        code=f"COCOA-{code}", name="Cocoa", exchange_id=exchange.id
    )
    session.add(commodity)
    session.flush()
    contract = RefContract(
        commodity_id=commodity.id,
        code=code,
        contract_month=contract_month,
        is_active=is_active,
    )
    session.add(contract)
    session.flush()
    return contract.id


def _add_ohlcv(
    session: Session, contract_id: uuid.UUID, on_date: date, *, oi: int
) -> None:
    session.add(
        PlContractDataDaily(
            date=on_date, contract_id=contract_id, close=Decimal("3500"), oi=oi
        )
    )


def _by_date(df) -> dict[date, str]:
    def _norm(d: object) -> date:
        return d.date() if hasattr(d, "date") else d  # type: ignore[return-value]

    return {_norm(d): c for d, c in zip(df["date"], df["contract_code"])}


@pytest.mark.integration
def test_chain_ignores_premature_oi_crossover_on_future_contract(
    sync_db_session: Session,
) -> None:
    """CAZ26 (future, not yet rolled) nudges past CAU26 on the last day → ignored."""
    s = sync_db_session
    cau = _seed_contract(s, code="CAU26", contract_month="2026-09", is_active=True)
    caz = _seed_contract(s, code="CAZ26", contract_month="2026-12", is_active=False)

    for i in range(5):
        _add_ohlcv(s, cau, _day(i), oi=52000)
    for i in range(5):
        # CAZ26 below CAU26 until the last day, then crosses by a hair (+300).
        _add_ohlcv(s, caz, _day(i), oi=50000 if i < 4 else 52300)
    s.flush()

    by_date = _by_date(load_all_market_data(s))

    # Every date resolves to the ACTIVE contract — the premature CAZ26 crossover
    # on the last day is excluded by the cap.
    for i in range(5):
        assert by_date[_day(i)] == "CAU26", f"D{i} must stay on active CAU26"


@pytest.mark.integration
def test_chain_follows_oi_among_contracts_up_to_active(
    sync_db_session: Session,
) -> None:
    """Historical chaining preserved: among contracts <= active, highest OI wins.

    CAN26 (Jul) is the past front-month; CAU26 (Sep) is now active. Pre-roll
    dates must still resolve to CAN26 (it had the OI), post-roll to CAU26.
    """
    s = sync_db_session
    can = _seed_contract(s, code="CAN26", contract_month="2026-07", is_active=False)
    cau = _seed_contract(s, code="CAU26", contract_month="2026-09", is_active=True)

    for i in range(5):
        _add_ohlcv(s, can, _day(i), oi=60000 if i < 3 else 40000)
    for i in range(5):
        _add_ohlcv(s, cau, _day(i), oi=45000 if i < 3 else 55000)
    s.flush()

    by_date = _by_date(load_all_market_data(s))
    for i in range(3):
        assert by_date[_day(i)] == "CAN26", f"D{i} pre-roll → CAN26"
    for i in range(3, 5):
        assert by_date[_day(i)] == "CAU26", f"D{i} post-roll → CAU26"
