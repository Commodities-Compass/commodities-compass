"""CLI for billing ops — read state, record a wire payment, mint a Checkout link.

Manual ops, no admin UI, same spirit as ``tenant_admin.py`` and
``set-farmgate-price``. Design: docs/architecture/billing-and-collection.md

    poetry run billing-status       --account acme
    poetry run mark-paid            --account acme --until 2027-08-31
    poetry run create-checkout-link --account acme --price price_1ABC…

``mark-paid`` is the wire / institutional path and needs no Stripe account at
all — it is what carries clients who structurally cannot put a card on file.
``create-checkout-link`` does need Stripe credentials and a Price created in the
Stripe dashboard.

Writes via ``DATABASE_SYNC_URL`` (scripts.db.get_session): localhost:5433
locally, Cloud SQL against prod through the bastion tunnel.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select, text

from app.models.billing import CUSTOMER_TYPE_BUSINESS, CUSTOMER_TYPES
from app.models.tenant import TenantAccount
from scripts.db import get_session

load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def _account(session, code: str) -> TenantAccount:
    account = session.execute(
        select(TenantAccount).where(TenantAccount.code == code)
    ).scalar_one_or_none()
    if account is None:
        raise SystemExit(f"No tenant_account with code {code!r}.")
    return account


# --------------------------------------------------------------------------- #
# billing-status
# --------------------------------------------------------------------------- #
def billing_status() -> int:
    p = argparse.ArgumentParser(description="Show the billing state of an account.")
    p.add_argument("--account", required=True, help="tenant_account.code")
    args = p.parse_args()

    with get_session() as session:
        account = _account(session, args.account)
        logger.info("Account %s (%s)", account.code, account.name)
        logger.info("  tier            : %s", account.tier)
        logger.info("  billing_status  : %s", account.billing_status)
        logger.info("  paid_through    : %s", account.paid_through or "—")

        if account.billing_status == "manual":
            expired = (
                account.paid_through is None or account.paid_through < date.today()
            )
            logger.info(
                "  access (if BILLING_ENFORCED): %s",
                "DENIED — paid_through missing or past" if expired else "granted",
            )

        subs = session.execute(
            text(
                """
                SELECT provider, provider_customer_id, provider_subscription_id,
                       tier, customer_type, amount_cents, currency,
                       billing_interval, status, current_period_end,
                       effective_from, active
                FROM tenant_billing_subscription
                WHERE account_id = :aid
                ORDER BY effective_from DESC, created_at DESC
                """
            ),
            {"aid": account.id},
        ).fetchall()
        if not subs:
            logger.info("  no subscription row (manual/wire account)")
        for s in subs:
            m = s._mapping
            logger.info(
                "  sub %s %s %s [%s] %d %s/%s status=%s until=%s active=%s",
                m["provider"],
                m["provider_subscription_id"] or "—",
                m["tier"],
                m["customer_type"],
                m["amount_cents"],
                m["currency"],
                m["billing_interval"],
                m["status"],
                m["current_period_end"] or "—",
                m["active"],
            )

        invoices = session.execute(
            text(
                """
                SELECT number, amount_cents, amount_received_cents, currency,
                       status, rail, paid_at
                FROM tenant_billing_invoice
                WHERE account_id = :aid
                ORDER BY COALESCE(issued_at, created_at) DESC
                LIMIT 5
                """
            ),
            {"aid": account.id},
        ).fetchall()
        for inv in invoices:
            m = inv._mapping
            short = ""
            # Only meaningful on a SETTLED invoice: an `open` one is short by its
            # full amount simply because it has not been paid, which would flag
            # every unpaid invoice as a short payment.
            if (
                m["status"] == "paid"
                and m["amount_received_cents"] is not None
                and m["amount_received_cents"] < m["amount_cents"]
            ):
                # Correspondent-bank skim on a wire. Visible, not silently lost.
                short = f"  ⚠ SHORT by {m['amount_cents'] - m['amount_received_cents']}"
            logger.info(
                "  invoice %s %d %s %s via %s paid=%s%s",
                m["number"] or "—",
                m["amount_cents"],
                m["currency"],
                m["status"],
                m["rail"],
                m["paid_at"] or "—",
                short,
            )
    return 0


# --------------------------------------------------------------------------- #
# mark-paid
# --------------------------------------------------------------------------- #
def mark_paid() -> int:
    p = argparse.ArgumentParser(
        description="Record a wire/manual payment: set billing_status=manual + paid_through."
    )
    p.add_argument("--account", required=True, help="tenant_account.code")
    p.add_argument(
        "--until", required=True, help="Access granted through this date (YYYY-MM-DD)"
    )
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    try:
        until = datetime.strptime(args.until, "%Y-%m-%d").date()
    except ValueError as exc:
        raise SystemExit(f"--until must be YYYY-MM-DD, got {args.until!r}") from exc
    if until < date.today():
        # Allowed (backdating a lapsed account is legitimate) but never silent.
        logger.warning("--until %s is in the PAST: this DENIES access.", until)

    with get_session() as session:
        account = _account(session, args.account)
        logger.info(
            "%s: billing_status %s → manual, paid_through %s → %s",
            account.code,
            account.billing_status,
            account.paid_through or "—",
            until,
        )
        if args.dry_run:
            logger.info("[DRY RUN] No row written.")
            return 0
        session.execute(
            text(
                "UPDATE tenant_account "
                "SET billing_status = 'manual', paid_through = :until WHERE id = :id"
            ),
            {"until": until, "id": account.id},
        )
    logger.info(
        "Done. Cached principals expire within PRINCIPAL_CACHE_TTL (10 min in prod)."
    )
    return 0


# --------------------------------------------------------------------------- #
# create-checkout-link
# --------------------------------------------------------------------------- #
def create_checkout_link() -> int:
    p = argparse.ArgumentParser(
        description="Mint a Stripe Checkout link that captures a card and starts the sub."
    )
    p.add_argument("--account", required=True, help="tenant_account.code")
    p.add_argument("--price", required=True, help="Stripe Price id (price_…)")
    p.add_argument("--amount-cents", type=int, required=True, help="For our own record")
    p.add_argument("--interval", default="month", choices=["month", "year"])
    # Recorded per CONTRACT because French consumer protections bind at contract
    # formation: which regime applied is not reconstructable later from the
    # account. Constant while we sell B2B only — that is the point.
    p.add_argument(
        "--customer-type",
        default=CUSTOMER_TYPE_BUSINESS,
        choices=sorted(CUSTOMER_TYPES),
        help="Legal regime at contract formation (default: business).",
    )
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    # Imported lazily: this is the only command that needs Stripe credentials,
    # and billing-status / mark-paid must keep working without them.
    from app.core.config import settings
    from app.services import billing_service

    with get_session() as session:
        account = _account(session, args.account)
        logger.info(
            "Checkout for %s tier=%s %d EUR-cents/%s regime=%s price=%s",
            account.code,
            account.tier,
            args.amount_cents,
            args.interval,
            args.customer_type,
            args.price,
        )
        if args.dry_run:
            logger.info("[DRY RUN] No Stripe call, no row written.")
            return 0

        url = asyncio.run(
            billing_service.create_checkout_session(
                account_code=account.code,
                price_id=args.price,
                success_url=f"{settings.frontend_url}/dashboard?billing=ok",
                cancel_url=f"{settings.frontend_url}/dashboard?billing=cancelled",
            )
        )

        # The row is created NOW, in `incomplete`, so the webhook has something
        # to attach the Stripe ids to when checkout.session.completed arrives.
        session.execute(
            text(
                """
                INSERT INTO tenant_billing_subscription
                    (id, account_id, provider, tier, customer_type, currency,
                     amount_cents, billing_interval, status, effective_from, active)
                VALUES (:id, :aid, 'stripe', :tier, :ctype, 'EUR', :amt,
                        :itv, 'incomplete', CURRENT_DATE, true)
                ON CONFLICT DO NOTHING
                """
            ),
            {
                "id": uuid.uuid4(),
                "aid": account.id,
                "tier": account.tier,
                "ctype": args.customer_type,
                "amt": args.amount_cents,
                "itv": args.interval,
            },
        )

    logger.info("Send this link to the client:\n\n  %s\n", url)
    return 0
