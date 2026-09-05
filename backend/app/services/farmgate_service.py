"""Official farmgate price service — CCC (CIV) + COCOBOD (Ghana) guaranteed price.

Reads ``pl_official_farmgate_price`` (append-only) and publishes ONE price per
region: the one **in force for the focus season**.

The *focus season* is the most recent season either origin has announced. It is
global, not per-region, and that is the whole point: the day CCC announces
2026/27, Ghana stops printing its 2025/26 price and starts saying "awaiting
announcement" — an origin that has not spoken yet is reported as silent rather
than as unchanged. Inserting the COCOBOD row later fills the card on its own,
with no code change.

Within that season, "in force" is the most recent price effective on or before
the requested date; when the season is announced but has not started yet, the
forthcoming price is published instead (its season label and effective date say
so). Sub-campaigns are not split out: a mid-crop price announced in April simply
becomes the price in force from its effective date, which is what a buyer pays.

This is the *official / guaranteed* price (per-kg in CIV, per-64kg-bag in
Ghana), distinct from the real terrain / differential price (Programme
Fondateur, separate).
"""

from __future__ import annotations

import logging
from datetime import date as date_cls
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline import PlOfficialFarmgatePrice

logger = logging.getLogger(__name__)

FARMGATE_REGIONS = ("civ", "ghana")


async def get_farmgate_prices(
    db: AsyncSession, target_date: date_cls
) -> dict[str, Any]:
    """Return the price in force for the focus season, per region.

    Shape: ``{"date": iso, "season": "2026/27"|None, "civ": {...}|None,
    "ghana": {...}|None}``. A region is ``None`` when it has announced nothing
    for the focus season — the pending state the dashboard renders as
    "awaiting announcement".
    """
    season = await _focus_season(db)
    result: dict[str, Any] = {"date": target_date.isoformat(), "season": season}
    for region in FARMGATE_REGIONS:
        result[region] = (
            await _in_force(db, region, season, target_date)
            if season is not None
            else None
        )
    return result


async def _focus_season(db: AsyncSession) -> Optional[str]:
    """The most recent season announced by any origin ("YYYY/YY" sorts lexically)."""
    return (
        await db.execute(select(func.max(PlOfficialFarmgatePrice.season_label)))
    ).scalar_one_or_none()


async def _in_force(
    db: AsyncSession, region: str, season: str, target_date: date_cls
) -> Optional[dict[str, Any]]:
    """The (region, season) price in force on ``target_date``, or the coming one."""
    base = select(PlOfficialFarmgatePrice).where(
        PlOfficialFarmgatePrice.region == region,
        PlOfficialFarmgatePrice.season_label == season,
    )

    row = (
        await db.execute(
            base.where(PlOfficialFarmgatePrice.effective_date <= target_date)
            .order_by(
                PlOfficialFarmgatePrice.effective_date.desc(),
                PlOfficialFarmgatePrice.announced_date.desc().nullslast(),
            )
            .limit(1)
        )
    ).scalar_one_or_none()

    if row is None:
        # Season announced, not yet started: publish the forthcoming price. The
        # alternative — falling back to last season — would print an expired
        # price under a fresh date, which is worse than printing a future one.
        row = (
            await db.execute(
                base.order_by(
                    PlOfficialFarmgatePrice.effective_date.asc(),
                    PlOfficialFarmgatePrice.announced_date.asc().nullsfirst(),
                ).limit(1)
            )
        ).scalar_one_or_none()

    if row is None:
        return None

    return {
        "region": row.region,
        "campaign_type": row.campaign_type,
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
