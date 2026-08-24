"""YTD invalidation credit — a warned loss is scored as a hit (+1).

When an intraday invalidation alert (cc-intraday-monitor) fired against the
day's signal, the user was warned in time to act, so that losing day is scored
as a MONITOR-style +1 instead of a directional miss. Only LOSING days that were
actually alerted (delivered) are credited, and the alert challenging
``decision[D]`` fires on session D+1 — the off-by-one these tests pin.

Reuses the saw-tooth from test_eval_horizon_per_algorithm: OPEN every session on
a +20/-10 tooth, scored at the regime J+1 horizon, loses every other day.
"""

from __future__ import annotations

import uuid
from datetime import date as date_cls
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AudAlertEvent
from app.models.pipeline import (
    PlAlgorithmVersion,
    PlContractDataDaily,
    PlIndicatorDaily,
)
from app.models.reference import RefAlertRule, RefCommodity, RefContract, RefExchange
from app.services.dashboard_service import calculate_ytd_performance
from app.utils.contract_resolver import _cache
from app.utils.serving_chain import reset_cache as reset_serving_cache

_SESSIONS = [date_cls(2026, 1, d) for d in (5, 6, 7, 8, 9, 12, 13, 14, 15, 16, 19, 20)]
_CLOSES = [100, 120, 110, 130, 120, 140, 130, 150, 140, 160, 150, 170]

# OPEN loses at J+1 on the down-legs: decision days at indices 1,3,5,7,9
# (sessions Jan 6/8/12/14/16). The alert challenging each fires the NEXT
# session — indices 2,4,6,8,10 (Jan 7/9/13/15/19).
_LOSS_ALERT_SESSIONS = [_SESSIONS[i] for i in (2, 4, 6, 8, 10)]
_RAW_YTD = 61.62  # pinned in test_eval_horizon_per_algorithm
_ALL_CREDITED_YTD = 12.5 / 11 * 100  # 6 wins ×1.25 + 5 credits ×1.0, /11 days


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    _cache.clear()
    reset_serving_cache()


async def _seed(db: AsyncSession) -> uuid.UUID:
    ex = RefExchange(code="ICE-CR", name="ICE", timezone="UTC")
    db.add(ex)
    await db.flush()
    com = RefCommodity(code="CC-CR", name="Cocoa", exchange_id=ex.id)
    db.add(com)
    await db.flush()
    contract = RefContract(
        commodity_id=com.id,
        code="CAU26",
        contract_month="U26",
        is_active=True,
        active_from=_SESSIONS[0],
    )
    db.add(contract)
    await db.flush()
    algo = PlAlgorithmVersion(
        name="regime",
        version="1.0.0",
        horizon="short_term",
        is_active=False,
        serving_rank=1,
    )
    db.add(algo)
    await db.flush()
    for session, close in zip(_SESSIONS, _CLOSES):
        db.add(
            PlContractDataDaily(
                date=session,
                contract_id=contract.id,
                close=Decimal(str(close)),
                volume=1000,
                oi=1000,
            )
        )
        db.add(
            PlIndicatorDaily(
                date=session,
                contract_id=contract.id,
                algorithm_version_id=algo.id,
                decision="OPEN",
                conclusion="seeded",
            )
        )
    await db.flush()
    _cache.clear()
    reset_serving_cache()
    return contract.id


async def _add_alert(
    db: AsyncSession, contract_id: uuid.UUID, session: date_cls, *, status: str = "sent"
) -> None:
    rule = RefAlertRule(
        rule_key=f"r-{session}",
        metric_column="close",
        level_column="s1",
        level_label="SUPPORT 1",
        comparator="below",
        direction="bearish",
    )
    db.add(rule)
    await db.flush()
    db.add(
        AudAlertEvent(
            rule_id=rule.id,
            contract_id=contract_id,
            session_date=session,
            level_value=Decimal("100"),
            observed_price=Decimal("99"),
            observed_at=datetime(
                session.year, session.month, session.day, 10, tzinfo=timezone.utc
            ),
            channel="telegram",
            delivery_status=status,
        )
    )
    await db.flush()


async def _ytd(db: AsyncSession, *, credit: bool) -> float:
    return await calculate_ytd_performance(
        db,
        reference_date=_SESSIONS[-1],
        algorithm_name="regime",
        apply_invalidation_credit=credit,
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_no_alerts_credit_equals_raw(db_session: AsyncSession) -> None:
    """With no alert events, the credited path returns the raw YTD."""
    await _seed(db_session)
    assert await _ytd(db_session, credit=True) == pytest.approx(_RAW_YTD, abs=0.01)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_all_alerted_losses_flip_to_hits(db_session: AsyncSession) -> None:
    contract = await _seed(db_session)
    for session in _LOSS_ALERT_SESSIONS:
        await _add_alert(db_session, contract, session)

    credited = await _ytd(db_session, credit=True)
    raw = await _ytd(db_session, credit=False)

    assert raw == pytest.approx(_RAW_YTD, abs=0.01)
    assert credited == pytest.approx(_ALL_CREDITED_YTD, abs=0.01)  # 113.64
    assert credited > raw


@pytest.mark.integration
@pytest.mark.asyncio
async def test_credit_flag_off_gives_raw(db_session: AsyncSession) -> None:
    contract = await _seed(db_session)
    for session in _LOSS_ALERT_SESSIONS:
        await _add_alert(db_session, contract, session)
    assert await _ytd(db_session, credit=False) == pytest.approx(_RAW_YTD, abs=0.01)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_only_delivered_alerts_credit(db_session: AsyncSession) -> None:
    """A 'failed' alert (user never warned) does not credit."""
    contract = await _seed(db_session)
    await _add_alert(db_session, contract, _LOSS_ALERT_SESSIONS[0], status="failed")
    assert await _ytd(db_session, credit=True) == pytest.approx(_RAW_YTD, abs=0.01)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_wins_are_not_credited(db_session: AsyncSession) -> None:
    """An alert on a WIN day's next session must not change the score."""
    contract = await _seed(db_session)
    # Win decision days are indices 0,2,4,6,8,10 → their D+1 are 1,3,5,7,9.
    await _add_alert(db_session, contract, _SESSIONS[1])  # D+1 of the winning i=0
    assert await _ytd(db_session, credit=True) == pytest.approx(_RAW_YTD, abs=0.01)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_off_by_one_alert_on_D_not_credited(db_session: AsyncSession) -> None:
    """The credit keys on the NEXT session (D+1), not the decision day D itself."""
    contract = await _seed(db_session)
    # Losing decision day i=1 is _SESSIONS[1]; the WRONG (same-day) key.
    await _add_alert(db_session, contract, _SESSIONS[1])
    credited = await _ytd(db_session, credit=True)
    # Alert on D (not D+1) must NOT credit that loss → stays raw.
    assert credited == pytest.approx(_RAW_YTD, abs=0.01)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_partial_credit_between_raw_and_full(db_session: AsyncSession) -> None:
    contract = await _seed(db_session)
    for session in _LOSS_ALERT_SESSIONS[:2]:  # credit 2 of 5 losses
        await _add_alert(db_session, contract, session)
    credited = await _ytd(db_session, credit=True)
    assert _RAW_YTD < credited < _ALL_CREDITED_YTD
