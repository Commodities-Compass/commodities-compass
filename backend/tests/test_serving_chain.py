"""Tests for the serving chain (pl_algorithm_version.serving_rank).

The chain replaces four hardcoded algorithm-name constants. These tests pin the
behaviours that must survive that move — especially the two subtle ones the old
resolver relied on:

  * within a name, the NEWEST version carrying a row wins (go-forward-only
    versions serve recent dates, predecessors keep the historical ones);
  * a date with NO data anywhere still resolves — to the terminal link —
    instead of raising, so endpoints degrade to an empty payload not a 500.
"""

from __future__ import annotations

import uuid
from datetime import date as date_cls
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline import (
    PlAlgorithmVersion,
    PlContractDataDaily,
    PlIndicatorDaily,
)
from app.models.reference import RefCommodity, RefContract, RefExchange
from app.utils.serving_chain import (
    NoServingVersionError,
    get_serving_chain,
    reset_cache,
    resolve_serving_version,
)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    reset_cache()


async def _seed_contract(db: AsyncSession, code: str) -> uuid.UUID:
    exchange = RefExchange(code=f"ICE-{code}", name="ICE", timezone="UTC")
    db.add(exchange)
    await db.flush()
    commodity = RefCommodity(
        code=f"COCOA-{code}", name="Cocoa", exchange_id=exchange.id
    )
    db.add(commodity)
    await db.flush()
    contract = RefContract(
        commodity_id=commodity.id, code=code, contract_month=code[-3:], is_active=False
    )
    db.add(contract)
    await db.flush()
    return contract.id


async def _seed_version(
    db: AsyncSession,
    name: str,
    *,
    version: str = "1.0.0",
    serving_rank: int | None = None,
    kind: str = "power_formula",
    created_at: datetime | None = None,
) -> uuid.UUID:
    row = PlAlgorithmVersion(
        name=name,
        version=version,
        horizon="short_term",
        is_active=False,
        compute_enabled=False,
        algorithm_kind=kind,
        serving_rank=serving_rank,
        description=f"test {name} {version}",
    )
    if created_at is not None:
        row.created_at = created_at
    db.add(row)
    await db.flush()
    return row.id


async def _seed_indicator(
    db: AsyncSession,
    *,
    on_date: date_cls,
    contract_id: uuid.UUID,
    version_id: uuid.UUID,
    seed_ohlcv: bool = True,
) -> None:
    if seed_ohlcv:
        db.add(
            PlContractDataDaily(
                date=on_date, contract_id=contract_id, close=Decimal("8000")
            )
        )
        await db.flush()
    db.add(
        PlIndicatorDaily(
            date=on_date,
            contract_id=contract_id,
            algorithm_version_id=version_id,
            decision="OPEN",
        )
    )
    await db.flush()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_chain_is_ordered_by_rank_and_excludes_unranked(
    db_session: AsyncSession,
) -> None:
    await _seed_version(db_session, "alpha", serving_rank=2)
    await _seed_version(db_session, "beta", serving_rank=1)
    await _seed_version(db_session, "unranked", serving_rank=None)

    assert await get_serving_chain(db_session) == ("beta", "alpha")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_preferred_link_wins_when_it_has_a_row(db_session: AsyncSession) -> None:
    contract = await _seed_contract(db_session, "CAK26")
    preferred = await _seed_version(db_session, "preferred", serving_rank=1)
    fallback = await _seed_version(db_session, "fallback", serving_rank=2)
    target = date_cls(2026, 5, 15)
    await _seed_indicator(
        db_session, on_date=target, contract_id=contract, version_id=preferred
    )
    await _seed_indicator(
        db_session,
        on_date=target,
        contract_id=contract,
        version_id=fallback,
        seed_ohlcv=False,
    )

    version_id, name = await resolve_serving_version(
        db_session, target, contract_id=contract
    )
    assert (version_id, name) == (preferred, "preferred")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_falls_through_when_preferred_has_no_row(
    db_session: AsyncSession,
) -> None:
    contract = await _seed_contract(db_session, "CAH24")
    await _seed_version(db_session, "preferred", serving_rank=1)
    fallback = await _seed_version(db_session, "fallback", serving_rank=2)
    target = date_cls(2024, 6, 15)
    await _seed_indicator(
        db_session, on_date=target, contract_id=contract, version_id=fallback
    )

    version_id, name = await resolve_serving_version(
        db_session, target, contract_id=contract
    )
    assert (version_id, name) == (fallback, "fallback")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_terminal_fallback_when_no_link_has_data(
    db_session: AsyncSession,
) -> None:
    """A date with no data must still resolve — endpoints return empty, not 500."""
    contract = await _seed_contract(db_session, "CAN25")
    await _seed_version(db_session, "preferred", serving_rank=1)
    terminal = await _seed_version(db_session, "terminal", serving_rank=2)

    version_id, name = await resolve_serving_version(
        db_session, date_cls(2025, 1, 2), contract_id=contract
    )
    assert (version_id, name) == (terminal, "terminal")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_newest_version_of_a_name_wins(db_session: AsyncSession) -> None:
    """Go-forward-only versioning: the rank designates the NAME, not the row."""
    contract = await _seed_contract(db_session, "CAU26")
    old = await _seed_version(
        db_session,
        "algo",
        version="1.0.0",
        serving_rank=1,
        created_at=datetime(2026, 1, 1),
    )
    new = await _seed_version(
        db_session, "algo", version="1.1.0", created_at=datetime(2026, 6, 1)
    )
    target = date_cls(2026, 7, 1)
    # Both versions carry a row for this date; the newer one must win.
    await _seed_indicator(
        db_session, on_date=target, contract_id=contract, version_id=old
    )
    await _seed_indicator(
        db_session,
        on_date=target,
        contract_id=contract,
        version_id=new,
        seed_ohlcv=False,
    )

    version_id, name = await resolve_serving_version(
        db_session, target, contract_id=contract
    )
    assert (version_id, name) == (new, "algo")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_unranked_version_is_never_served(db_session: AsyncSession) -> None:
    """A shadow algorithm writing rows must not leak into the dashboard."""
    contract = await _seed_contract(db_session, "CAZ26")
    served = await _seed_version(db_session, "served", serving_rank=1)
    shadow = await _seed_version(db_session, "shadow", serving_rank=None)
    target = date_cls(2026, 8, 3)
    await _seed_indicator(
        db_session, on_date=target, contract_id=contract, version_id=shadow
    )

    version_id, name = await resolve_serving_version(
        db_session, target, contract_id=contract
    )
    # Falls back to the terminal link, never to the unranked shadow row.
    assert (version_id, name) == (served, "served")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_empty_chain_raises(db_session: AsyncSession) -> None:
    await _seed_version(db_session, "nothing_ranked", serving_rank=None)
    with pytest.raises(NoServingVersionError):
        await resolve_serving_version(db_session, date_cls(2026, 5, 1))


