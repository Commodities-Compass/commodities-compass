"""Database writer for ICE stocks data → pl_contract_data_daily.stock_us."""

import logging
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.pipeline import PlContractDataDaily
from scripts.contract_resolver import resolve_active

log = logging.getLogger(__name__)


class DbWriterError(Exception):
    pass


def write_stock_us(
    session: Session,
    stock_us_tonnes: int,
    target_date: date,
    dry_run: bool = False,
) -> None:
    """Update stock_us on the pl_contract_data_daily row for target_date.

    Queries by (date, contract_id). Raises DbWriterError if no row exists
    for that date (Barchart must have created it).
    """
    contract_id = resolve_active(session)

    if dry_run:
        log.info(
            "[DRY RUN] Would write stock_us=%d for date=%s",
            stock_us_tonnes,
            target_date,
        )
        return

    existing = session.execute(
        select(PlContractDataDaily).where(
            PlContractDataDaily.date == target_date,
            PlContractDataDaily.contract_id == contract_id,
        )
    ).scalar_one_or_none()

    if existing is None:
        raise DbWriterError(
            f"No row found for date={target_date}, contract_id={contract_id} — "
            "Barchart scraper must run first to create the row"
        )

    existing.stock_us = Decimal(str(stock_us_tonnes))
    session.flush()
    log.info("Updated stock_us=%d on row date=%s", stock_us_tonnes, existing.date)
