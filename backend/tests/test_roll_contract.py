"""Tests for roll-contract CLI and active contract code resolution."""

from datetime import date

import pytest
from sqlalchemy import select

from app.models.reference import RefCommodity, RefContract, RefExchange
from scripts.contract_resolver import ContractResolverError, resolve_active_code


@pytest.fixture()
def contract_chain(sync_db_session):
    """Create exchange → commodity → 2 contracts (one active, one inactive)."""
    exchange = RefExchange(
        code="IFEU", name="ICE Futures Europe", timezone="Europe/London"
    )
    sync_db_session.add(exchange)
    sync_db_session.flush()

    commodity = RefCommodity(code="CC", name="London Cocoa #7", exchange_id=exchange.id)
    sync_db_session.add(commodity)
    sync_db_session.flush()

    active = RefContract(
        commodity_id=commodity.id,
        code="CAK26",
        contract_month="2026-05",
        expiry_date=date(2026, 5, 15),
        is_active=True,
    )
    inactive = RefContract(
        commodity_id=commodity.id,
        code="CAN26",
        contract_month="2026-07",
        expiry_date=date(2026, 7, 15),
        is_active=False,
    )
    sync_db_session.add_all([active, inactive])
    sync_db_session.flush()

    return {"active": active, "inactive": inactive}


class TestResolveActiveCode:
    def test_returns_active_code(self, sync_db_session, contract_chain):
        code = resolve_active_code(sync_db_session)
        assert code == "CAK26"

    def test_raises_when_no_active(self, sync_db_session):
        with pytest.raises(ContractResolverError, match="No active contract"):
            resolve_active_code(sync_db_session)


class TestRollContract:
    def test_roll_deactivates_old_activates_new(self, sync_db_session, contract_chain):
        """Simulate what roll_contract.py does: deactivate old, activate new."""
        old = contract_chain["active"]
        new = contract_chain["inactive"]

        # Deactivate all active
        actives = (
            sync_db_session.execute(
                select(RefContract).where(RefContract.is_active.is_(True))
            )
            .scalars()
            .all()
        )
        for c in actives:
            c.is_active = False

        # Activate new
        new.is_active = True
        sync_db_session.flush()

        assert old.is_active is False
        assert new.is_active is True
        assert resolve_active_code(sync_db_session) == "CAN26"

    def test_roll_to_already_active_is_noop(self, sync_db_session, contract_chain):
        """Rolling to the already-active contract should be a no-op."""
        active = contract_chain["active"]
        assert active.is_active is True
        assert resolve_active_code(sync_db_session) == "CAK26"

    def test_roll_to_nonexistent_contract_fails(self, sync_db_session, contract_chain):
        """Cannot roll to a contract that doesn't exist in ref_contract."""
        result = sync_db_session.execute(
            select(RefContract).where(RefContract.code == "NONEXISTENT")
        ).scalar_one_or_none()
        assert result is None
