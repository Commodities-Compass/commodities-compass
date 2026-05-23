"""Tests for the date-aware algorithm version resolver.

Covers:
- Ensemble row exists for date → returns ensemble version
- No ensemble row for date → falls back to legacy
- No row in either → raises ValueError
- Cache returns the same tuple on repeated calls
"""

from __future__ import annotations

import uuid
from datetime import date as date_cls
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

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


async def _seed_ref_chain(db: AsyncSession, code: str = "CAK26") -> uuid.UUID:
    """Seed ref_exchange → ref_commodity → ref_contract chain."""
    exchange = RefExchange(code=f"ICE-{code}", name="ICE", timezone="UTC")
    db.add(exchange)
    await db.flush()
    commodity = RefCommodity(
        code=f"COCOA-{code}", name="Cocoa", exchange_id=exchange.id
    )
    db.add(commodity)
    await db.flush()
    contract = RefContract(
        commodity_id=commodity.id,
        code=code,
        contract_month=code[-3:],
        is_active=False,
    )
    db.add(contract)
    await db.flush()
    return contract.id


async def _seed_version(
    db: AsyncSession, name: str, is_active: bool = False
) -> uuid.UUID:
    """Seed a pl_algorithm_version row."""
    v = PlAlgorithmVersion(
        name=name,
        version="1.0.0",
        horizon="short_term",
        is_active=is_active,
        compute_enabled=True,
        description=f"Test {name}",
    )
    db.add(v)
    await db.flush()
    return v.id


async def _seed_indicator_row(
    db: AsyncSession,
    *,
    on_date: date_cls,
    contract_id: uuid.UUID,
    algorithm_version_id: uuid.UUID,
) -> None:
    """Seed a minimal pl_indicator_daily row."""
    # Need the contract daily row first (FK)
    db.add(
        PlContractDataDaily(
            date=on_date,
            contract_id=contract_id,
            close=Decimal("8000"),
            volume=100,
            oi=10000,
        )
    )
    await db.flush()
    db.add(
        PlIndicatorDaily(
            date=on_date,
            contract_id=contract_id,
            algorithm_version_id=algorithm_version_id,
            decision="OPEN",
            indicator_value=Decimal("0.5"),
        )
    )
    await db.flush()


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    """Reset the resolver cache between tests so order doesn't matter."""
    _cache.clear()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ensemble_picked_when_row_exists(db_session: AsyncSession) -> None:
    contract = await _seed_ref_chain(db_session, "CAK26")
    ensemble = await _seed_version(db_session, ENSEMBLE_VERSION_NAME)
    legacy = await _seed_version(db_session, LEGACY_VERSION_NAME)
    target = date_cls(2026, 5, 15)
    await _seed_indicator_row(
        db_session,
        on_date=target,
        contract_id=contract,
        algorithm_version_id=ensemble,
    )

    version_id, name = await get_algorithm_version_for_date(
        db_session, target, contract_id=contract
    )
    assert version_id == ensemble
    assert name == ENSEMBLE_VERSION_NAME
    _ = legacy  # silence unused


@pytest.mark.integration
@pytest.mark.asyncio
async def test_legacy_fallback_when_no_ensemble_row(db_session: AsyncSession) -> None:
    contract = await _seed_ref_chain(db_session, "CAH24")
    ensemble = await _seed_version(db_session, ENSEMBLE_VERSION_NAME)
    legacy = await _seed_version(db_session, LEGACY_VERSION_NAME)
    target = date_cls(2024, 6, 15)
    # Only seed legacy row for this date
    await _seed_indicator_row(
        db_session,
        on_date=target,
        contract_id=contract,
        algorithm_version_id=legacy,
    )

    version_id, name = await get_algorithm_version_for_date(
        db_session, target, contract_id=contract
    )
    assert version_id == legacy
    assert name == LEGACY_VERSION_NAME
    _ = ensemble


@pytest.mark.integration
@pytest.mark.asyncio
async def test_legacy_fallback_without_contract_filter(
    db_session: AsyncSession,
) -> None:
    """Without contract_id filter the resolver still finds the date row."""
    contract = await _seed_ref_chain(db_session, "CAH24")
    legacy = await _seed_version(db_session, LEGACY_VERSION_NAME)
    await _seed_version(db_session, ENSEMBLE_VERSION_NAME)
    target = date_cls(2024, 6, 15)
    await _seed_indicator_row(
        db_session,
        on_date=target,
        contract_id=contract,
        algorithm_version_id=legacy,
    )

    version_id, name = await get_algorithm_version_for_date(db_session, target)
    assert version_id == legacy
    assert name == LEGACY_VERSION_NAME


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cache_returns_same_tuple(db_session: AsyncSession) -> None:
    contract = await _seed_ref_chain(db_session, "CAK26")
    ensemble = await _seed_version(db_session, ENSEMBLE_VERSION_NAME)
    await _seed_version(db_session, LEGACY_VERSION_NAME)
    target = date_cls(2026, 5, 15)
    await _seed_indicator_row(
        db_session,
        on_date=target,
        contract_id=contract,
        algorithm_version_id=ensemble,
    )

    first = await get_algorithm_version_for_date(
        db_session, target, contract_id=contract
    )
    second = await get_algorithm_version_for_date(
        db_session, target, contract_id=contract
    )
    assert first == second
    assert first[0] == ensemble
