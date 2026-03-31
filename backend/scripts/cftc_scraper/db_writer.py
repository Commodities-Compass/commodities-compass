"""Database writer for CFTC data → pl_contract_data_daily.com_net_us."""

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


def write_com_net_us(
    session: Session,
    commercial_net: float,
    target_date: date,
    dry_run: bool = False,
) -> None:
    """Update com_net_us on the pl_contract_data_daily row for target_date.

    Queries by (date, contract_id). Raises DbWriterError if no row exists
    for that date (Barchart must have created it).
    """
    contract_id = resolve_active(session)

    if dry_run:
        log.info(
            "[DRY RUN] Would write com_net_us=%s for date=%s",
            commercial_net,
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

    existing.com_net_us = Decimal(str(commercial_net))
    session.flush()
    log.info("Updated com_net_us=%s on row date=%s", commercial_net, existing.date)
