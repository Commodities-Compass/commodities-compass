"""CLI script for safe contract roll.

Usage:
    poetry run roll-contract CAN26
    poetry run roll-contract CAN26 --dry-run
"""

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select

from app.models.reference import RefContract
from scripts.contract_resolver import ContractResolverError, resolve_active_code
from scripts.db import get_session

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
    args = parser.parse_args()
    new_code = args.new_code.upper()

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
                    "[DRY RUN] Would deactivate %s and activate %s",
                    current_code,
                    new_code,
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

            # Activate new contract
            new_contract.is_active = True
            session.flush()

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
