"""Active contract and algorithm version resolution.

Bridges commodity-centric legacy queries to contract-centric pl_* tables.
Results are cached with a 5-minute TTL since these values change at most
once per contract roll (weeks/months).

The date-aware resolver `get_algorithm_version_for_date()` lets the dashboard
serve the preferred algorithm on dates where it has a row and fall back to the
next one for older dates — without backfilling history (which would introduce
look-ahead bias, the models being trained past those dates).

Which algorithm is preferred is NOT decided here any more: it lives in
`pl_algorithm_version.serving_rank` and is read by `app.utils.serving_chain`.
This module keeps the contract-side resolution and delegates the algorithm side.
"""

import asyncio
import logging
import uuid
from datetime import date as date_cls

from cachetools import TTLCache
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline import (
    PlAlgorithmVersion,
)
from app.models.reference import RefContract
from app.utils.front_month import front_month_for_date_or_none
from app.utils.serving_chain import get_version_id_by_name, resolve_serving_version

logger = logging.getLogger(__name__)

_cache: TTLCache[str, uuid.UUID | str | tuple[uuid.UUID, str]] = TTLCache(
    maxsize=64, ttl=300
)
_cache_lock = asyncio.Lock()

# Algorithm version names used by the date-aware resolver.
ENSEMBLE_VERSION_NAME = "ensemble_v1_softgate_wrapper"
LEGACY_VERSION_NAME = "legacy"


async def _cached_lookup(
    key: str,
    db: AsyncSession,
    query,  # noqa: ANN001
    error_msg: str,
) -> uuid.UUID | str:
    """Generic cached DB lookup with double-check locking.

    Only used for the simple UUID/str lookups (get_active_*). The
    date-aware resolver manages its own cache slots with tuple values.
    """
    if key in _cache:
        cached = _cache[key]
        if isinstance(cached, (uuid.UUID, str)):
            return cached
    async with _cache_lock:
        if key in _cache:
            cached = _cache[key]
            if isinstance(cached, (uuid.UUID, str)):
                return cached
        result = await db.execute(query)
        value = result.scalar_one_or_none()
        if value is None:
            raise ValueError(error_msg)
        _cache[key] = value
        return value


async def get_active_contract_id(db: AsyncSession) -> uuid.UUID:
    """Get the active contract ID from ref_contract."""
    query = select(RefContract.id).where(RefContract.is_active.is_(True)).limit(1)
    result = await _cached_lookup(
        "active_contract_id", db, query, "No active contract found in ref_contract"
    )
    return uuid.UUID(str(result)) if not isinstance(result, uuid.UUID) else result


async def get_active_contract_code(db: AsyncSession) -> str:
    """Get the active contract code (e.g., 'CAK26') from ref_contract."""
    query = select(RefContract.code).where(RefContract.is_active.is_(True)).limit(1)
    result = await _cached_lookup(
        "active_contract_code", db, query, "No active contract found in ref_contract"
    )
    return str(result)


async def get_contract_code_by_id(
    db: AsyncSession, contract_id: uuid.UUID
) -> str | None:
    """Get a contract code (e.g. 'CAU26') from its id.

    Unlike ``get_active_contract_code``, this resolves the code for an
    *arbitrary* contract — the dashboard needs the front-month of the requested
    date, which across a roll is not the active one.

    Returns ``None`` when the id has no row instead of raising: the code is
    display-only provenance (the Section II socle), so a miss must degrade the
    caption, never the whole indicators response. The caller logs the miss.
    """
    key = f"contract_code_by_id:{contract_id}"
    cached = _cache.get(key)
    if isinstance(cached, str):
        return cached

    async with _cache_lock:
        cached = _cache.get(key)
        if isinstance(cached, str):
            return cached
        result = await db.execute(
            select(RefContract.code).where(RefContract.id == contract_id).limit(1)
        )
        value = result.scalar_one_or_none()
        if value is None:
            return None
        code = str(value)
        _cache[key] = code
        return code


async def get_active_algorithm_version_id(db: AsyncSession) -> uuid.UUID:
    """Get the active algorithm version ID from pl_algorithm_version.

    Kept for the few non-date-aware callsites (e.g., backfill scripts).
    Production dashboard endpoints should prefer
    ``get_algorithm_version_for_date()`` instead.
    """
    query = (
        select(PlAlgorithmVersion.id)
        .where(PlAlgorithmVersion.is_active.is_(True))
        .limit(1)
    )
    result = await _cached_lookup(
        "active_algo_version_id",
        db,
        query,
        "No active algorithm version found in pl_algorithm_version",
    )
    return uuid.UUID(str(result)) if not isinstance(result, uuid.UUID) else result


async def _get_version_id_by_name(db: AsyncSession, name: str) -> uuid.UUID | None:
    """Newest algorithm_version id for ``name``, or None.

    Delegates to the serving-chain module so there is a single cache for this
    lookup — two independent TTL caches over the same row would drift on a
    version flip. Kept under this name for the existing importers.
    """
    return await get_version_id_by_name(db, name)


async def get_algorithm_version_for_date(
    db: AsyncSession,
    target_date: date_cls,
    *,
    contract_id: uuid.UUID | None = None,
) -> tuple[uuid.UUID, str]:
    """Resolve which algorithm version the dashboard serves on ``target_date``.

    Thin wrapper over the serving chain
    (``app.utils.serving_chain.resolve_serving_version``). The preference order
    used to be hardcoded here as ``preferred_name``/``fallback_name``; it now
    lives in ``pl_algorithm_version.serving_rank``, so switching algorithms is
    an UPDATE rather than a code change.

    Behaviour is unchanged: the first ranked name that has a
    ``pl_indicator_daily`` row for the date wins (newest version within that
    name), and a date with no data at all still resolves to the terminal link
    so endpoints return an empty payload rather than a 500.

    Raises ``NoServingVersionError`` (a ``ValueError``) when the chain is empty
    or its terminal link does not exist — callers that already catch
    ``ValueError`` keep working.
    """
    return await resolve_serving_version(db, target_date, contract_id=contract_id)


async def resolve_contract_for_date(
    db: AsyncSession, target_date: date_cls
) -> uuid.UUID | None:
    """Resolve the front-month contract for a date from the canonical roll calendar.

    Thin wrapper over ``front_month_for_date_or_none`` — the front-month is the
    contract with the greatest ``ref_contract.active_from`` <= ``target_date``.

    Replaces the former 4-tier completeness cascade (active-complete → any-complete
    → active-any → highest-OI), which used liquidity and decision-presence as
    proxies for the front-month and was a split-brain source: on a roll boundary it
    could disagree with compute / the chained VIEW. The calendar is the single
    source of truth, so all consumers now agree by construction.

    Returns None for a date before the calendar starts (pre-seed history).
    """
    return await front_month_for_date_or_none(db, target_date)
