"""Positioning service — ICE EU COT + CFTC US COT + Stock EU/US.

Sources (all weekly, queried "latest on/before target_date"):
  * ``pl_cot_eu_weekly`` — ICE Europe Disaggregated COT (Friday release for
    Tuesday snapshot). Provides Managed Money + Producer/Merchant nets,
    longs/shorts, and total open interest.
  * ``pl_cot_us_weekly`` — CFTC US Disaggregated COT (same cadence as EU).
    Refactored 2026-05-27 to mirror the EU schema. Replaces the legacy
    ``pl_contract_data_daily.com_net_us`` column.
  * ``pl_stock_observation`` — ICE certified stocks for both regions in a
    single generic table keyed on (region, report_date, contract_market).
    Stores both ``value_native`` (in the source's native unit) and
    ``value_tonnes`` (normalized to tonnes for cross-region comparison +
    gauge rendering).

Output payload always includes ``*_report_date`` / ``*_release_date``
fields so the frontend can display "last published" provenance and avoid
the trompeur-fallback bug where a null value was masked by the gauge
minimum.

The EU/US stock ratio is always in tonnes — both sides converted at the
source, no consumer math required.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date as date_cls
from typing import Any, Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline import PlCotEuWeekly, PlCotUsWeekly, PlStockObservation

logger = logging.getLogger(__name__)


async def get_positioning(
    db: AsyncSession,
    target_date: date_cls,
    *,
    contract_id: Optional[uuid.UUID] = None,  # noqa: ARG001 — kept for callsite stability
) -> dict[str, Any]:
    """Return COT EU + COT US + Stock EU/US for ``target_date``.

    All sources are weekly so the "latest on/before target_date" pattern
    applies uniformly. ``contract_id`` is retained on the signature for
    callsite stability but is no longer needed — none of the four sources
    are keyed on contract_id anymore (cocoa-level positioning data is
    contract-agnostic).
    """
    cot_eu = await _fetch_latest_cot_eu(db, target_date)
    cot_us = await _fetch_latest_cot_us(db, target_date)
    stock_eu = await _fetch_latest_stock(db, target_date, region="eu")
    stock_us = await _fetch_latest_stock(db, target_date, region="us")

    stock_eu_tonnes = _to_float(stock_eu.value_tonnes) if stock_eu else None
    stock_us_tonnes = _to_float(stock_us.value_tonnes) if stock_us else None

    stock_eu_us_ratio: Optional[float] = None
    if (
        stock_eu_tonnes is not None
        and stock_us_tonnes is not None
        and stock_us_tonnes > 0
    ):
        stock_eu_us_ratio = round(stock_eu_tonnes / stock_us_tonnes, 4)

    return {
        "date": target_date.isoformat(),
        # ICE EU COT (managed money / producer-merchant, weekly)
        "cot_managed_money_net": _int_or_none(cot_eu, "m_money_net"),
        "cot_managed_money_long": _int_or_none(cot_eu, "m_money_long"),
        "cot_managed_money_short": _int_or_none(cot_eu, "m_money_short"),
        "cot_producer_merchant_net": _int_or_none(cot_eu, "prod_merc_net"),
        "cot_open_interest": _int_or_none(cot_eu, "open_interest"),
        "cot_report_date": _iso_or_none(cot_eu, "report_date"),
        "cot_release_date": _iso_or_none(cot_eu, "release_date"),
        # CFTC US COT (same shape as ICE EU since 2026-05-27)
        "cot_us_managed_money_net": _int_or_none(cot_us, "m_money_net"),
        "cot_us_managed_money_long": _int_or_none(cot_us, "m_money_long"),
        "cot_us_managed_money_short": _int_or_none(cot_us, "m_money_short"),
        "cot_us_producer_merchant_net": _int_or_none(cot_us, "prod_merc_net"),
        "cot_us_open_interest": _int_or_none(cot_us, "open_interest"),
        "cot_us_report_date": _iso_or_none(cot_us, "report_date"),
        "cot_us_release_date": _iso_or_none(cot_us, "release_date"),
        # Stocks — canonical unit is tonnes, plus native unit for audit
        "stock_eu_tonnes": stock_eu_tonnes,
        "stock_eu_native_value": _to_float(stock_eu.value_native) if stock_eu else None,
        "stock_eu_native_unit": stock_eu.unit_native if stock_eu else None,
        "stock_eu_report_date": _iso_or_none(stock_eu, "report_date"),
        "stock_us_tonnes": stock_us_tonnes,
        "stock_us_report_date": _iso_or_none(stock_us, "report_date"),
        "stock_eu_us_ratio": stock_eu_us_ratio,
    }


async def _fetch_latest_cot_eu(
    db: AsyncSession, target_date: date_cls
) -> Optional[PlCotEuWeekly]:
    return (
        await db.execute(
            select(PlCotEuWeekly)
            .where(
                PlCotEuWeekly.release_date <= target_date,
                PlCotEuWeekly.contract_market == "cocoa",
            )
            .order_by(desc(PlCotEuWeekly.release_date))
            .limit(1)
        )
    ).scalar_one_or_none()


async def _fetch_latest_cot_us(
    db: AsyncSession, target_date: date_cls
) -> Optional[PlCotUsWeekly]:
    return (
        await db.execute(
            select(PlCotUsWeekly)
            .where(
                PlCotUsWeekly.release_date <= target_date,
                PlCotUsWeekly.contract_market == "cocoa",
            )
            .order_by(desc(PlCotUsWeekly.release_date))
            .limit(1)
        )
    ).scalar_one_or_none()


async def _fetch_latest_stock(
    db: AsyncSession, target_date: date_cls, *, region: str
) -> Optional[PlStockObservation]:
    return (
        await db.execute(
            select(PlStockObservation)
            .where(
                PlStockObservation.region == region,
                PlStockObservation.contract_market == "cocoa",
                PlStockObservation.report_date <= target_date,
            )
            .order_by(desc(PlStockObservation.report_date))
            .limit(1)
        )
    ).scalar_one_or_none()


def _to_float(value: Any) -> Optional[float]:
    return float(value) if value is not None else None


def _int_or_none(obj: Any, attr: str) -> Optional[int]:
    if obj is None:
        return None
    value = getattr(obj, attr, None)
    return int(value) if value is not None else None


def _iso_or_none(obj: Any, attr: str) -> Optional[str]:
    if obj is None:
        return None
    value = getattr(obj, attr, None)
    return value.isoformat() if value is not None else None
