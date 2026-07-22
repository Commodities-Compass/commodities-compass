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
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline import (
    PlAlgorithmVersion,
)
from app.models.reference import RefContract
from app.utils.front_month import front_month_for_date_or_none

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

    # Resolve, FOR THIS DATE, the newest ensemble-family version that actually HAS a
    # pl_indicator_daily row. With ensemble v1.1.0 shipped go-forward-only (v1.0.0's
    # historical rows left frozen), this serves v1.1.0 for recent dates and v1.0.0 for
    # historical dates transparently — no history recompute. Picking a single "preferred"
    # version id and testing its row would wrongly drop historical ensemble dates (which
    # only have v1.0.0 rows) to legacy the moment v1.1.0 becomes the newest.
    sql = (
        "SELECT id.algorithm_version_id "
        "FROM pl_indicator_daily id "
        "JOIN pl_algorithm_version av ON av.id = id.algorithm_version_id "
        "WHERE id.date = :d AND av.name = :name "
        + ("AND id.contract_id = :c " if contract_id else "")
        + "ORDER BY av.created_at DESC LIMIT 1"
    )
    params: dict[str, object] = {"d": target_date, "name": preferred_name}
    if contract_id is not None:
        params["c"] = str(contract_id)
    ens_id = (await db.execute(text(sql), params)).scalar_one_or_none()
    if ens_id is not None:
        version_id = (
            uuid.UUID(str(ens_id)) if not isinstance(ens_id, uuid.UUID) else ens_id
        )
        result = (version_id, preferred_name)
        _cache[cache_key] = result
        return result

    # No ensemble row for this date — fall back to legacy.
    fallback_id = await _get_version_id_by_name(db, fallback_name)
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
