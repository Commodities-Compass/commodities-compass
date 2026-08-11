"""CLI provisioning for per-client tenants, seats, and entitlements.

Manual ops (no admin UI). Append-only, mirroring ``set-farmgate-price`` and the
temporal config pattern: a grant/revoke INSERTs a row (never UPDATE/DELETE) so
history is preserved. The ``v_tenant_entitlement_current`` view collapses to the
latest active row per (account, key).

Entry points (pyproject scripts):
    poetry run create-tenant     --code acme --name "Acme" --tier pro [--locale fr] [--algo-version <uuid>]
    poetry run link-seat         --account acme --auth0-sub "auth0|abc" [--email x@acme.com] [--role viewer]
    poetry run grant-entitlement --account acme --key read:section:weather
    poetry run revoke-entitlement --account acme --key read:section:weather
    poetry run set-tier          --account acme --tier enterprise

All write via DATABASE_SYNC_URL (scripts.db.get_session). Locally that is
localhost:5433; against prod it is Cloud SQL — same posture as the other ops CLIs.

NOTE: the API caches a resolved principal for 10 min per instance; a grant/revoke
is picked up within that TTL (or immediately on a service restart).
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select, text

from sqlalchemy import func

from app.core.entitlements import (
    ALL_ENTITLEMENT_KEYS,
    PROVISIONABLE_TIERS,
    expand_tier,
    is_valid_key,
    max_seats_for,
)
from app.models.tenant import TenantAccount, TenantUser
from scripts.db import get_session

load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def _account_id(session, code: str):
    account = session.execute(
        select(TenantAccount).where(TenantAccount.code == code)
    ).scalar_one_or_none()
    if account is None:
        raise SystemExit(f"No tenant_account with code {code!r}. Create it first.")
    return account.id


def _append_grant(session, account_id, key: str, active: bool) -> None:
    """Append a temporal entitlement row (idempotent per (account, key, today))."""
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
        {"aid": account_id, "key": key, "eff": date.today(), "active": active},
    )


# --------------------------------------------------------------------------- #
# create-tenant
# --------------------------------------------------------------------------- #
def create_tenant() -> int:
    p = argparse.ArgumentParser(description="Create a tenant account + seed its tier grants.")
    p.add_argument("--code", required=True, help="Stable handle, e.g. acme")
    p.add_argument("--name", required=True)
    p.add_argument("--tier", required=True, choices=sorted(PROVISIONABLE_TIERS))
    p.add_argument("--locale", default="fr")
    p.add_argument("--algo-version", default=None, help="pl_algorithm_version.id to pin (optional)")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    keys = sorted(expand_tier(args.tier))
    seats = max_seats_for(args.tier)
    logger.info(
        "Create tenant code=%s name=%s tier=%s locale=%s → %d grants, %d seats",
        args.code, args.name, args.tier, args.locale, len(keys), seats,
    )
    if args.dry_run:
        logger.info("[DRY RUN] grants: %s", keys)
        return 0

    with get_session() as session:
        exists = session.execute(
            select(TenantAccount.id).where(TenantAccount.code == args.code)
        ).scalar_one_or_none()
        if exists is not None:
            raise SystemExit(f"tenant_account {args.code!r} already exists.")
        account = TenantAccount(
            code=args.code,
            name=args.name,
            tier=args.tier,
            locale=args.locale,
            max_seats=seats,
            algorithm_version_id=args.algo_version,
        )
        session.add(account)
        session.flush()
        for key in keys:
            _append_grant(session, account.id, key, active=True)
    logger.info("Created tenant %s with %d entitlements.", args.code, len(keys))
    return 0


# --------------------------------------------------------------------------- #
# link-seat
# --------------------------------------------------------------------------- #
def link_seat() -> int:
    p = argparse.ArgumentParser(description="Link an Auth0 identity (seat) to an account.")
    p.add_argument("--account", required=True, help="tenant_account.code")
    p.add_argument("--auth0-sub", required=True, help="JWT sub, e.g. auth0|abc")
    p.add_argument("--email", default=None)
    p.add_argument("--role", default="viewer")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    logger.info("Link seat sub=%s → account=%s", args.auth0_sub, args.account)
    if args.dry_run:
        logger.info("[DRY RUN] No row written.")
        return 0

    with get_session() as session:
        account = session.execute(
            select(TenantAccount).where(TenantAccount.code == args.account)
        ).scalar_one_or_none()
        if account is None:
            raise SystemExit(f"No tenant_account with code {args.account!r}.")
        existing = session.execute(
            select(TenantUser).where(TenantUser.auth0_sub == args.auth0_sub)
        ).scalar_one_or_none()
        if existing is not None:
            raise SystemExit(
                f"Seat {args.auth0_sub!r} already linked to account_id={existing.account_id}."
            )
        active_seats = session.execute(
            select(func.count())
            .select_from(TenantUser)
            .where(TenantUser.account_id == account.id, TenantUser.is_active.is_(True))
        ).scalar_one()
        # Soft cap: warn but never block (contracted seats are a commercial commitment).
        if active_seats >= account.max_seats:
            logger.warning(
                "Seat cap: account %s has %d/%d active seats — adding this one EXCEEDS "
                "the contracted cap (allowed, not blocked).",
                args.account, active_seats, account.max_seats,
            )
        session.add(
            TenantUser(
                account_id=account.id,
                auth0_sub=args.auth0_sub,
                email=args.email,
                role=args.role,
            )
        )
    logger.info(
        "Linked seat %s to %s (%d/%d seats used).",
        args.auth0_sub, args.account, active_seats + 1, account.max_seats,
    )
    return 0


# --------------------------------------------------------------------------- #
# grant / revoke entitlement
# --------------------------------------------------------------------------- #
def _grant_or_revoke(active: bool, verb: str) -> int:
    p = argparse.ArgumentParser(description=f"{verb.capitalize()} an entitlement key (append-only).")
    p.add_argument("--account", required=True, help="tenant_account.code")
    p.add_argument("--key", required=True, help="e.g. read:section:weather")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    if not is_valid_key(args.key):
        raise SystemExit(
            f"Unknown entitlement key {args.key!r}. Valid keys:\n  "
            + "\n  ".join(sorted(ALL_ENTITLEMENT_KEYS))
        )

    logger.info("%s %s on account=%s (effective %s)", verb, args.key, args.account, date.today())
    if args.dry_run:
        logger.info("[DRY RUN] No row written.")
        return 0

    with get_session() as session:
        account_id = _account_id(session, args.account)
        _append_grant(session, account_id, args.key, active=active)
    logger.info("%s %s for %s.", verb, args.key, args.account)
    return 0


def grant_entitlement() -> int:
    return _grant_or_revoke(active=True, verb="grant")


def revoke_entitlement() -> int:
    return _grant_or_revoke(active=False, verb="revoke")


# --------------------------------------------------------------------------- #
# set-tier
# --------------------------------------------------------------------------- #
def set_tier() -> int:
    p = argparse.ArgumentParser(
        description="Set an account tier + append the tier's grants (does NOT auto-revoke extras)."
    )
    p.add_argument("--account", required=True, help="tenant_account.code")
    p.add_argument("--tier", required=True, choices=sorted(PROVISIONABLE_TIERS))
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    keys = sorted(expand_tier(args.tier))
    logger.info("Set tier %s on account=%s → %d grants", args.tier, args.account, len(keys))
    if args.dry_run:
        logger.info("[DRY RUN] grants: %s", keys)
        return 0

    with get_session() as session:
        account = session.execute(
            select(TenantAccount).where(TenantAccount.code == args.account)
        ).scalar_one_or_none()
        if account is None:
            raise SystemExit(f"No tenant_account with code {args.account!r}.")
        account.tier = args.tier
        for key in keys:
            _append_grant(session, account.id, key, active=True)
    logger.info(
        "Set %s to tier %s and appended %d grants "
        "(keys outside the tier are NOT revoked — use revoke-entitlement).",
        args.account, args.tier, len(keys),
    )
    return 0


if __name__ == "__main__":
    sys.exit(grant_entitlement())
