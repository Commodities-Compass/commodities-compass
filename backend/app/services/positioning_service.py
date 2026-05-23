"""Positioning service — COT EU weekly + Stock EU/US daily.

Sources:
  * ``pl_cot_eu_weekly`` for ICE Europe positioning (Managed Money + Producer/
    Merchant nets, plus longs and shorts). Weekly cadence, lagged ~3 days
    from snapshot Tuesday. We pick the most recent row on/before the target.
  * ``pl_contract_data_daily`` for ``stock_eu_bags60kg``, ``stock_us`` (tonnes),
    and the legacy CFTC US commercial net ``com_net_us``. We pick the row on
    the target date for the resolved contract, falling back to the latest
    available date (covers contract roll edge-cases).

The EU/US stock ratio is computed in tonnes — EU bags are converted via
``bags × 60 / 1000`` (60kg per bag).
"""

from __future__ import annotations

import logging
import uuid
from datetime import date as date_cls
from typing import Any, Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline import PlContractDataDaily, PlCotEuWeekly
from app.utils.contract_resolver import get_active_contract_id

logger = logging.getLogger(__name__)

# Cocoa bag = 60 kg → tonnes (per ICE convention)
EU_BAG_KG = 60.0
KG_PER_TONNE = 1000.0


async def get_positioning(
    db: AsyncSession,
    target_date: date_cls,
    *,
    contract_id: Optional[uuid.UUID] = None,
) -> dict[str, Any]:
    """Return COT EU positioning + Stock EU/US for ``target_date``.

    Stock columns are taken from the (target_date, contract_id) row when it
    exists. If the contract has no row for that date (roll edge), falls back
    to the latest available row for that contract on or before the date.
    """
    if contract_id is None:
        contract_id = await get_active_contract_id(db)

    # COT EU — most recent weekly snapshot on/before target_date
    cot = (
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

    # Stocks — exact-date row first, fall back to latest <= target_date
    stocks = (
        await db.execute(
            select(
                PlContractDataDaily.stock_eu_bags60kg,
                PlContractDataDaily.stock_us,
                PlContractDataDaily.com_net_us,
                PlContractDataDaily.date,
            )
            .where(
                PlContractDataDaily.contract_id == contract_id,
                PlContractDataDaily.date <= target_date,
            )
            .order_by(desc(PlContractDataDaily.date))
            .limit(1)
        )
    ).one_or_none()

    stock_eu = _to_float(stocks.stock_eu_bags60kg) if stocks else None
    stock_us = _to_float(stocks.stock_us) if stocks else None
    com_net_us = _to_float(stocks.com_net_us) if stocks else None

    # Ratio EU/US in tonnes (only when both present and US > 0)
    stock_eu_us_ratio: Optional[float] = None
    if stock_eu is not None and stock_us is not None and stock_us > 0:
        stock_eu_tonnes = stock_eu * EU_BAG_KG / KG_PER_TONNE
        stock_eu_us_ratio = round(stock_eu_tonnes / stock_us, 4)

    return {
        "date": target_date.isoformat(),
        "cot_managed_money_net": int(cot.m_money_net)
        if cot and cot.m_money_net is not None
        else None,
        "cot_managed_money_long": int(cot.m_money_long)
        if cot and cot.m_money_long is not None
        else None,
        "cot_managed_money_short": int(cot.m_money_short)
        if cot and cot.m_money_short is not None
        else None,
        "cot_producer_merchant_net": int(cot.prod_merc_net)
        if cot and cot.prod_merc_net is not None
        else None,
        "cot_open_interest": int(cot.open_interest)
        if cot and cot.open_interest is not None
        else None,
        "cot_report_date": cot.report_date.isoformat() if cot else None,
        "cot_release_date": cot.release_date.isoformat() if cot else None,
        "stock_eu_bags60kg": stock_eu,
        "stock_us": stock_us,
        "stock_eu_us_ratio": stock_eu_us_ratio,
        "com_net_us": com_net_us,
    }


def _to_float(v: Any) -> Optional[float]:
    return float(v) if v is not None else None
