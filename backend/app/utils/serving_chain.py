"""Serving chain — which algorithm the dashboard shows, in preference order.

Single source of truth for "what do users see". Before this module the answer
was spread across four hardcoded constants (the date resolver, the YTD series,
the intraday message, the ensemble-only endpoints) and no DB column described
it — which is why "flip is_active to switch algorithms" never worked: that flag
belongs to the compute layer (``app/engine/runner.py`` resolves the legacy
version with it), not to serving.

The chain now lives in ``pl_algorithm_version.serving_rank``:

    NULL = never served · 1 = preferred · 2 = next fallback · …

Switching the served algorithm is therefore an UPDATE on that column — no code
change, no redeploy, effective within the cache TTL — and rolling back is the
reverse UPDATE.

**The rank designates a NAME, not a row.** Within a name, resolution still
picks the newest version that actually carries a ``pl_indicator_daily`` row for
the requested date. That is what lets a go-forward-only version serve recent
dates while its predecessor keeps the historical ones, and it is why at most
one row per name may be ranked (partial unique indexes
``uq_algorithm_serving_rank`` / ``uq_algorithm_serving_name``).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import date as date_cls

from cachetools import TTLCache
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Short TTL: a rank change is a deliberate operator action and must surface
# quickly, but the chain is read on every dashboard request so it cannot be
# uncached. 5 min matches the other resolver caches.
_CACHE_TTL_SECONDS = 300

_cache: TTLCache[str, object] = TTLCache(maxsize=128, ttl=_CACHE_TTL_SECONDS)
_cache_lock = asyncio.Lock()


class NoServingVersionError(ValueError):
    """No version in the serving chain can answer for this date.

    Raised only when the chain is empty or its terminal link does not exist at
    all — never for "this date simply has no data", which resolves to the
    terminal fallback so the endpoints can return an empty payload.
    """


def reset_cache() -> None:
    """Drop the memoised chain and resolutions. For tests and rank flips."""
    _cache.clear()


async def get_serving_chain(db: AsyncSession) -> tuple[str, ...]:
    """Served algorithm names, most-preferred first.

    Empty when nothing is ranked — callers must treat that as a configuration
    error, not as "serve anything".
    """
    key = "serving_chain"
    cached = _cache.get(key)
    if isinstance(cached, tuple):
        return cached

    async with _cache_lock:
        cached = _cache.get(key)
        if isinstance(cached, tuple):
            return cached
        rows = await db.execute(
            text(
                "SELECT name FROM pl_algorithm_version "
                "WHERE serving_rank IS NOT NULL ORDER BY serving_rank"
            )
        )
        chain = tuple(str(r[0]) for r in rows)
        if not chain:
            logger.error(
                "Serving chain is empty — no pl_algorithm_version row carries a "
                "serving_rank. The dashboard cannot resolve an algorithm."
            )
        _cache[key] = chain
        return chain


async def get_version_id_by_name(db: AsyncSession, name: str) -> uuid.UUID | None:
    """Newest version id for ``name``, regardless of whether it has data."""
    key = f"version_id_by_name:{name}"
    cached = _cache.get(key)
    if isinstance(cached, uuid.UUID):
        return cached

    async with _cache_lock:
        cached = _cache.get(key)
        if isinstance(cached, uuid.UUID):
            return cached
        row = (
            await db.execute(
                text(
                    "SELECT id FROM pl_algorithm_version WHERE name = :name "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"name": name},
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        version_id = row if isinstance(row, uuid.UUID) else uuid.UUID(str(row))
        _cache[key] = version_id
        return version_id


async def resolve_serving_version(
    db: AsyncSession,
    target_date: date_cls,
    *,
    contract_id: uuid.UUID | None = None,
) -> tuple[uuid.UUID, str]:
    """Return ``(version_id, name)`` for the algorithm to serve on ``target_date``.

    Walks the chain and returns the first link that actually has a
    ``pl_indicator_daily`` row for the date (and contract, when given). If no
    link has one, returns the **terminal** link's id without requiring a row —
    preserving the long-standing behaviour where a date with no data still
    resolves to an algorithm and the endpoints degrade to an empty payload
    rather than a 500.

    Raises ``NoServingVersionError`` when the chain is empty or its terminal
    link has no ``pl_algorithm_version`` row at all.
    """
    chain = await get_serving_chain(db)
    if not chain:
        raise NoServingVersionError(
            "Serving chain is empty: no pl_algorithm_version row has a serving_rank"
        )

    contract_key = str(contract_id) if contract_id else "any"
    key = f"serving:{target_date.isoformat()}:{contract_key}:{'>'.join(chain)}"
    cached = _cache.get(key)
    if isinstance(cached, tuple):
        return cached  # type: ignore[return-value]

    # One round trip for the whole chain: rank the candidate rows by their
    # position in the chain, then (within a name) newest version first.
    sql = (
        "SELECT av.name, i.algorithm_version_id "
        "FROM pl_indicator_daily i "
        "JOIN pl_algorithm_version av ON av.id = i.algorithm_version_id "
        "WHERE i.date = :d AND av.name = ANY(:names) "
        + ("AND i.contract_id = :c " if contract_id is not None else "")
        + "ORDER BY array_position(:names, av.name), av.created_at DESC LIMIT 1"
    )
    params: dict[str, object] = {"d": target_date, "names": list(chain)}
    if contract_id is not None:
        params["c"] = str(contract_id)
    row = (await db.execute(text(sql), params)).first()

    if row is not None:
        name = str(row[0])
        raw = row[1]
        version_id = raw if isinstance(raw, uuid.UUID) else uuid.UUID(str(raw))
        result = (version_id, name)
        _cache[key] = result
        return result

    # No link carries data for this date — fall through to the terminal link.
    terminal = chain[-1]
    fallback_id = await get_version_id_by_name(db, terminal)
    if fallback_id is None:
        raise NoServingVersionError(
            f"No pl_indicator_daily row for date={target_date} on any of "
            f"{list(chain)}, and the terminal version {terminal!r} does not exist"
        )
    result = (fallback_id, terminal)
    _cache[key] = result
    return result
