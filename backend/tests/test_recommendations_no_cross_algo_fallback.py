"""The narrative belongs to the served algorithm — nothing else may fill in.

``get_latest_recommendations`` used to walk a four-step cascade that relaxed
the contract filter and then the ALGORITHM filter. It existed for one era: the
decision came from the ensemble while only the legacy job wrote prose, so the
grid borrowed legacy's narrative to avoid an empty section.

Once a single algorithm owns the pipeline end to end, that borrowing becomes a
liability: rows from retired pipelines stay in the table forever, so the
cascade could surface a narrative from a dead algorithm next to a live
decision — silently, and increasingly stale. These tests make the borrowing
impossible.
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
from app.services.dashboard_service import get_latest_recommendations

_SESSION = date_cls(2026, 8, 17)


async def _seed_contract(db: AsyncSession, code: str) -> uuid.UUID:
    ex = RefExchange(code=f"ICE-{code}", name="ICE", timezone="UTC")
    db.add(ex)
    await db.flush()
    com = RefCommodity(code=f"CC-{code}", name="Cocoa", exchange_id=ex.id)
    db.add(com)
    await db.flush()
    contract = RefContract(
        commodity_id=com.id, code=code, contract_month=code[-3:], is_active=True
    )
    db.add(contract)
    await db.flush()
    db.add(
        PlContractDataDaily(
            date=_SESSION, contract_id=contract.id, close=Decimal("8000")
        )
    )
    await db.flush()
    return contract.id


async def _seed_version(db: AsyncSession, name: str, rank: int | None) -> uuid.UUID:
    row = PlAlgorithmVersion(
        name=name, version="1.0.0", horizon="short_term", serving_rank=rank
    )
    db.add(row)
    await db.flush()
    return row.id


async def _seed_row(
    db: AsyncSession,
    *,
    contract_id: uuid.UUID,
    version_id: uuid.UUID,
    conclusion: str | None,
    language: str = "fr",
) -> None:
    db.add(
        PlIndicatorDaily(
            date=_SESSION,
            contract_id=contract_id,
            algorithm_version_id=version_id,
            language=language,
            decision="OPEN",
            conclusion=conclusion,
        )
    )
    await db.flush()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_served_narrative_is_returned(db_session: AsyncSession) -> None:
    contract = await _seed_contract(db_session, "CAU26")
    served = await _seed_version(db_session, "served", 1)
    await _seed_row(
        db_session,
        contract_id=contract,
        version_id=served,
        conclusion="Ligne une\nLigne deux",
    )

    recommendations, raw, on_date = await get_latest_recommendations(
        db_session, _SESSION, contract_id=contract, algo_id=served
    )

    assert recommendations == ["Ligne une", "Ligne deux"]
    assert raw is not None
    assert on_date == _SESSION


@pytest.mark.integration
@pytest.mark.asyncio
async def test_retired_algorithm_narrative_is_never_borrowed(
    db_session: AsyncSession,
) -> None:
    """The core guarantee: a dead algorithm's prose stays invisible."""
    contract = await _seed_contract(db_session, "CAZ26")
    served = await _seed_version(db_session, "served", 1)
    retired = await _seed_version(db_session, "retired_legacy", None)

    # The served algorithm has a decision but no narrative yet…
    await _seed_row(
        db_session, contract_id=contract, version_id=served, conclusion=None
    )
    # …while the retired one still has a rich narrative sitting in the table.
    await _seed_row(
        db_session,
        contract_id=contract,
        version_id=retired,
        conclusion="Analyse héritée d'un algo retiré",
    )

    recommendations, raw, _ = await get_latest_recommendations(
        db_session, _SESSION, contract_id=contract, algo_id=served
    )

    assert recommendations == []
    assert raw is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_another_contracts_narrative_is_never_borrowed(
    db_session: AsyncSession,
) -> None:
    """The contract filter is not relaxed either — no leak across a roll."""
    front = await _seed_contract(db_session, "CAU27")
    other = await _seed_contract(db_session, "CAZ27")
    served = await _seed_version(db_session, "served", 1)
    await _seed_row(
        db_session,
        contract_id=other,
        version_id=served,
        conclusion="Narration de l'autre contrat",
    )

    recommendations, raw, _ = await get_latest_recommendations(
        db_session, _SESSION, contract_id=front, algo_id=served
    )

    assert recommendations == []
    assert raw is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_language_is_never_relaxed(db_session: AsyncSession) -> None:
    """Serving one language's prose under another's label stays impossible."""
    contract = await _seed_contract(db_session, "CAH28")
    served = await _seed_version(db_session, "served", 1)
    await _seed_row(
        db_session,
        contract_id=contract,
        version_id=served,
        conclusion="English narrative only",
        language="en",
    )

    recommendations, raw, _ = await get_latest_recommendations(
        db_session, _SESSION, contract_id=contract, algo_id=served, language="fr"
    )

    assert recommendations == []
    assert raw is None
