"""Database reader for press review — reads CLOSE from pl_contract_data_daily."""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.pipeline import PlContractDataDaily
from app.models.reference import RefContract

log = logging.getLogger(__name__)


def read_latest_close(session: Session) -> tuple[str, str]:
    """Read the latest CLOSE price and date from pl_contract_data_daily.

    Returns:
        Tuple of (close_price_str, date_str in MM/DD/YYYY format)
        matching the interface of the old SheetsReader.read_latest_close().

    Raises:
        RuntimeError: If no data found or no active contract.
    """
    # Resolve active contract
    active = session.execute(
        select(RefContract.id).where(RefContract.is_active.is_(True))
    ).scalar_one_or_none()

    if not active:
        raise RuntimeError("No active contract found in ref_contract")

    row = session.execute(
        select(PlContractDataDaily.close, PlContractDataDaily.date)
        .where(
            PlContractDataDaily.contract_id == active,
            PlContractDataDaily.close.is_not(None),
        )
        .order_by(PlContractDataDaily.date.desc())
        .limit(1)
    ).one_or_none()

    if not row:
        raise RuntimeError(
            f"No rows with CLOSE in pl_contract_data_daily for contract_id={active}"
        )

    close_val, row_date = row
    close_str = (
        str(int(close_val)) if close_val == int(close_val) else f"{close_val:.2f}"
    )
    date_str = row_date.strftime("%m/%d/%Y")

    log.info("Read CLOSE=%s for date=%s (contract_id=%s)", close_str, date_str, active)
    return close_str, date_str
