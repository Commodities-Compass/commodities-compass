"""Database writer for ICE stocks data → pl_contract_data_daily.stock_us."""

import logging
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
    dry_run: bool = False,
) -> None:
    """Update stock_us on the most recent pl_contract_data_daily row.

    Finds the latest row for the active contract and updates its stock_us field.
    Raises DbWriterError if no row exists (Barchart must run first at 9:00 PM).
    """
    contract_id = resolve_active(session)

    if dry_run:
        log.info("[DRY RUN] Would write stock_us=%d", stock_us_tonnes)
        return

    existing = session.execute(
        select(PlContractDataDaily)
        .where(PlContractDataDaily.contract_id == contract_id)
        .order_by(PlContractDataDaily.date.desc())
        .limit(1)
    ).scalar_one_or_none()

    if existing is None:
        raise DbWriterError(
            "No existing row found for active contract — "
            "Barchart scraper must run first to create the row"
        )

    existing.stock_us = Decimal(str(stock_us_tonnes))
    session.flush()
    log.info("Updated stock_us=%d on row date=%s", stock_us_tonnes, existing.date)
