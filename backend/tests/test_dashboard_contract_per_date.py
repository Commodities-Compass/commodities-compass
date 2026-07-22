"""Regression: dashboard endpoints must resolve the front-month contract
PER DATE, not the active one.

The CAN26→CAU26 roll surfaced this: the endpoints did
``contract_id = await get_active_contract_id(db)`` (= CAU26 post-roll) and fed
that to the date-aware algo/position lookups. For a pre-roll June date CAU26
has no rows, so every historical session fell back to Legacy and a null
position (rendered as MONITOR) — "all June sessions show MONITOR / Powered by
Legacy". The fix resolves the contract that was front-month THAT day.
"""

from __future__ import annotations

import uuid
from datetime import date as date_cls
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.endpoints.dashboard import _resolve_contract_for_request
from app.models.pipeline import (
    PlAlgorithmVersion,
    PlContractDataDaily,
    PlIndicatorDaily,
)
from app.models.reference import RefCommodity, RefContract, RefExchange
from app.utils.contract_resolver import (
    ENSEMBLE_VERSION_NAME,
    LEGACY_VERSION_NAME,
    _cache,
    get_algorithm_version_for_date,
)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    _cache.clear()


async def _contract(
    db: AsyncSession,
    code: str,
    *,
    active: bool,
    active_from: date_cls | None = None,
) -> uuid.UUID:
    ex = RefExchange(code=f"ICE-{code}", name="ICE", timezone="UTC")
    db.add(ex)
    await db.flush()
    com = RefCommodity(code=f"CC-{code}", name="Cocoa", exchange_id=ex.id)
    db.add(com)
    await db.flush()
    c = RefContract(
        commodity_id=com.id,
        code=code,
        contract_month=code[-3:],
        is_active=active,
        active_from=active_from,
    )
    db.add(c)
    await db.flush()
    return c.id


async def _version(db: AsyncSession, name: str, *, active: bool) -> uuid.UUID:
    v = PlAlgorithmVersion(
        name=name, version="1.0.0", horizon="short_term", is_active=active
    )
    db.add(v)
    await db.flush()
    return v.id


async def _indicator(db, on_date, contract_id, algo_id) -> None:
    db.add(
        PlIndicatorDaily(
            date=on_date,
            contract_id=contract_id,
            algorithm_version_id=algo_id,
            decision="OPEN",
            conclusion="seeded",  # non-null → resolve_contract_for_date picks it
        )
    )
    await db.flush()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_request_contract_resolves_per_date_across_roll(
    db_session: AsyncSession,
) -> None:
    # Roll calendar: CAN26 front from Apr, CAU26 from mid-Jun (post-target).
    can = await _contract(
        db_session, "CAN26", active=False, active_from=date_cls(2026, 4, 10)
    )
    cau = await _contract(
        db_session, "CAU26", active=True, active_from=date_cls(2026, 6, 17)
    )
    legacy = await _version(db_session, LEGACY_VERSION_NAME, active=True)
    ensemble = await _version(db_session, ENSEMBLE_VERSION_NAME, active=False)

    target = date_cls(2026, 6, 5)  # pre-roll session — only CAN26 has rows
    # one OHLCV row for the FK-ish lookups; CAN26 has both legacy + ensemble rows
    db_session.add(
        PlContractDataDaily(
            date=target, contract_id=can, close=Decimal("2902"), volume=100, oi=30000
        )
    )
    await db_session.flush()
    await _indicator(db_session, target, can, legacy)
    await _indicator(db_session, target, can, ensemble)
    # CAU26 (active) has NO row for this pre-roll date.
    _cache.clear()

    # THE FIX: a dated request resolves to the day's front-month (CAN26), not CAU26.
    assert await _resolve_contract_for_request(db_session, target) == can

    # → so the algo resolves to ENSEMBLE (the row that exists on CAN26), not legacy.
    _, name = await get_algorithm_version_for_date(db_session, target, contract_id=can)
    assert name == ENSEMBLE_VERSION_NAME

    # A 'latest' (no-date) request still uses the active contract.
    assert await _resolve_contract_for_request(db_session, None) == cau

    # Sanity: had we kept using the active contract (CAU26), the algo would have
    # fallen back to legacy — the bug.
    _, active_name = await get_algorithm_version_for_date(
        db_session, target, contract_id=cau
    )
    assert active_name == LEGACY_VERSION_NAME
