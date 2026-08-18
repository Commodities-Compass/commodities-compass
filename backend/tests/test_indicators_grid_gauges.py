"""/indicators-grid now reads pl_dashboard_gauge, not pl_indicator_daily.

There was no coverage of ``get_indicators_with_ranges`` at all before this
file, which is how the gauges could have been repointed at a new table with a
fully green suite. The behaviours pinned here are the ones that make the
bascule safe:

  * the gauges survive an algorithm change, because they no longer read one;
  * the response SHAPE is unchanged, so no frontend work is needed;
  * a missing gauge row degrades to an empty grid, never a 500.
"""

from __future__ import annotations

import uuid
from datetime import date as date_cls
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline import PlDashboardGauge
from app.models.reference import RefCommodity, RefContract, RefExchange
from app.models.test_range import TestRange
from app.services.dashboard_service import get_indicators_with_ranges

_SESSION = date_cls(2026, 8, 17)

# (test_range.indicator, response key) for the five served gauges.
_EXPECTED = (
    ("RSI", "rsi"),
    ("MACD", "macd"),
    ("%K", "percentK"),
    ("ATR", "atr"),
    ("VOL_OI", "volOi"),
)


async def _seed_contract(db: AsyncSession, code: str) -> uuid.UUID:
    ex = RefExchange(code=f"ICE-{code}", name="ICE", timezone="UTC")
    db.add(ex)
    await db.flush()
    com = RefCommodity(code=f"CC-{code}", name="Cocoa", exchange_id=ex.id)
    db.add(com)
    await db.flush()
    contract = RefContract(
        commodity_id=com.id, code=code, contract_month=code[-3:], is_active=False
    )
    db.add(contract)
    await db.flush()
    return contract.id


async def _seed_ranges(db: AsyncSession) -> None:
    """Three colour zones per gauge — the shape test_range really has."""
    for indicator, _ in _EXPECTED:
        for low, high, area in (
            (Decimal("-3"), Decimal("-1"), "RED"),
            (Decimal("-1"), Decimal("1"), "ORANGE"),
            (Decimal("1"), Decimal("3"), "GREEN"),
        ):
            db.add(
                TestRange(
                    indicator=indicator, range_low=low, range_high=high, area=area
                )
            )
    await db.flush()


async def _seed_gauges(
    db: AsyncSession, contract_id: uuid.UUID, *, on_date: date_cls = _SESSION
) -> None:
    for offset, (indicator, _) in enumerate(_EXPECTED):
        db.add(
            PlDashboardGauge(
                date=on_date,
                contract_id=contract_id,
                indicator_name=indicator,
                raw_value=Decimal("50"),
                score_value=Decimal("55"),
                norm_value=Decimal("0.5") + offset,
            )
        )
    await db.flush()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_grid_is_built_from_gauge_rows(db_session: AsyncSession) -> None:
    contract = await _seed_contract(db_session, "CAU26")
    await _seed_ranges(db_session)
    await _seed_gauges(db_session, contract)

    grid = await get_indicators_with_ranges(db_session, _SESSION, contract_id=contract)

    assert set(grid) == {key for _, key in _EXPECTED}
    # norm_value is what the gauge plots — 0.5, 1.5, 2.5, … as seeded.
    assert grid["rsi"]["value"] == pytest.approx(0.5)
    assert grid["macd"]["value"] == pytest.approx(1.5)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_response_shape_is_unchanged(db_session: AsyncSession) -> None:
    """The frontend contract: {value, min, max, label, ranges[]}."""
    contract = await _seed_contract(db_session, "CAZ26")
    await _seed_ranges(db_session)
    await _seed_gauges(db_session, contract)

    grid = await get_indicators_with_ranges(db_session, _SESSION, contract_id=contract)

    cell = grid["rsi"]
    assert set(cell) == {"value", "min", "max", "label", "ranges"}
    assert cell["label"] == "RSI"
    assert cell["min"] == Decimal("-3")
    assert cell["max"] == Decimal("3")
    assert len(cell["ranges"]) == 3
    assert {r["area"] for r in cell["ranges"]} == {"RED", "ORANGE", "GREEN"}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_gauges_ignore_the_algorithm(db_session: AsyncSession) -> None:
    """The point of the whole exercise: no algorithm can affect a gauge."""
    contract = await _seed_contract(db_session, "CAK27")
    await _seed_ranges(db_session)
    await _seed_gauges(db_session, contract)

    served = await get_indicators_with_ranges(
        db_session, _SESSION, contract_id=contract
    )
    # A bogus algorithm id must change nothing — the parameter is inert.
    with_bogus_algo = await get_indicators_with_ranges(
        db_session, _SESSION, contract_id=contract, algo_id=uuid.uuid4()
    )

    assert served == with_bogus_algo
    assert served, "grid must not be empty"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_macroeco_is_no_longer_served(db_session: AsyncSession) -> None:
    """It is the LLM macro bonus, not a technical gauge, and nothing renders it."""
    contract = await _seed_contract(db_session, "CAH27")
    await _seed_ranges(db_session)
    db_session.add(
        TestRange(
            indicator="MACROECO",
            range_low=Decimal("-6"),
            range_high=Decimal("6"),
            area="ORANGE",
        )
    )
    await _seed_gauges(db_session, contract)

    grid = await get_indicators_with_ranges(db_session, _SESSION, contract_id=contract)

    assert "macroeco" not in grid


@pytest.mark.integration
@pytest.mark.asyncio
async def test_missing_gauges_degrade_to_empty_grid(db_session: AsyncSession) -> None:
    """Before the backfill covers a date — empty payload, never a 500."""
    contract = await _seed_contract(db_session, "CAN27")
    await _seed_ranges(db_session)

    grid = await get_indicators_with_ranges(db_session, _SESSION, contract_id=contract)

    assert grid == {}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_other_contracts_gauges_are_not_served(db_session: AsyncSession) -> None:
    """A roll must not leak the previous front-month's gauges."""
    front = await _seed_contract(db_session, "CAU27")
    other = await _seed_contract(db_session, "CAZ27")
    await _seed_ranges(db_session)
    await _seed_gauges(db_session, other)

    grid = await get_indicators_with_ranges(db_session, _SESSION, contract_id=front)

    assert grid == {}
