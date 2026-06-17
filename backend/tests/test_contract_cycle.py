"""Tests for the delivery-month cycle helpers + ensure_contract auto-register.

These back the multi-contract scrape (front + next delivery month) that makes a
contract roll a data-layer non-event: v_contract_data_chained always has both
contracts so front-month-by-OI auto-switches at the true crossover.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.reference import RefCommodity, RefContract, RefExchange
from scripts.contract_resolver import (
    ContractResolverError,
    contract_month_for,
    ensure_contract,
    next_contract_code,
)


@pytest.mark.unit
@pytest.mark.parametrize(
    "code,expected",
    [
        ("CAH26", "CAK26"),  # Mar -> May
        ("CAK26", "CAN26"),  # May -> Jul
        ("CAN26", "CAU26"),  # Jul -> Sep
        ("CAU26", "CAZ26"),  # Sep -> Dec
        ("CAZ26", "CAH27"),  # Dec -> Mar next year (year roll)
        ("cau26", "CAZ26"),  # case-insensitive
    ],
)
def test_next_contract_code(code: str, expected: str) -> None:
    assert next_contract_code(code) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "code,expected",
    [
        ("CAH26", "2026-03"),
        ("CAK26", "2026-05"),
        ("CAN26", "2026-07"),
        ("CAU26", "2026-09"),
        ("CAZ26", "2026-12"),
        ("CAH27", "2027-03"),
    ],
)
def test_contract_month_for(code: str, expected: str) -> None:
    assert contract_month_for(code) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "bad", ["CCU26", "CAA26", "CAU2", "CAUXY", "XYZ", "CAU260", ""]
)
def test_parse_fails_loud_on_bad_codes(bad: str) -> None:
    with pytest.raises(ContractResolverError):
        next_contract_code(bad)


@pytest.fixture()
def commodity_id(sync_db_session: Session):
    exchange = RefExchange(
        code="IFEU", name="ICE Futures Europe", timezone="Europe/London"
    )
    sync_db_session.add(exchange)
    sync_db_session.flush()
    commodity = RefCommodity(code="CA", name="London Cocoa #7", exchange_id=exchange.id)
    sync_db_session.add(commodity)
    sync_db_session.flush()
    return commodity.id


@pytest.mark.integration
def test_ensure_contract_creates_when_missing(sync_db_session, commodity_id) -> None:
    cid = ensure_contract(sync_db_session, "CAZ26", commodity_id=commodity_id)
    row = sync_db_session.execute(
        select(RefContract).where(RefContract.code == "CAZ26")
    ).scalar_one()
    assert row.id == cid
    assert row.contract_month == "2026-12"
    assert row.is_active is False
    assert row.expiry_date is None  # never fabricated


@pytest.mark.integration
def test_ensure_contract_idempotent(sync_db_session, commodity_id) -> None:
    first = ensure_contract(sync_db_session, "CAZ26", commodity_id=commodity_id)
    second = ensure_contract(sync_db_session, "CAZ26", commodity_id=commodity_id)
    assert first == second
    rows = (
        sync_db_session.execute(select(RefContract).where(RefContract.code == "CAZ26"))
        .scalars()
        .all()
    )
    assert len(rows) == 1  # no duplicate


@pytest.mark.integration
def test_ensure_contract_returns_existing(sync_db_session, commodity_id) -> None:
    existing = RefContract(
        commodity_id=commodity_id,
        code="CAU26",
        contract_month="2026-09",
        is_active=True,
    )
    sync_db_session.add(existing)
    sync_db_session.flush()
    cid = ensure_contract(sync_db_session, "CAU26", commodity_id=commodity_id)
    assert cid == existing.id
    # untouched — still active, not duplicated
    rows = (
        sync_db_session.execute(select(RefContract).where(RefContract.code == "CAU26"))
        .scalars()
        .all()
    )
    assert len(rows) == 1 and rows[0].is_active is True
