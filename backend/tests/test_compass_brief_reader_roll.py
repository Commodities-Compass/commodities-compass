"""Regression: DBBriefReader survives a contract roll (CAN26 -> CAU26).

Origin: 2026-06-17 prod incident — ``cc-compass-brief`` failed with
"Need at least 2 days of data, found 1" the evening a roll fired. The legacy
reader was ``is_active``-contract scoped, so the freshly-activated front month
(1 day of data) starved it while the prior front month held all the history.

Fix: resolve the front-month contract per date from ``v_contract_data_chained``
(front-month-by-OI) and key every per-date read on that ``contract_id`` instead
of ``ref_contract.is_active``. The brief then spans the roll boundary cleanly —
today = new front month, yesterday = the now-inactive prior front month.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from scripts.compass_brief.db_reader import DBBriefReader
from tests.factories import (
    make_pl_algorithm_version,
    make_pl_contract_data_daily,
    make_pl_indicator_daily,
    make_ref_commodity,
    make_ref_contract,
    make_ref_exchange,
)

# Mirrors Alembic migration n8i9j0k1l2m3 — created per test so the suite does
# not depend on Alembic ordering (same approach as test_v_contract_data_chained).
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


@pytest.fixture
def chained_view(sync_db_session: Session):
    sync_db_session.execute(text(_VIEW_DDL))
    yield
    sync_db_session.execute(text("DROP VIEW IF EXISTS v_contract_data_chained;"))


def _seed_roll(session: Session) -> None:
    """Seed the CAN26 -> CAU26 roll exactly as it landed in prod on 2026-06-17.

    - CAN26 (prior front, now inactive): full history through 06-16.
    - CAU26 (new front, active): a single 06-17 row.
    - CAZ26 (back month, scraped same day by the multi-contract scraper):
      a 06-17 row with *lower* OI than CAU26, so the chained view must NOT
      pick it for the roll day.
    """
    exchange = make_ref_exchange(code="ICE_EU_ROLL")
    session.add(exchange)
    session.flush()
    commodity = make_ref_commodity(exchange.id, code="CC_ROLL")
    session.add(commodity)
    session.flush()

    can = make_ref_contract(
        commodity.id, code="CAN26", contract_month="N26", is_active=False
    )
    cau = make_ref_contract(
        commodity.id, code="CAU26", contract_month="U26", is_active=True
    )
    caz = make_ref_contract(
        commodity.id, code="CAZ26", contract_month="Z26", is_active=False
    )
    session.add_all([can, cau, caz])
    session.flush()

    algo = make_pl_algorithm_version(name="legacy", version="1.0.0", is_active=True)
    session.add(algo)
    session.flush()

    # CAN26 history (pre-roll front month).
    session.add(
        make_pl_contract_data_daily(
            can.id, date=date(2026, 6, 15), close=Decimal("2976"), oi=30215
        )
    )
    session.add(
        make_pl_contract_data_daily(
            can.id, date=date(2026, 6, 16), close=Decimal("3151"), oi=28884
        )
    )
    # CAU26 roll day — dominant OI -> front month for 06-17.
    session.add(
        make_pl_contract_data_daily(
            cau.id, date=date(2026, 6, 17), close=Decimal("3161"), oi=53159
        )
    )
    # CAZ26 same day, lower OI — chained view must skip it for 06-17.
    session.add(
        make_pl_contract_data_daily(
            caz.id, date=date(2026, 6, 17), close=Decimal("3225"), oi=50351
        )
    )

    # Legacy decisions, keyed on the contract that traded each date.
    session.add(
        make_pl_indicator_daily(
            can.id,
            algo.id,
            date=date(2026, 6, 16),
            decision="HEDGE",
            confidence=Decimal("4"),
            direction="BAISSIERE",
            conclusion="cocoa hedge yesterday",
            eco="macro eco yesterday",
        )
    )
    session.add(
        make_pl_indicator_daily(
            cau.id,
            algo.id,
            date=date(2026, 6, 17),
            decision="HEDGE",
            confidence=Decimal("4"),
            direction="BAISSIERE",
            conclusion="cocoa hedge today",
            eco="macro eco today",
        )
    )
    session.flush()


@pytest.mark.integration
def test_get_last_two_dates_spans_roll(sync_db_session: Session, chained_view) -> None:
    """The two most recent sessions come from the chained front-month series,
    even though the active contract only has the roll day."""
    _seed_roll(sync_db_session)
    reader = DBBriefReader(sync_db_session)

    dates = reader._get_last_two_dates()

    assert dates == [date(2026, 6, 17), date(2026, 6, 16)]


@pytest.mark.integration
def test_read_all_survives_roll_with_one_day_active_contract(
    sync_db_session: Session, chained_view
) -> None:
    """The roll day no longer starves the brief: today resolves to the new
    front month (CAU26, not the higher-close CAZ26 back month), and yesterday
    resolves to the now-inactive prior front month (CAN26)."""
    _seed_roll(sync_db_session)
    reader = DBBriefReader(sync_db_session)

    data = reader.read_all()  # previously raised ValueError("found 1")

    # Today = roll day, front month by OI (CAU26 close 3161, not CAZ26 3225).
    assert data.today.technicals["CLOSE"] == "3161"
    assert data.today.indicators["CONCLUSION"] == "HEDGE"
    assert data.today.direction == "BAISSIERE"

    # Yesterday = pre-roll, now-INACTIVE contract — must still resolve.
    assert data.yesterday.technicals["CLOSE"] == "3151"
    assert data.yesterday.indicators["CONCLUSION"] == "HEDGE"
