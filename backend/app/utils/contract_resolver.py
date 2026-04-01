"""Active contract and algorithm version resolution.

Bridges commodity-centric legacy queries to contract-centric pl_* tables.
Results are cached with a 5-minute TTL since these values change at most
once per contract roll (weeks/months).
"""

import asyncio
import uuid
import logging

from cachetools import TTLCache
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reference import RefContract
from app.models.pipeline import PlAlgorithmVersion

logger = logging.getLogger(__name__)

_cache: TTLCache[str, uuid.UUID | str] = TTLCache(maxsize=8, ttl=300)
_cache_lock = asyncio.Lock()


async def _cached_lookup(
    key: str,
    db: AsyncSession,
    query,  # noqa: ANN001
    error_msg: str,
) -> uuid.UUID | str:
    """Generic cached DB lookup with double-check locking."""
    if key in _cache:
        return _cache[key]
    async with _cache_lock:
        if key in _cache:
            return _cache[key]
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
    """Get the active algorithm version ID from pl_algorithm_version."""
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
