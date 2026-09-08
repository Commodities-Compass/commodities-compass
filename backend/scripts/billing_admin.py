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
from urllib.parse import urlparse

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


#: Hosts that can only ever mean "the machine that typed the command".
_LOCAL_HOSTS: frozenset[str] = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})


class LocalReturnUrlError(SystemExit):
    """The Checkout return URL points at the operator's machine — refuse."""


def resolve_return_base(*, explicit: str | None, configured: str) -> str:
    """Return the base URL Stripe sends the paying client back to.

    ``settings.frontend_url`` derives from the CORS origins, which is right on
    the deployed service and wrong everywhere else: this CLI is normally run
    from a laptop against the production database, so it would bake
    ``http://localhost:3000`` into a link a real client follows. On 2026-09-08
    it did exactly that — the payment succeeded, the client landed on a refused
    connection, and a successful charge looked like a failed one.

    So this fails loud rather than guess. There is no default pointing at the
    production URL either: a hardcoded fallback is the failure mode
    ``BRIEF_DEFAULT_VERSION`` already documented — it survives a domain change
    and nobody notices until a client cannot come back.
    """
    base = (explicit or configured).rstrip("/")
    host = urlparse(base).hostname or ""
    if host.lower() in _LOCAL_HOSTS:
        raise LocalReturnUrlError(
            f"Refusing to mint a Checkout link returning to {base!r}: that is "
            f"this machine, not the client's. Pass --frontend-url "
            f"https://app.com-compass.com (the URL the CLIENT uses)."
        )
    return base


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
    p.add_argument(
        "--frontend-url",
        default=None,
        help=(
            "Base URL the CLIENT is sent back to after paying, e.g. "
            "https://app.com-compass.com. Defaults to the configured frontend "
            "URL, which is only correct when running on the deployed service."
        ),
    )
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    # Imported lazily: this is the only command that needs Stripe credentials,
    # and billing-status / mark-paid must keep working without them.
    from app.core.config import settings
    from app.services import billing_service

    # Resolved BEFORE any Stripe call: a refusal must cost nothing, and a link
    # that strands the client is worse than no link at all.
    base = resolve_return_base(
        explicit=args.frontend_url, configured=settings.frontend_url
    )

    with get_session() as session:
        account = _account(session, args.account)
        # Reuse the Stripe customer this account already has, if any — a second
        # one forks the client's payment methods and invoice history in two.
        known_customer = session.execute(
            text(
                "SELECT provider_customer_id FROM tenant_billing_subscription "
                "WHERE account_id = :aid AND active AND provider_customer_id "
                "IS NOT NULL ORDER BY effective_from DESC LIMIT 1"
            ),
            {"aid": account.id},
        ).scalar_one_or_none()

        logger.info(
            "Checkout for %s tier=%s %d EUR-cents/%s regime=%s price=%s return=%s",
            account.code,
            account.tier,
            args.amount_cents,
            args.interval,
            args.customer_type,
            args.price,
            base,
        )
        if args.dry_run:
            logger.info("[DRY RUN] No Stripe call, no row written.")
            return 0

        handle = asyncio.run(
            billing_service.create_checkout_session(
                account_code=account.code,
                price_id=args.price,
                success_url=f"{base}/dashboard?billing=ok",
                cancel_url=f"{base}/dashboard?billing=cancelled",
                customer_id=known_customer,
            )
        )

        # The row is created NOW, in `incomplete`, carrying the customer id —
        # so every webhook Stripe sends, including the ones that land before
        # `checkout.session.completed`, resolves to this account.
        session.execute(
            text(
                """
                INSERT INTO tenant_billing_subscription
                    (id, account_id, provider, provider_customer_id, tier,
                     customer_type, currency, amount_cents, billing_interval,
                     status, effective_from, active)
                VALUES (:id, :aid, 'stripe', :cid, :tier, :ctype, 'EUR', :amt,
                        :itv, 'incomplete', CURRENT_DATE, true)
                ON CONFLICT DO NOTHING
                """
            ),
            {
                "id": uuid.uuid4(),
                "aid": account.id,
                "cid": handle.customer_id,
                "tier": account.tier,
                "ctype": args.customer_type,
                "amt": args.amount_cents,
                "itv": args.interval,
            },
        )
        # The INSERT above is a no-op when an active row already exists (a
        # re-issued link, or a row written before this fix). Bind it anyway —
        # leaving it NULL is what loses the events.
        session.execute(
            text(
                "UPDATE tenant_billing_subscription SET provider_customer_id = :cid "
                "WHERE account_id = :aid AND active AND provider_customer_id IS NULL"
            ),
            {"cid": handle.customer_id, "aid": account.id},
        )

    logger.info("Send this link to the client:\n\n  %s\n", handle.url)
    return 0
