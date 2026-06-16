"""Integration tests for the chained trailing-window loaders.

Guards the contract-roll continuity fix in
``scripts.ensemble_compute.db_loader``: the Compass wrapper's trailing
self-evaluation inputs (recent orchestrator decisions + specialist votes) must
chain across a contract roll via ``v_contract_data_chained`` (front-month-by-OI)
instead of resetting to a NaN-bootstrap window the moment ``ref_contract.is_active``
flips to the new code. The join also de-dups the transient duplicate rows a roll
backfill leaves behind (old + new contract both have a row for a crossover date).

The VIEW is created by Alembic (n8i9j0k1l2m3 / r2m3n4o5p6q7), not by
``Base.metadata.create_all()``, so — exactly like ``test_v_contract_data_chained``
— we materialize it per test and drop it after.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.pipeline import (
    PlAlgorithmVersion,
    PlContractDataDaily,
    PlOrchestratorDecision,
    PlSpecialistPrediction,
)
from app.models.reference import RefCommodity, RefContract, RefExchange
from scripts.ensemble_compute.db_loader import (
    load_recent_orchestrator_decisions,
    load_recent_specialist_votes,
)

# Identical to the live view (post r2m3n4o5p6q7 — no legacy stock/cot columns).
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

# CAN26 (July) is rolling off; CAU26 (Sep) is the new front-month. Mirrors the
# real CAN26 → CAU26 roll this fix is being shipped for.
_CAN_MARK = Decimal("-0.5")  # net_score marker on CAN26 decisions
_CAU_MARK = Decimal("0.5")  # net_score marker on CAU26 decisions
_BASE = date(2026, 6, 1)


def _day(i: int) -> date:
    return _BASE + timedelta(days=i)


def _seed_contract(session: Session, *, code: str) -> uuid.UUID:
    exchange = RefExchange(code=f"ICE-{code}", name="ICE", timezone="UTC")
    session.add(exchange)
    session.flush()
    commodity = RefCommodity(
        code=f"COCOA-{code}", name="Cocoa", exchange_id=exchange.id
    )
    session.add(commodity)
    session.flush()
    contract = RefContract(
        commodity_id=commodity.id, code=code, contract_month=code[-3:], is_active=False
    )
    session.add(contract)
    session.flush()
    return contract.id


def _seed_algo(session: Session) -> uuid.UUID:
    av = PlAlgorithmVersion(
        name="ensemble_v1_softgate_wrapper", version="1.0.0", horizon="swing"
    )
    session.add(av)
    session.flush()
    return av.id


def _add_ohlcv(
    session: Session, contract_id: uuid.UUID, on_date: date, *, oi: int
) -> None:
    session.add(
        PlContractDataDaily(
            date=on_date, contract_id=contract_id, close=Decimal("2000"), oi=oi
        )
    )


def _add_decision(
    session: Session,
    contract_id: uuid.UUID,
    algo_id: uuid.UUID,
    on_date: date,
    *,
    net_score: Decimal,
) -> None:
    session.add(
        PlOrchestratorDecision(
            date=on_date,
            contract_id=contract_id,
            algorithm_version_id=algo_id,
            soft_gate_decision="OPEN",
            net_score=net_score,
            weights_sum=Decimal("1"),
            n_committed_specialists=10,
            decision_wrapped="OPEN",
            wrapper_active=False,
            fired_running_acc=False,
            fired_trend=False,
            fired_dispersion=False,
            fired_three_way=False,
        )
    )


def _add_votes(
    session: Session,
    contract_id: uuid.UUID,
    algo_id: uuid.UUID,
    on_date: date,
    *,
    pred: str,
) -> None:
    for name in ("w1", "w2", "s1", "s2"):
        session.add(
            PlSpecialistPrediction(
                date=on_date,
                contract_id=contract_id,
                algorithm_version_id=algo_id,
                specialist_name=name,
                window_months=12,
                pred=pred,
            )
        )


@pytest.fixture
def chained_view(sync_db_session: Session):
    sync_db_session.execute(text(_VIEW_DDL))
    yield
    sync_db_session.execute(text("DROP VIEW IF EXISTS v_contract_data_chained;"))


@pytest.mark.integration
def test_decisions_window_is_single_contract_on_normal_days(
    sync_db_session: Session, chained_view
) -> None:
    """No roll: one contract per date → identical to the old contract-filtered query.

    The ``contract_id`` arg is now ignored; we pass the *other* contract's id to
    prove it. The window must still return every CAN26 row, one per date.
    """
    s = sync_db_session
    algo_id = _seed_algo(s)
    can = _seed_contract(s, code="CAN26")
    other = _seed_contract(s, code="CAU26")  # no data — proves arg is ignored
    for i in range(7):
        _add_ohlcv(s, can, _day(i), oi=100)
        _add_decision(s, can, algo_id, _day(i), net_score=_CAN_MARK)
    s.flush()

    df = load_recent_orchestrator_decisions(
        s,
        end_date=_day(7),
        contract_id=other,
        algorithm_version_id=algo_id,
        lookback=50,
    )

    assert df["date"].dt.date.tolist() == [_day(i) for i in range(7)]
    assert {round(float(x), 3) for x in df["net_score"]} == {-0.5}


@pytest.mark.integration
def test_decisions_window_chains_and_dedups_across_roll(
    sync_db_session: Session, chained_view
) -> None:
    """Crossover at D4: CAN26 front D0..D3, CAU26 front D4..D6.

    CAN26 wrote a decision every day (live, lagging the roll); CAU26 has the
    rewrite for D4..D6 → duplicate rows on D4/D5/D6. The chained window must
    return exactly one row per date (dedup) and pick the front-month contract
    per date (CAN26 marker pre-crossover, CAU26 marker post-crossover).
    """
    s = sync_db_session
    algo_id = _seed_algo(s)
    can = _seed_contract(s, code="CAN26")
    cau = _seed_contract(s, code="CAU26")

    # OHLCV: CAN26 dominant D0..D3 (oi 200), rolled off D4..D6 (oi 50).
    #        CAU26 appears at the crossover D4..D6 (oi 300 = front-month).
    for i in range(7):
        _add_ohlcv(s, can, _day(i), oi=200 if i < 4 else 50)
    for i in range(4, 7):
        _add_ohlcv(s, cau, _day(i), oi=300)

    # Decisions: CAN26 every day; CAU26 rewrite D4..D6 (→ dup rows D4/D5/D6).
    for i in range(7):
        _add_decision(s, can, algo_id, _day(i), net_score=_CAN_MARK)
    for i in range(4, 7):
        _add_decision(s, cau, algo_id, _day(i), net_score=_CAU_MARK)
    s.flush()

    df = load_recent_orchestrator_decisions(
        s, end_date=_day(7), contract_id=can, algorithm_version_id=algo_id, lookback=50
    )

    # One row per date — D4/D5/D6 duplicates collapsed by the join.
    assert df["date"].dt.date.tolist() == [_day(i) for i in range(7)]
    marker = {
        d: round(float(n), 3) for d, n in zip(df["date"].dt.date, df["net_score"])
    }
    for i in range(4):
        assert marker[_day(i)] == -0.5, f"D{i} should be CAN26 front-month"
    for i in range(4, 7):
        assert marker[_day(i)] == 0.5, f"D{i} should be CAU26 front-month"


@pytest.mark.integration
def test_votes_window_chains_and_dedups_across_roll(
    sync_db_session: Session, chained_view
) -> None:
    """Same crossover scenario for specialist votes (cluster-dispersion input)."""
    s = sync_db_session
    algo_id = _seed_algo(s)
    can = _seed_contract(s, code="CAN26")
    cau = _seed_contract(s, code="CAU26")

    for i in range(7):
        _add_ohlcv(s, can, _day(i), oi=200 if i < 4 else 50)
    for i in range(4, 7):
        _add_ohlcv(s, cau, _day(i), oi=300)

    for i in range(7):
        _add_votes(s, can, algo_id, _day(i), pred="HEDGE")  # CAN26 marker
    for i in range(4, 7):
        _add_votes(s, cau, algo_id, _day(i), pred="OPEN")  # CAU26 marker
    s.flush()

    # Window upper bound is end_date - 1 day = D6; lookback covers D0..D6.
    df = load_recent_specialist_votes(
        s,
        end_date=_day(7),
        contract_id=can,
        algorithm_version_id=algo_id,
        lookback_days=60,
    )

    # 7 dates × 4 specialists, no doubling on D4..D6.
    assert len(df) == 7 * 4
    per_date_count = df.groupby(df["date"].dt.date)["specialist_name"].count()
    assert (per_date_count == 4).all()
    preds = df.groupby(df["date"].dt.date)["pred"].agg(lambda x: set(x)).to_dict()
    for i in range(4):
        assert preds[_day(i)] == {"HEDGE"}, f"D{i} should be CAN26 front-month"
    for i in range(4, 7):
        assert preds[_day(i)] == {"OPEN"}, f"D{i} should be CAU26 front-month"
