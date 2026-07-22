"""Resolve contract codes to UUIDs from ref_contract table."""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.reference import RefContract

log = logging.getLogger(__name__)

# ICE London Cocoa #7 delivery-month cycle (Barchart codes are CA<letter><yy>).
# H=Mar, K=May, N=Jul, U=Sep, Z=Dec — the only months that trade.
_CONTRACT_PREFIX = "CA"
_MONTH_CYCLE = ["H", "K", "N", "U", "Z"]
_MONTH_NUMBER = {"H": 3, "K": 5, "N": 7, "U": 9, "Z": 12}


class ContractResolverError(Exception):
    pass


def _parse_code(code: str) -> tuple[str, int]:
    """Split a ``CA<letter><yy>`` code into (month_letter, 2-digit year). Fail-loud."""
    code = code.upper()
    letter, yy = (code[2], code[3:]) if len(code) == 5 else ("", "")
    if (
        not code.startswith(_CONTRACT_PREFIX)
        or letter not in _MONTH_CYCLE
        or not yy.isdigit()
    ):
        raise ContractResolverError(f"Unexpected contract code format: {code!r}")
    return letter, int(yy)


def next_contract_code(code: str) -> str:
    """Next delivery month in the H-K-N-U-Z cocoa cycle (Z rolls to H, year+1).

    e.g. CAU26 -> CAZ26, CAZ26 -> CAH27. Used to derive the back-month the
    scraper also captures so ``v_contract_data_chained`` always has both
    contracts around a roll.
    """
    letter, yy = _parse_code(code)
    idx = _MONTH_CYCLE.index(letter)
    if idx == len(_MONTH_CYCLE) - 1:
        return f"{_CONTRACT_PREFIX}{_MONTH_CYCLE[0]}{(yy + 1) % 100:02d}"
    return f"{_CONTRACT_PREFIX}{_MONTH_CYCLE[idx + 1]}{yy:02d}"


def contract_month_for(code: str) -> str:
    """``YYYY-MM`` delivery month for a code (CAU26 -> '2026-09')."""
    letter, yy = _parse_code(code)
    return f"20{yy:02d}-{_MONTH_NUMBER[letter]:02d}"


def ensure_contract(
    session: Session, code: str, *, commodity_id: uuid.UUID
) -> uuid.UUID:
    """Return the contract_id for ``code``, auto-creating an inactive row if absent.

    Lets the scraper register the next delivery month on the fly so the
    front-month-by-OI chained VIEW always has both contracts around a roll —
    making rolls a data-layer non-event. ``expiry_date`` is left NULL (never
    fabricated); the chained VIEW and front-month logic key on OI, not expiry,
    and the precise expiry is set at roll time if ever needed.
    """
    existing = session.execute(
        select(RefContract).where(RefContract.code == code)
    ).scalar_one_or_none()
    if existing is not None:
        return existing.id
    contract = RefContract(
        commodity_id=commodity_id,
        code=code,
        contract_month=contract_month_for(code),
        is_active=False,
    )
    session.add(contract)
    session.flush()
    log.info(
        "Auto-registered next contract %s (month=%s, inactive)",
        code,
        contract.contract_month,
    )
    return contract.id


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
