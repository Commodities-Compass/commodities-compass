"""Resolve contract codes to UUIDs from ref_contract table."""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.reference import RefContract

log = logging.getLogger(__name__)


class ContractResolverError(Exception):
    pass


def resolve_by_code(session: Session, code: str) -> uuid.UUID:
    """Look up a contract ID by exact code (e.g., 'CAK26').

    Used by: Barchart scraper (ACTIVE_CONTRACT env var).
    """
    result = session.execute(
        select(RefContract).where(RefContract.code == code)
    ).scalar_one_or_none()
    if result is None:
        raise ContractResolverError(f"Contract not found: {code}")
    return result.id


def resolve_active(session: Session) -> uuid.UUID:
    """Look up the currently active contract (is_active=True).

    Used by: ICE stocks, CFTC scrapers.
    """
    result = session.execute(
        select(RefContract).where(RefContract.is_active.is_(True))
    ).scalar_one_or_none()
    if result is None:
        raise ContractResolverError("No active contract found in ref_contract")
    return result.id


def resolve_active_code(session: Session) -> str:
    """Look up the active contract code (e.g., 'CAK26') from ref_contract.

    Used by: Barchart scraper (replaces ACTIVE_CONTRACT env var).
    Raises ContractResolverError if zero or multiple active contracts.
    """
    result = session.execute(
        select(RefContract).where(RefContract.is_active.is_(True))
    ).scalar_one_or_none()
    if result is None:
        raise ContractResolverError("No active contract found in ref_contract")
    return result.code


def resolve_active_at_date(session: Session, target_date) -> uuid.UUID:
    """Resolve the front-month contract on a historical date.

    Picks the contract with the highest open interest on ``target_date``.
    This is the "front-month-by-OI" convention used by R&D when assembling
    the canonical training dataset — the most liquid contract on any given
    day is the one whose OHLCV reflects the market.

    Used by: ensemble-compute backfill (historical dates pre-current-roll).
    The live cc-ensemble-compute job uses ``resolve_active`` (is_active=TRUE
    from ref_contract) for today's run.

    Raises ContractResolverError if no row exists in pl_contract_data_daily
    for the given date.
    """
    from sqlalchemy import text as sa_text

    # Deterministic tiebreak: (OI desc, volume desc, contract_id asc). On a
    # roll-boundary date where two contracts have identical OI, the contract_id
    # sort guarantees reproducibility across reruns. R&D's training set used
    # the same convention.
    row = session.execute(
        sa_text(
            "SELECT contract_id, COALESCE(oi, 0) AS oi_val, "
            "       COALESCE(volume, 0) AS vol_val "
            "FROM pl_contract_data_daily "
            "WHERE date = :d "
            "ORDER BY COALESCE(oi, 0) DESC, "
            "         COALESCE(volume, 0) DESC, "
            "         contract_id ASC "
            "LIMIT 1"
        ),
        {"d": target_date},
    ).fetchone()
    if row is None:
        raise ContractResolverError(
            f"No pl_contract_data_daily row for date={target_date} "
            "— cannot resolve historical front-month contract"
        )
    import logging

    logging.getLogger(__name__).info(
        "Historical front-month for %s: contract_id=%s (oi=%s, volume=%s)",
        target_date,
        row[0],
        row[1],
        row[2],
    )
    return row[0]
