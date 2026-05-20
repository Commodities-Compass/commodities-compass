"""UPDATE writer for Barchart Stock EU data → pl_contract_data_daily.

This scraper *never inserts* a row. The OHLCV row must already have been
written by ``barchart_scraper`` at 19:00 UTC; this scraper updates the
``stock_eu_bags60kg`` column on the existing row keyed by ``date``.

Fail-loud per ``.claude/rules/pipeline-error-handling.md`` if the row
doesn't exist — masking that case would create stock-only rows with no
OHLCV, breaking downstream computation.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class StockEuRowMissingError(RuntimeError):
    """Raised when pl_contract_data_daily has no row for the target date."""


def update_stock_eu(
    session: Session,
    target_date: date,
    value_bags60kg: Decimal,
) -> int:
    """Update pl_contract_data_daily.stock_eu_bags60kg for one date.

    Returns the number of rows updated (always 1 if the row exists).
    Raises StockEuRowMissingError if no row matches — the OHLCV scraper
    must have run first.
    """
    result = session.execute(
        text(
            "UPDATE pl_contract_data_daily SET stock_eu_bags60kg = :v WHERE date = :d"
        ),
        {"v": value_bags60kg, "d": target_date},
    )
    rowcount = result.rowcount
    if rowcount == 0:
        raise StockEuRowMissingError(
            f"no row in pl_contract_data_daily for date={target_date.isoformat()} "
            "— OHLCV scraper must run first"
        )

    session.flush()
    logger.info(
        "Updated %d row (date=%s, stock_eu_bags60kg=%s)",
        rowcount,
        target_date,
        value_bags60kg,
    )
    return rowcount
