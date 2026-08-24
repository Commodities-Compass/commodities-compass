"""Tests for roll-contract CLI and active contract code resolution."""

from contextlib import contextmanager
from datetime import date, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.models.reference import RefCommodity, RefContract, RefExchange
from scripts.contract_resolver import ContractResolverError, resolve_active_code


@contextmanager
def _session_cm(session):
    """Stand in for scripts.db.get_session (which commits); the fixture rolls back."""
    yield session


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

    def test_forward_roll_keeps_calendar_and_is_active_consistent(
        self, sync_db_session, contract_chain
    ):
        """A forward roll stamps a later active_from; the calendar leading edge
        (active_front_month) then equals is_active — the post-condition
        roll-contract asserts."""
        from scripts.front_month import active_front_month

        old = contract_chain["active"]  # CAK26
        new = contract_chain["inactive"]  # CAN26
        old.active_from = date(2026, 3, 2)
        old.is_active = False
        new.is_active = True
        new.active_from = date(2026, 4, 10)  # later → new leading edge
        sync_db_session.flush()

        assert active_front_month(sync_db_session) == new.id
        assert resolve_active_code(sync_db_session) == "CAN26"

    def test_backward_roll_without_restamp_desyncs_calendar(
        self, sync_db_session, contract_chain
    ):
        """Reactivating an EARLIER contract without re-stamping active_from leaves
        the calendar leading edge on the later contract — exactly the desync
        roll-contract's post-condition assert is designed to catch (the operator
        must pass --effective-date to re-stamp an intentional rollback)."""
        from scripts.front_month import active_front_month

        old = contract_chain["active"]  # CAK26 (earlier)
        new = contract_chain["inactive"]  # CAN26 (later)
        old.active_from = date(2026, 3, 2)
        new.active_from = date(2026, 4, 10)
        # Rollback: reactivate the earlier contract, keep its stale date.
        new.is_active = False
        old.is_active = True
        sync_db_session.flush()

        assert resolve_active_code(sync_db_session) == "CAK26"  # is_active
        assert active_front_month(sync_db_session) != old.id  # calendar disagrees


class TestRollContractMain:
    """End-to-end ``main()`` — the CLI the operator actually runs.

    Origin: 2026-08-24 pre-roll audit. ``main()`` had ZERO coverage; every test
    above hand-manipulates ORM objects and so could not see either defect below.
    """

    def _run(self, session, argv, *, next_session=date(2026, 4, 10)):
        from scripts import roll_contract

        with (
            patch.object(roll_contract, "get_session", lambda: _session_cm(session)),
            patch.object(
                roll_contract, "get_next_session_date", lambda _d: next_session
            ),
            patch("sys.argv", ["roll-contract", *argv]),
        ):
            return roll_contract.main()

    def test_repairs_a_half_rolled_state_instead_of_no_op(
        self, sync_db_session, contract_chain
    ):
        """is_active flipped by raw SQL but active_from never stamped.

        The CLI used to early-return 0 ("already active. Nothing to do.") BEFORE
        any active_from handling — leaving the calendar unrolled, the chained view
        frozen, and no CLI path to recover. It must repair instead.
        """
        old, new = contract_chain["active"], contract_chain["inactive"]
        old.active_from = date(2026, 3, 2)
        old.is_active = False
        new.is_active = True  # raw-SQL flip
        new.active_from = None  # ...calendar never stamped
        sync_db_session.flush()

        rc = self._run(sync_db_session, ["CAN26"])

        assert rc == 0
        sync_db_session.refresh(new)
        assert new.active_from == date(2026, 4, 10)  # repaired
        assert new.is_active is True

    def test_genuine_no_op_when_calendar_already_agrees(
        self, sync_db_session, contract_chain
    ):
        """Already active AND holding the leading edge → nothing to do, unchanged."""
        old, new = contract_chain["active"], contract_chain["inactive"]
        old.active_from = date(2026, 3, 2)
        old.is_active = False
        new.is_active = True
        new.active_from = date(2026, 4, 1)
        sync_db_session.flush()

        rc = self._run(sync_db_session, ["CAN26"])

        assert rc == 0
        sync_db_session.refresh(new)
        assert new.active_from == date(2026, 4, 1)  # NOT re-stamped

    def test_rejects_an_effective_date_far_in_the_future(
        self, sync_db_session, contract_chain
    ):
        """A year typo (2027-04-10) must not silently freeze the pipeline.

        The post-condition only checks "greatest active_from", which any future
        date satisfies — so nothing else catches this.
        """
        old, new = contract_chain["active"], contract_chain["inactive"]
        old.active_from = date(2026, 3, 2)
        sync_db_session.flush()
        far = date.today() + timedelta(days=400)

        rc = self._run(sync_db_session, ["CAN26", "--effective-date", far.isoformat()])

        assert rc == 1
        sync_db_session.refresh(new)
        assert new.active_from is None  # nothing written
        assert new.is_active is False

    def test_accepts_a_near_future_effective_date(
        self, sync_db_session, contract_chain
    ):
        """The legitimate case — next session, a few days out — still works."""
        old, new = contract_chain["active"], contract_chain["inactive"]
        old.active_from = date(2026, 3, 2)
        sync_db_session.flush()
        soon = date.today() + timedelta(days=3)

        rc = self._run(sync_db_session, ["CAN26", "--effective-date", soon.isoformat()])

        assert rc == 0
        sync_db_session.refresh(new)
        assert new.active_from == soon