@pytest.mark.integration
@pytest.mark.asyncio
async def test_contract_filter_is_honoured(db_session: AsyncSession) -> None:
    front = await _seed_contract(db_session, "CAU26")
    other = await _seed_contract(db_session, "CAZ26")
    preferred = await _seed_version(db_session, "preferred", serving_rank=1)
    terminal = await _seed_version(db_session, "terminal", serving_rank=2)
    target = date_cls(2026, 7, 15)
    # The preferred row exists, but on the OTHER contract.
    await _seed_indicator(
        db_session, on_date=target, contract_id=other, version_id=preferred
    )

    version_id, name = await resolve_serving_version(
        db_session, target, contract_id=front
    )
    assert (version_id, name) == (terminal, "terminal")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_rank_flip_changes_what_is_served_after_cache_reset(
    db_session: AsyncSession,
) -> None:
    """The bascule itself: an UPDATE on serving_rank, no code change."""
    contract = await _seed_contract(db_session, "CAK27")
    incumbent = await _seed_version(db_session, "incumbent", serving_rank=1)
    challenger = await _seed_version(db_session, "challenger", serving_rank=2)
    target = date_cls(2027, 3, 1)
    await _seed_indicator(
        db_session, on_date=target, contract_id=contract, version_id=incumbent
    )
    await _seed_indicator(
        db_session,
        on_date=target,
        contract_id=contract,
        version_id=challenger,
        seed_ohlcv=False,
    )

    _, name = await resolve_serving_version(db_session, target, contract_id=contract)
    assert name == "incumbent"

    # Flip, in the ONLY collision-free order — this is the sequence the bascule
    # migration must follow, and the partial unique index enforces it:
    #   1. vacate the rank being taken   2. assign it   3. re-rank the incumbent
    # Each step needs its own flush; batching them lets Postgres apply the
    # UPDATEs in an order that transiently duplicates a rank.
    incumbent_row = await db_session.get(PlAlgorithmVersion, incumbent)
    challenger_row = await db_session.get(PlAlgorithmVersion, challenger)
    assert incumbent_row is not None and challenger_row is not None
    incumbent_row.serving_rank = None
    await db_session.flush()
    challenger_row.serving_rank = 1
    await db_session.flush()
    incumbent_row.serving_rank = 2
    await db_session.flush()
    reset_cache()

    _, name = await resolve_serving_version(db_session, target, contract_id=contract)
    assert name == "challenger"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_two_versions_cannot_share_a_rank(db_session: AsyncSession) -> None:
    await _seed_version(db_session, "first", serving_rank=1)
    with pytest.raises(IntegrityError):
        await _seed_version(db_session, "second", serving_rank=1)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_two_versions_of_a_name_cannot_both_be_ranked(
    db_session: AsyncSession,
) -> None:
    """The rank designates the name — ranking two of its versions is ambiguous."""
    await _seed_version(db_session, "algo", version="1.0.0", serving_rank=1)
    with pytest.raises(IntegrityError):
        await _seed_version(db_session, "algo", version="1.1.0", serving_rank=2)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_chain_is_cached_until_reset(db_session: AsyncSession) -> None:
    await _seed_version(db_session, "only", serving_rank=1)
    assert await get_serving_chain(db_session) == ("only",)

    await _seed_version(db_session, "added_later", serving_rank=2)
    assert await get_serving_chain(db_session) == ("only",)  # memoised

    reset_cache()
    assert await get_serving_chain(db_session) == ("only", "added_later")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_timedelta_import_is_used_for_created_at_ordering(
    db_session: AsyncSession,
) -> None:
    """Newest-wins must use created_at, not insertion order."""
    contract = await _seed_contract(db_session, "CAH27")
    base = datetime(2026, 1, 1)
    # Insert the NEWER row first so insertion order disagrees with created_at.
    newer = await _seed_version(
        db_session, "algo", version="2.0.0", created_at=base + timedelta(days=100)
    )
    older = await _seed_version(
        db_session, "algo", version="1.0.0", serving_rank=1, created_at=base
    )
    target = date_cls(2027, 1, 5)
    await _seed_indicator(
        db_session, on_date=target, contract_id=contract, version_id=older
    )
    await _seed_indicator(
        db_session,
        on_date=target,
        contract_id=contract,
        version_id=newer,
        seed_ohlcv=False,
    )

    version_id, _ = await resolve_serving_version(
        db_session, target, contract_id=contract
    )
    assert version_id == newer
