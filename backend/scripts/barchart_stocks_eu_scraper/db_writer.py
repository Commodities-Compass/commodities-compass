"""UPDATE writer for Barchart Stock EU data → pl_contract_data_daily.

This scraper *never inserts* a row. The OHLCV row must already have been
written by ``barchart_scraper`` at 19:00 UTC; this scraper updates the
``stock_eu_bags60kg`` column on the existing row keyed by ``(date,
contract_id)`` where ``contract_id`` is the currently active contract.

Mirrors ``ice_stocks_scraper.db_writer.write_stock_us`` — both EU and US
stock scrapers use the same (date, active_contract_id) targeting so that
during a contract roll, only the active contract's row is updated.

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

from scripts.contract_resolver import resolve_active

logger = logging.getLogger(__name__)


class StockEuRowMissingError(RuntimeError):
    """Raised when pl_contract_data_daily has no row for the target (date, contract)."""


def update_stock_eu(
    session: Session,
    target_date: date,
    value_bags60kg: Decimal,
) -> int:
    """Update pl_contract_data_daily.stock_eu_bags60kg for one (date, active_contract).

    Returns the number of rows updated (always 1 if the row exists).
    Raises StockEuRowMissingError if no row matches — the OHLCV scraper
    must have run first AND the active contract must be set.

    The active contract is resolved from ``ref_contract.is_active=true``
    so that during a roll, only the new active contract's row gets the
    stock value (matching stock_us semantics).
    """
    contract_id = resolve_active(session)

    result = session.execute(
        text(
            "UPDATE pl_contract_data_daily "
            "SET stock_eu_bags60kg = :v "
            "WHERE date = :d AND contract_id = :contract_id"
        ),
        {"v": value_bags60kg, "d": target_date, "contract_id": contract_id},
    )
    rowcount = result.rowcount
    if rowcount == 0:
        raise StockEuRowMissingError(
            f"no row in pl_contract_data_daily for "
            f"date={target_date.isoformat()}, contract_id={contract_id} "
            "— OHLCV scraper must run first"
        )

    session.flush()
    logger.info(
        "Updated %d row (date=%s, contract_id=%s, stock_eu_bags60kg=%s)",
        rowcount,
        target_date,
        contract_id,
        value_bags60kg,
    )
    return rowcount
