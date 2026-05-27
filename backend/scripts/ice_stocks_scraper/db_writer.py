"""Database writer for ICE Certified Stocks → pl_stock_observation.

Refactored 2026-05-27: writes to the generic ``pl_stock_observation``
table (region='us', source='ice_us_report41') keyed on the actual
``report_date`` extracted from the XLS, rather than overwriting the
session-date row of ``pl_contract_data_daily.stock_us``. See migration
``r2m3n4o5p6q7`` for the schema rationale.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from scripts._shared.stock_observation_writer import (
    StockObservationWriterError,
    upsert_stock_observation,
)

log = logging.getLogger(__name__)

SOURCE_TAG = "ice_us_report41"


class DbWriterError(StockObservationWriterError):
    pass


def write_stock_us(
    session: Session,
    stock_us_tonnes: int,
    report_date: date,
    dry_run: bool = False,
) -> bool:
    """Upsert the ICE US certified stock for one report_date.

    ``stock_us_tonnes`` is the post-conversion value already in tonnes
    (the scraper does ``grand_total_bags × 70 / 1000`` at parse time).
    """
    return upsert_stock_observation(
        session,
        region="us",
        report_date=report_date,
        value_native=Decimal(str(stock_us_tonnes)),
        unit_native="tonnes",
        source=SOURCE_TAG,
        dry_run=dry_run,
    )
