"""Official farmgate price service — CCC (CIV) + COCOBOD (Ghana) guaranteed price.

Reads ``pl_official_farmgate_price`` (append-only). For each region, returns the
most recent price effective on or before the requested date. This is the
*official / guaranteed* price (per-kg in CIV, per-64kg-bag in Ghana), distinct
from the real terrain/differential price (Programme Fondateur, separate).
"""

from __future__ import annotations

import logging
from datetime import date as date_cls
from typing import Any, Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline import PlOfficialFarmgatePrice

logger = logging.getLogger(__name__)

FARMGATE_REGIONS = ("civ", "ghana")


async def get_farmgate_prices(
    db: AsyncSession, target_date: date_cls
) -> dict[str, Any]:
    """Return the latest effective farmgate price per region for ``target_date``.

    Shape: ``{"date": iso, "civ": {...} | None, "ghana": {...} | None}``. A
    region is ``None`` when no price has been announced on or before the date.
    """
    result: dict[str, Any] = {"date": target_date.isoformat()}
    for region in FARMGATE_REGIONS:
        result[region] = await _latest_for_region(db, region, target_date)
    return result


async def _latest_for_region(
    db: AsyncSession, region: str, target_date: date_cls
) -> Optional[dict[str, Any]]:
    """Most recent price effective ≤ target_date for one region (newest revision)."""
    row = (
        await db.execute(
            select(PlOfficialFarmgatePrice)
            .where(
                PlOfficialFarmgatePrice.region == region,
                PlOfficialFarmgatePrice.effective_date <= target_date,
            )
            .order_by(
                desc(PlOfficialFarmgatePrice.effective_date),
                desc(PlOfficialFarmgatePrice.announced_date),
            )
            .limit(1)
        )
    ).scalar_one_or_none()

    if row is None:
        return None

    return {
        "region": row.region,
        "season_label": row.season_label,
        "price_native": float(row.price_native),
        "currency": row.currency,
        "unit": row.unit,
        "source": row.source,
        "source_url": row.source_url,
        "effective_date": row.effective_date.isoformat(),
        "announced_date": (
            row.announced_date.isoformat() if row.announced_date else None
        ),
    }
