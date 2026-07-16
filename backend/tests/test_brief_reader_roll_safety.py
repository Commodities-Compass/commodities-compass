"""Issue #67 — the ensemble brief's YTD / running-accuracy must stay roll-safe
and in lock step with the dashboard.

#65 made the dashboard scoring decision-aware (front-month = highest-OI contract
that CARRIES a decision) but left the brief's sync copies on an OI-only
front-month, so at a roll the podcast YTD could diverge from the dashboard. This
locks the fixed behaviour: on a roll day where the not-yet-rolled new contract
leads OI but has no decision, the series still resolves to the OLD
decision-carrying contract.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from scripts.compass_brief_ensemble.db_reader import (
    _compute_ytd_score,
    _decision_aware_front_month_rows,
)
from tests.factories import (
    make_pl_algorithm_version,
    make_pl_contract_data_daily,
    make_pl_indicator_daily,
    make_ref_commodity,
    make_ref_contract,
    make_ref_exchange,
)


def _seed_chain(session: Session):
    ex = make_ref_exchange(code="ICE_ROLL67")
    session.add(ex)
    session.flush()
    com = make_ref_commodity(ex.id, code="CC_ROLL67")
    session.add(com)
    session.flush()
    old = make_ref_contract(com.id, code="CAOLD67", is_active=False)
    new = make_ref_contract(com.id, code="CANEW67", is_active=True)
    ens = make_pl_algorithm_version(
        name="ensemble_v1_softgate_wrapper", version="1.0.0"
    )
    leg = make_pl_algorithm_version(name="legacy", version="1.0.0")
    session.add_all([old, new, ens, leg])
    session.flush()
    return old.id, new.id, ens.id


class TestBriefRollSafety:
    def _seed_roll(self, session: Session):
        old_id, new_id, ens_id = _seed_chain(session)
        days = [date(2026, 6, 1) + timedelta(days=i) for i in range(6)]
        roll_day = days[-1]
        for i, d in enumerate(days):
            # OLD contract: OHLCV + an ensemble decision every day. OI leads
            # until the roll day, where it drops below the new contract.
            oi = 500 if d == roll_day else 1000
            session.add(
                make_pl_contract_data_daily(
                    old_id, date=d, close=Decimal(4000 + i * 10), oi=oi
                )
            )
            session.add(
                make_pl_indicator_daily(
                    old_id, ens_id, date=d, decision="OPEN", language="fr"
                )
            )
        # NEW contract: OHLCV only on the roll day, HIGHER OI, but NO decision.
        session.add(
            make_pl_contract_data_daily(
                new_id, date=roll_day, close=Decimal(9999), oi=2000
            )
        )
        session.flush()
        return days, roll_day

    def test_roll_day_resolves_to_decision_contract_not_top_oi(
        self, sync_db_session: Session
    ):
        days, roll_day = self._seed_roll(sync_db_session)
        rows = _decision_aware_front_month_rows(sync_db_session, days[0], roll_day)
        by_date = {r.date: r for r in rows}

        # Every day is retained (OI-only would have dropped the roll day).
        assert len(by_date) == len(days)
        # The roll day resolves to the OLD decision-carrying contract, not the
        # higher-OI new contract (close 9999 / no decision).
        assert by_date[roll_day].decision == "OPEN"
        assert float(by_date[roll_day].close) != 9999.0

    def test_ytd_score_does_not_drop_the_roll_day(self, sync_db_session: Session):
        days, _ = self._seed_roll(sync_db_session)
        # Rising closes + OPEN each day → every scored day is a win → non-None,
        # positive. The OI-only front-month would have nulled the roll day's
        # decision and could freeze the YTD.
        score = _compute_ytd_score(sync_db_session, days[-1])
        assert score is not None
        assert score > 0
