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

from sqlalchemy import desc, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline import PlExternalIndicator, PlOfficialFarmgatePrice
from app.services.macro_panel_service import EUR_XOF_PARITY

logger = logging.getLogger(__name__)

FARMGATE_REGIONS = ("civ", "ghana")

# --- Market-equivalent bord-champ (London → implied farmgate) ----------------
# What the current London cocoa price WOULD imply for the farmgate, to sit next
# to the official guaranteed price (the gap is the coop signal). The London
# terminal (GBP/t) already EXCLUDES the LID physical premium, so it maps to the
# barème's "CIF sans LID" base directly, and the CIV producer share applies
# straight: equiv = 0.706 × (London_GBP/t × XOF-per-GBP ÷ 1000). Validated on
# the CCC LID-era barèmes (R² ≈ 0.9997).
CIV_PASS_THROUGH = 0.706
# Ghana is ESTIMATED — no COCOBOD barème nor GHS FX in the app. These two tunable
# constants fold London→GHS and the producer share into one factor; the response
# flags it estimated=True. Recalibrate when Ghana barème data lands.
GHANA_GHS_PER_GBP = 20.0
GHANA_PASS_THROUGH = 0.55
GHANA_BAG_KG = 64


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
    result["equivalent"] = await _market_equivalent(
        db,
        target_date,
        civ_official=(result["civ"] or {}).get("price_native"),
        ghana_official=(result["ghana"] or {}).get("price_native"),
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


def _delta_pct(equiv: float, official: Optional[float]) -> Optional[float]:
    """Percent gap of the equivalent vs the official price (None if no official)."""
    if not official or official <= 0:
        return None
    return round((equiv - official) / official * 100, 1)


async def _latest_london_close(
    db: AsyncSession, target_date: date_cls
) -> Optional[float]:
    """Front-month London close (GBP/t) on/before the date — roll-safe chain."""
    value = (
        await db.execute(
            text(
                "SELECT close FROM v_contract_data_chained "
                "WHERE date <= :d AND close IS NOT NULL "
                "ORDER BY date DESC LIMIT 1"
            ),
            {"d": target_date},
        )
    ).scalar_one_or_none()
    return float(value) if value is not None else None


async def _latest_xof_per_gbp(
    db: AsyncSession, target_date: date_cls
) -> Optional[float]:
    """XOF per 1 GBP — fixed EUR/XOF peg through the floating GBP/EUR ECB cross."""
    gbp_per_eur = (
        await db.execute(
            select(PlExternalIndicator.fx_gbpeur)
            .where(
                PlExternalIndicator.date <= target_date,
                PlExternalIndicator.fx_gbpeur.is_not(None),
            )
            .order_by(desc(PlExternalIndicator.date))
            .limit(1)
        )
    ).scalar_one_or_none()
    rate = float(gbp_per_eur) if gbp_per_eur is not None else None
    if rate is None or rate <= 0:
        return None
    return EUR_XOF_PARITY / rate


async def _market_equivalent(
    db: AsyncSession,
    target_date: date_cls,
    *,
    civ_official: Optional[float],
    ghana_official: Optional[float],
) -> Optional[dict[str, Any]]:
    """London-implied farmgate per region, to sit beside the official price.

    Returns None when either input (London close, GBP/EUR cross) is missing —
    the dashboard then shows the official prices alone. CIV is validated on the
    CCC barèmes; Ghana is flagged ``estimated`` (see module constants).
    """
    london = await _latest_london_close(db, target_date)
    xof_per_gbp = await _latest_xof_per_gbp(db, target_date)
    if london is None or xof_per_gbp is None:
        return None

    caf_cfa_kg = london * xof_per_gbp / 1000.0
    equiv_civ = float(round(CIV_PASS_THROUGH * caf_cfa_kg))
    ghs_per_bag = london * GHANA_GHS_PER_GBP * GHANA_BAG_KG / 1000.0
    equiv_ghana = float(round(GHANA_PASS_THROUGH * ghs_per_bag))

    return {
        "london_gbp_per_tonne": round(london, 1),
        "xof_per_gbp": round(xof_per_gbp, 2),
        "civ": {
            "price_native": equiv_civ,
            "currency": "XOF",
            "unit": "per_kg",
            "coefficient": CIV_PASS_THROUGH,
            "estimated": False,
            "delta_pct_vs_official": _delta_pct(equiv_civ, civ_official),
        },
        "ghana": {
            "price_native": equiv_ghana,
            "currency": "GHS",
            "unit": "per_bag_64kg",
            "coefficient": GHANA_PASS_THROUGH,
            "estimated": True,
            "delta_pct_vs_official": _delta_pct(equiv_ghana, ghana_official),
        },
    }
