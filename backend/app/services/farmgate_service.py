"""Official farmgate price service — CCC (CIV) + COCOBOD (Ghana) guaranteed price.

Reads ``pl_official_farmgate_price`` (append-only). For each region AND each
sub-campaign (principale / intermediaire), returns the most recent price
effective on or before the requested date. This is the *official / guaranteed*
price (per-kg in CIV, per-64kg-bag in Ghana), distinct from the real terrain /
differential price (Programme Fondateur, separate).
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
CAMPAIGN_TYPES = ("principale", "intermediaire")


async def get_farmgate_prices(
    db: AsyncSession, target_date: date_cls
) -> dict[str, Any]:
    """Return the latest effective farmgate price per region AND sub-campaign.

    Shape: ``{"date": iso, "civ": {"principale": {...}|None, "intermediaire":
    {...}|None}, "ghana": {...}}``. A slot is ``None`` when nothing has been
    announced for that region/campaign on or before the date.
    """
    result: dict[str, Any] = {"date": target_date.isoformat()}
    for region in FARMGATE_REGIONS:
        result[region] = {
            campaign: await _latest_for(db, region, campaign, target_date)
            for campaign in CAMPAIGN_TYPES
        }
    return result


async def _latest_for(
    db: AsyncSession, region: str, campaign_type: str, target_date: date_cls
) -> Optional[dict[str, Any]]:
    """Most recent price effective ≤ target_date for one (region, campaign)."""
    row = (
        await db.execute(
            select(PlOfficialFarmgatePrice)
            .where(
                PlOfficialFarmgatePrice.region == region,
                PlOfficialFarmgatePrice.campaign_type == campaign_type,
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
