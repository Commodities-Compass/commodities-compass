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
