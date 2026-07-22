"""CLI script for safe contract roll.

Usage:
    poetry run roll-contract CAN26
    poetry run roll-contract CAN26 --dry-run
"""

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select

from app.models.reference import RefContract
from scripts.contract_resolver import ContractResolverError, resolve_active_code
from scripts.db import get_next_session_date, get_session

load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Roll the active contract to a new code (e.g., CAN26)"
    )
    parser.add_argument(
        "new_code",
        help="New contract code to activate (e.g., CAN26)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without making changes",
    )
    parser.add_argument(
        "--effective-date",
        default=None,
        help=(
            "Session date the new contract becomes the front-month "
            "(YYYY-MM-DD; default: the NEXT trading session). Stamped as "
            "ref_contract.active_from — the canonical roll calendar the "
            "front_month resolver reads. Pass explicitly to re-stamp a rollback."
        ),
    )
    args = parser.parse_args()
    new_code = args.new_code.upper()
    # Default to the NEXT trading session: an evening roll takes effect on the
    # next session, which matches the seed's "first session the contract carries
    # a decision". --effective-date overrides for same-day / backfill / rollback.
    effective_date = (
        date.fromisoformat(args.effective_date)
        if args.effective_date
        else get_next_session_date(date.today())
    )

    try:
        with get_session() as session:
            # Validate: new contract must exist in ref_contract
            new_contract = session.execute(
                select(RefContract).where(RefContract.code == new_code)
            ).scalar_one_or_none()
            if new_contract is None:
                logger.error(
                    "Contract %s not found in ref_contract. "
                    "Add it first before rolling.",
                    new_code,
                )
                return 1

            if new_contract.is_active:
                logger.warning(
                    "Contract %s is already active. Nothing to do.", new_code
                )
                return 0

            # Find current active contract
            try:
                current_code = resolve_active_code(session)
            except ContractResolverError:
                current_code = "(none)"

            logger.info("Rolling contract: %s → %s", current_code, new_code)

            if args.dry_run:
                logger.info(
                    "[DRY RUN] Would deactivate %s and activate %s (active_from=%s)",
                    current_code,
                    new_code,
                    effective_date,
                )
                # Rollback so get_session doesn't commit
                session.rollback()
                return 0

            # Deactivate all currently active contracts
            active_contracts = (
                session.execute(
                    select(RefContract).where(RefContract.is_active.is_(True))
                )
                .scalars()
                .all()
            )
            for contract in active_contracts:
                contract.is_active = False
                logger.info("Deactivated: %s", contract.code)

            # Activate new contract + stamp the canonical roll calendar.
            # is_active stays as a derived cache of the leading edge; active_from
            # is the source of truth the front_month resolver reads.
            new_contract.is_active = True
            if args.effective_date is not None:
                # Explicit date → always (re)stamp; this is how an intentional
                # rollback re-stamps the calendar to a chosen session.
                new_contract.active_from = effective_date
                logger.info(
                    "Set active_from=%s on %s (explicit)", effective_date, new_code
                )
            elif new_contract.active_from is None:
                new_contract.active_from = effective_date
                logger.info("Set active_from=%s on %s", effective_date, new_code)
            else:
                logger.info(
                    "Kept existing active_from=%s on %s (idempotent re-roll)",
                    new_contract.active_from,
                    new_code,
                )
            session.flush()

            # Post-condition: is_active must equal the calendar leading edge
            # (greatest active_from). A silent rollback to an earlier contract
            # keeps a stale, smaller active_from → is_active and the calendar
            # desync. Fail loud; the operator must pass --effective-date to
            # re-stamp an intentional rollback.
            from scripts.front_month import active_front_month

            if active_front_month(session) != new_contract.id:
                raise RuntimeError(
                    f"Roll to {new_code} would desync the calendar: a later "
                    f"contract still has a greater active_from. This looks like a "
                    f"rollback — pass --effective-date to re-stamp intentionally."
                )

            logger.info("Activated: %s", new_code)
            logger.info(
                "Contract roll complete. All scrapers will pick up %s on next run.",
                new_code,
            )

    except Exception as e:
        logger.exception("Contract roll failed: %s", e)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
