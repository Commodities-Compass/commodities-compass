"""Database reader for press review — reads CLOSE from pl_contract_data_daily."""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.pipeline import PlContractDataDaily
from app.models.reference import RefContract

log = logging.getLogger(__name__)


def read_latest_close(session: Session) -> tuple[str, str, str, str]:
    """Read the latest CLOSE price, date, and contract info from pl_contract_data_daily.

    Returns:
        Tuple of (close_price_str, date_str MM/DD/YYYY, contract_code, contract_month).

    Raises:
        RuntimeError: If no data found or no active contract.
    """
    # Resolve active contract
    contract = session.execute(
        select(RefContract).where(RefContract.is_active.is_(True))
    ).scalar_one_or_none()

    if not contract:
        raise RuntimeError("No active contract found in ref_contract")

    row = session.execute(
        select(PlContractDataDaily.close, PlContractDataDaily.date)
        .where(
            PlContractDataDaily.contract_id == contract.id,
            PlContractDataDaily.close.is_not(None),
        )
        .order_by(PlContractDataDaily.date.desc())
        .limit(1)
    ).one_or_none()

    if not row:
        raise RuntimeError(
            f"No rows with CLOSE in pl_contract_data_daily for contract_id={contract.id}"
        )

    close_val, row_date = row
    close_str = (
        str(int(close_val)) if close_val == int(close_val) else f"{close_val:.2f}"
    )
    date_str = row_date.strftime("%m/%d/%Y")

    log.info(
        "Read CLOSE=%s for date=%s (contract=%s, month=%s)",
        close_str,
        date_str,
        contract.code,
        contract.contract_month,
    )
    return close_str, date_str, contract.code, contract.contract_month
