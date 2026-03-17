"""Database writer for CFTC data → pl_contract_data_daily.com_net_us."""

import logging
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
    dry_run: bool = False,
) -> None:
    """Update com_net_us on the most recent pl_contract_data_daily row.

    Finds the latest row for the active contract and updates its com_net_us field.
    Raises DbWriterError if no row exists (Barchart must run first at 9:00 PM).
    """
    contract_id = resolve_active(session)

    if dry_run:
        log.info("[DRY RUN] Would write com_net_us=%s", commercial_net)
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

    existing.com_net_us = Decimal(str(commercial_net))
    session.flush()
    log.info("Updated com_net_us=%s on row date=%s", commercial_net, existing.date)
