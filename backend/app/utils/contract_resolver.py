"""Active contract and algorithm version resolution.

Bridges commodity-centric legacy queries to contract-centric pl_* tables.
Results are cached with a 5-minute TTL since these values change at most
once per contract roll (weeks/months).

The date-aware resolver `get_algorithm_version_for_date()` enables the
dashboard to serve ensemble decisions for dates where ensemble has a row
(post 2025-12-15) and fall back to legacy for older dates — without
backfilling ensemble historically (avoids look-ahead bias since the
ensemble's 14 specialists were trained with cutoff 2026-04-30).
"""

import asyncio
import logging
import uuid
from datetime import date as date_cls

from cachetools import TTLCache
from sqlalchemy import desc, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline import (
    PlAlgorithmVersion,
    PlContractDataDaily,
    PlIndicatorDaily,
)
from app.models.reference import RefContract

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
    """Resolve a (name)-keyed algorithm_version id, cached 5min.

    Returns None if no row matches.
    """
    key = f"algo_version_by_name:{name}"
    if key in _cache:
        cached = _cache[key]
        return cached if isinstance(cached, uuid.UUID) else None

    async with _cache_lock:
        if key in _cache:
            cached = _cache[key]
            return cached if isinstance(cached, uuid.UUID) else None
        result = await db.execute(
            select(PlAlgorithmVersion.id)
            .where(PlAlgorithmVersion.name == name)
            .order_by(PlAlgorithmVersion.created_at.desc())
            .limit(1)
        )
        value = result.scalar_one_or_none()
        if value is not None:
            version_id = (
                uuid.UUID(str(value)) if not isinstance(value, uuid.UUID) else value
            )
            _cache[key] = version_id
            return version_id
        return None


async def get_algorithm_version_for_date(
    db: AsyncSession,
    target_date: date_cls,
    *,
    contract_id: uuid.UUID | None = None,
    preferred_name: str = ENSEMBLE_VERSION_NAME,
    fallback_name: str = LEGACY_VERSION_NAME,
) -> tuple[uuid.UUID, str]:
    """Resolve which algorithm_version_id has a pl_indicator_daily row for ``target_date``.

    Tries ``preferred_name`` first (e.g., ensemble_v1_softgate_wrapper) — if a
    row exists for that (target_date, version), return it. Otherwise fall back
    to ``fallback_name`` (legacy). Optionally filters on ``contract_id`` to
    handle contract rolls; if not provided, picks any contract.

    Returns ``(version_id, version_name)``. Raises ValueError if neither
    version has a row (frontend should treat as "no data for date").

    Cached 5min per (date, contract_id) pair.

    Rationale: ensemble has only 105 dates (2025-12-15 → 2026-05-21), but the
    dashboard must work for the full historical 2023-2026 range. Rather than
    backfilling ensemble retroactively (look-ahead bias on frozen specialists
    trained with cutoff 2026-04-30), the resolver picks ensemble for recent
    dates and legacy for older dates transparently.
    """
    contract_key = str(contract_id) if contract_id else "any"
    cache_key = f"algo_for_date:{target_date.isoformat()}:{contract_key}:{preferred_name}:{fallback_name}"
    if cache_key in _cache:
        cached = _cache[cache_key]
        if isinstance(cached, tuple):
            return cached  # type: ignore[return-value]

    preferred_id = await _get_version_id_by_name(db, preferred_name)
    fallback_id = await _get_version_id_by_name(db, fallback_name)

    if preferred_id is None and fallback_id is None:
        raise ValueError(
            f"Neither '{preferred_name}' nor '{fallback_name}' exist in pl_algorithm_version"
        )

    # Test preferred first.
    if preferred_id is not None:
        sql = (
            "SELECT 1 FROM pl_indicator_daily "
            "WHERE date = :d AND algorithm_version_id = :v "
            + ("AND contract_id = :c " if contract_id else "")
            + "LIMIT 1"
        )
        params: dict[str, object] = {"d": target_date, "v": str(preferred_id)}
        if contract_id is not None:
            params["c"] = str(contract_id)
        hit = (await db.execute(text(sql), params)).scalar_one_or_none()
        if hit is not None:
            result = (preferred_id, preferred_name)
            _cache[cache_key] = result
            return result

    # Fall back to legacy.
    if fallback_id is not None:
        result = (fallback_id, fallback_name)
        _cache[cache_key] = result
        return result

    raise ValueError(
        f"No pl_indicator_daily row found for date={target_date} "
        f"with either {preferred_name} or {fallback_name}"
    )


async def resolve_contract_for_date(
    db: AsyncSession, target_date: date_cls
) -> uuid.UUID | None:
    """Resolve the best contract_id for a historical date.

    Priority order:
    1. Active contract — if it has a complete pl_indicator_daily row
       (conclusion IS NOT NULL = daily analysis ran for this contract+date)
    2. Any contract with a complete row for that date
    3. Active contract with any row (even without conclusion)
    4. Any contract with data (highest OI = front-month heuristic)

    Returns None if no contract has data for that date at all.
    """
    active_id = await get_active_contract_id(db)
    algo_id = await get_active_algorithm_version_id(db)

    # 1. Active contract with complete data (conclusion exists)
    active_complete = await db.execute(
        select(PlIndicatorDaily.id)
        .where(
            PlIndicatorDaily.contract_id == active_id,
            PlIndicatorDaily.algorithm_version_id == algo_id,
            PlIndicatorDaily.date == target_date,
            PlIndicatorDaily.conclusion.isnot(None),
        )
        .limit(1)
    )
    if active_complete.scalar_one_or_none() is not None:
        return active_id

    # 2. Any contract with complete data for this date
    any_complete = await db.execute(
        select(PlIndicatorDaily.contract_id)
        .where(
            PlIndicatorDaily.date == target_date,
            PlIndicatorDaily.algorithm_version_id == algo_id,
            PlIndicatorDaily.conclusion.isnot(None),
        )
        .limit(1)
    )
    fallback_id = any_complete.scalar_one_or_none()
    if fallback_id is not None:
        logger.debug(
            "Cross-contract fallback (complete) for %s: %s -> %s",
            target_date,
            active_id,
            fallback_id,
        )
        return fallback_id

    # 3. Active contract with any row
    active_any = await db.execute(
        select(PlIndicatorDaily.id)
        .where(
            PlIndicatorDaily.contract_id == active_id,
            PlIndicatorDaily.date == target_date,
        )
        .limit(1)
    )
    if active_any.scalar_one_or_none() is not None:
        return active_id

    # 4. Any contract with market data (highest OI = front-month)
    fallback_market = await db.execute(
        select(PlContractDataDaily.contract_id)
        .where(PlContractDataDaily.date == target_date)
        .order_by(desc(PlContractDataDaily.oi))
        .limit(1)
    )
    fallback_id = fallback_market.scalar_one_or_none()
    if fallback_id is not None:
        logger.debug(
            "Cross-contract fallback (market) for %s: %s -> %s",
            target_date,
            active_id,
            fallback_id,
        )
    return fallback_id
