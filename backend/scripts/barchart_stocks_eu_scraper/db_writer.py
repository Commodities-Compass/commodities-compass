"""UPSERT writer for Barchart Stock EU → pl_stock_observation.

Refactored 2026-05-27: writes to the generic ``pl_stock_observation``
table (region='eu', source='barchart_ic345drw') keyed on the Barchart
"Most Recent Date" (= ICE Europe publication Tuesday). The old design
overwrote the session-date row of ``pl_contract_data_daily.stock_eu_bags60kg``
which masked the weekly cadence (lun-ven all carried the same value).
See migration ``r2m3n4o5p6q7`` for the schema rationale.
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

logger = logging.getLogger(__name__)

SOURCE_TAG = "barchart_ic345drw"


class StockEuRowMissingError(StockObservationWriterError):
    """Kept for backwards compatibility with existing tests, but no longer
    raised — the writer now INSERTs/UPSERTs into pl_stock_observation
    without depending on a pre-existing OHLCV row.
    """


def update_stock_eu(
    session: Session,
    report_date: date,
    value_bags60kg: Decimal,
    dry_run: bool = False,
) -> bool:
    """Upsert one ICE Europe certified stock observation.

    ``report_date`` is the Barchart "Most Recent Date" (the Tuesday ICE
    Europe published). ``value_bags60kg`` is the raw 60kg-bag count.
    Conversion to tonnes happens in the shared writer.
    """
    return upsert_stock_observation(
        session,
        region="eu",
        report_date=report_date,
        value_native=value_bags60kg,
        unit_native="bags_60kg",
        source=SOURCE_TAG,
        dry_run=dry_run,
    )
