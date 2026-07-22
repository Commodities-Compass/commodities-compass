"""Guards ensemble v1.1.0 go-forward versioning.

v1.1.0 (C5-full retune) ships WITHOUT recomputing history: v1.0.0's historical rows stay
frozen, v1.1.0 is written only for new sessions. The dashboard resolver must therefore
serve, PER DATE, the newest ensemble-family version that actually HAS a pl_indicator_daily
row — v1.1.0 for recent dates, v1.0.0 for historical dates — never dropping a historical
ensemble date to legacy just because a newer ensemble version now exists.
"""

from __future__ import annotations

import uuid
from datetime import date as date_cls
from datetime import datetime
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
    ex = RefExchange(code=f"ICE-{code}", name="ICE", timezone="UTC")
    db.add(ex)
    await db.flush()
    com = RefCommodity(code=f"COCOA-{code}", name="Cocoa", exchange_id=ex.id)
    db.add(com)
    await db.flush()
    c = RefContract(
        commodity_id=com.id, code=code, contract_month=code[-3:], is_active=False
    )
    db.add(c)
    await db.flush()
    return c.id


async def _seed_ensemble_version(
    db: AsyncSession, version: str, created_at: datetime
) -> uuid.UUID:
    v = PlAlgorithmVersion(
        name=ENSEMBLE_VERSION_NAME,
        version=version,
        horizon="short_term",
        is_active=False,
        compute_enabled=False,
        description=f"ensemble {version}",
        created_at=created_at,
    )
    db.add(v)
    await db.flush()
    return v.id


async def _seed_indicator_row(
    db: AsyncSession,
    *,
    on_date: date_cls,
    contract_id: uuid.UUID,
    version_id: uuid.UUID,
) -> None:
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
            algorithm_version_id=version_id,
            decision="OPEN",
            indicator_value=Decimal("0.5"),
        )
    )
    await db.flush()


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    _cache.clear()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_per_date_serves_v110_forward_v100_historical(
    db_session: AsyncSession,
) -> None:
    contract = await _seed_ref_chain(db_session, "CAU26")
    v100 = await _seed_ensemble_version(db_session, "1.0.0", datetime(2026, 7, 3, 10))
    v110 = await _seed_ensemble_version(db_session, "1.1.0", datetime(2026, 7, 22, 19))
    await _seed_ensemble_version_legacy(db_session)

    historical = date_cls(2026, 3, 11)  # only v1.0.0 has a row
    recent = date_cls(2026, 7, 22)  # only v1.1.0 has a row
    await _seed_indicator_row(
        db_session, on_date=historical, contract_id=contract, version_id=v100
    )
    await _seed_indicator_row(
        db_session, on_date=recent, contract_id=contract, version_id=v110
    )

    hist_id, hist_name = await get_algorithm_version_for_date(
        db_session, historical, contract_id=contract
    )
    assert hist_id == v100 and hist_name == ENSEMBLE_VERSION_NAME  # frozen history
    _cache.clear()
    rec_id, rec_name = await get_algorithm_version_for_date(
        db_session, recent, contract_id=contract
    )
    assert rec_id == v110 and rec_name == ENSEMBLE_VERSION_NAME  # go-forward


@pytest.mark.integration
@pytest.mark.asyncio
async def test_newest_version_wins_when_both_have_a_row(
    db_session: AsyncSession,
) -> None:
    contract = await _seed_ref_chain(db_session, "CAZ26")
    v100 = await _seed_ensemble_version(db_session, "1.0.0", datetime(2026, 7, 3, 10))
    v110 = await _seed_ensemble_version(db_session, "1.1.0", datetime(2026, 7, 22, 19))
    same_date = date_cls(2026, 7, 22)
    # One contract-day row (PK date+contract), then BOTH versions' indicator rows on it →
    # newest (v1.1.0) must win.
    db_session.add(
        PlContractDataDaily(
            date=same_date,
            contract_id=contract,
            close=Decimal("8000"),
            volume=100,
            oi=10000,
        )
    )
    await db_session.flush()
    for vid in (v100, v110):
        db_session.add(
            PlIndicatorDaily(
                date=same_date,
                contract_id=contract,
                algorithm_version_id=vid,
                decision="OPEN",
                indicator_value=Decimal("0.5"),
            )
        )
    await db_session.flush()

    vid, _ = await get_algorithm_version_for_date(
        db_session, same_date, contract_id=contract
    )
    assert vid == v110


async def _seed_ensemble_version_legacy(db: AsyncSession) -> uuid.UUID:
    v = PlAlgorithmVersion(
        name=LEGACY_VERSION_NAME,
        version="1.0.1",
        horizon="short_term",
        is_active=True,
        compute_enabled=True,
        description="legacy",
    )
    db.add(v)
    await db.flush()
    return v.id
