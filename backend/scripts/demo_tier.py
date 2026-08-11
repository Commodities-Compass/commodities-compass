"""DEV/DEMO helper — set an account's entitlements to EXACTLY one tier.

Unlike ``set-tier`` (additive — it only appends the new tier's grants), this
sets the account's CURRENT view to precisely the tier: it upserts a row dated
today for EVERY catalogue key with ``active = (key in tier)``, so keys outside
the tier are tombstoned and keys inside are granted. Append-only (no DELETE),
idempotent same-day. Also updates ``tier`` + ``max_seats``.

Intended for local demos ("show each tier one by one"), typically with the API
running at PRINCIPAL_CACHE_TTL=0 so each switch is visible on the next refresh.

    poetry run demo-set-tier --account me --tier export_essentiel
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select, text

from app.core.entitlements import (
    ALL_ENTITLEMENT_KEYS,
    PROVISIONABLE_TIERS,
    expand_tier,
    max_seats_for,
)
from app.models.tenant import TenantAccount
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
        description="DEV: set an account's entitlements to exactly one tier."
    )
    parser.add_argument("--account", required=True, help="tenant_account.code")
    parser.add_argument("--tier", required=True, choices=sorted(PROVISIONABLE_TIERS))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    tier_keys = expand_tier(args.tier)
    seats = max_seats_for(args.tier)
    logger.info(
        "Set account=%s to EXACTLY tier=%s (%d keys, %d seats)",
        args.account, args.tier, len(tier_keys), seats,
    )
    if args.dry_run:
        logger.info("[DRY RUN] granted: %s", sorted(tier_keys))
        logger.info("[DRY RUN] tombstoned: %s", sorted(ALL_ENTITLEMENT_KEYS - tier_keys))
        return 0

    today = date.today()
    with get_session() as session:
        account = session.execute(
            select(TenantAccount).where(TenantAccount.code == args.account)
        ).scalar_one_or_none()
        if account is None:
            raise SystemExit(f"No tenant_account with code {args.account!r}.")

        account.tier = args.tier
        account.max_seats = seats

        for key in sorted(ALL_ENTITLEMENT_KEYS):
            session.execute(
                text(
                    """
                    INSERT INTO tenant_entitlement
                        (id, account_id, entitlement_key, effective_from, active)
                    VALUES (gen_random_uuid(), :aid, :key, :eff, :active)
                    ON CONFLICT (account_id, entitlement_key, effective_from)
                    DO UPDATE SET active = EXCLUDED.active
                    """
                ),
                {
                    "aid": account.id,
                    "key": key,
                    "eff": today,
                    "active": key in tier_keys,
                },
            )
    logger.info("Account %s now shows exactly tier %s.", args.account, args.tier)
    return 0


if __name__ == "__main__":
    sys.exit(main())
