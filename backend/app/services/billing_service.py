"""Stripe billing — collection, not access control.

Stripe collects and chases; ``tenant_account.billing_status`` decides access
(see ``_billing_blocks`` in ``app/core/tenancy.py``). This module owns the
translation between the two, and nothing else.

Design: docs/architecture/billing-and-collection.md

Two responsibilities:

1. **Outbound** — mint the Stripe-hosted surfaces (Checkout for card capture,
   Customer Portal for card updates). Card data never reaches our frontend, so
   we stay out of PCI scope entirely.
2. **Inbound** — verify, record and apply webhook events. Every rail (card,
   wire via ``paid_out_of_band``, a future mobile-money collector) converges on
   the same ``invoice.paid`` event, so there is exactly one place where access
   flips.

**This module never writes ``tenant_entitlement``.** Grants record what a client
bought; billing records whether they paid. A failed debit must not destroy the
provenance of a sale.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import stripe
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.billing import TenantBillingInvoice
from app.models.tenant import TenantAccount

logger = logging.getLogger(__name__)

PROVIDER = "stripe"

#: Stripe subscription status → our `billing_status`. Anything absent leaves the
#: current value untouched rather than guessing: an unknown status must not
#: silently deny a paying client.
_STATUS_MAP: dict[str, str] = {
    "trialing": "trialing",
    "active": "active",
    "past_due": "past_due",
    "unpaid": "unpaid",
    "canceled": "canceled",
    # `incomplete` = the very first payment never completed. Treat as past_due,
    # not unpaid: the client may still finish the Checkout flow.
    "incomplete": "past_due",
    "incomplete_expired": "canceled",
    "paused": "past_due",
}


class BillingError(RuntimeError):
    """Billing failed. Always surfaced, never swallowed."""


class StripeNotConfiguredError(BillingError):
    """A Stripe call was attempted without credentials — fail loud.

    Silently no-op'ing here would make a missing secret look like a client who
    never subscribed, which is exactly the kind of quiet wrong state that costs
    money to unpick later.
    """


def _client() -> Any:
    if not settings.STRIPE_SECRET_KEY:
        raise StripeNotConfiguredError(
            "STRIPE_SECRET_KEY is not set — cannot reach Stripe."
        )
    stripe.api_key = settings.STRIPE_SECRET_KEY
    return stripe


# --------------------------------------------------------------------------- #
# Outbound — the Stripe-hosted surfaces
# --------------------------------------------------------------------------- #
async def create_checkout_session(
    *,
    account_code: str,
    price_id: str,
    success_url: str,
    cancel_url: str,
    customer_id: str | None = None,
) -> str:
    """Return a hosted Checkout URL that captures a card and starts the sub.

    `subscription` mode collects the card AND the mandate authorising later
    off-session debits — that mandate is what makes recurring possible at all.

    3DS is requested on the save even though the transaction is out of SCA
    scope (EEA acquirer + non-EEA issuer = one-leg-out): it shifts chargeback
    liability and strengthens the mandate. On the save, not on every charge.
    """
    api = _client()

    def _create() -> Any:
        return api.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            # How the webhook finds the account without trusting client input.
            client_reference_id=account_code,
            customer=customer_id,
            success_url=success_url,
            cancel_url=cancel_url,
            payment_method_options={
                "card": {"request_three_d_secure": "any"},
            },
        )

    session = await run_in_threadpool(_create)
    return str(session.url)


async def create_portal_session(*, customer_id: str, return_url: str) -> str:
    """Return a Customer Portal URL — where a client fixes a failed card.

    Not optional: under the `past_due` policy the client keeps full access and
    a banner, and this URL is the entire recovery loop. Without it every card
    failure becomes a support ticket.
    """
    api = _client()

    def _create() -> Any:
        return api.billing_portal.Session.create(
            customer=customer_id, return_url=return_url
        )

    session = await run_in_threadpool(_create)
    return str(session.url)


# --------------------------------------------------------------------------- #
# Inbound — webhook
# --------------------------------------------------------------------------- #
def verify_and_parse(payload: bytes, signature: str) -> dict[str, Any]:
    """Verify the Stripe signature and return the event.

    An unverified payload must never be allowed to change access state, so a
    missing secret is an error, not a bypass.
    """
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise StripeNotConfiguredError(
            "STRIPE_WEBHOOK_SECRET is not set — refusing to trust a webhook."
        )
    try:
        event = stripe.Webhook.construct_event(
            payload, signature, settings.STRIPE_WEBHOOK_SECRET
        )
    except Exception as exc:  # ValueError | SignatureVerificationError
        raise BillingError(f"Invalid Stripe webhook signature: {exc}") from exc
    return dict(event)


async def record_event(session: AsyncSession, event: dict[str, Any]) -> bool:
    """Archive the raw event. Return False if it was already seen.

    ``UNIQUE(provider, event_id)`` is the idempotency key: Stripe redelivers on
    any non-2xx, so a duplicate must be a no-op rather than a second application
    of the same payment.
    """
    result = await session.execute(
        text(
            """
            INSERT INTO aud_billing_event
                (id, provider, event_id, event_type, payload)
            VALUES (:id, :provider, :event_id, :event_type, CAST(:payload AS jsonb))
            ON CONFLICT (provider, event_id) DO NOTHING
            RETURNING id
            """
        ),
        {
            "id": uuid.uuid4(),
            "provider": PROVIDER,
            "event_id": event.get("id"),
            "event_type": event.get("type"),
            "payload": json.dumps(event, default=str),
        },
    )
    return result.first() is not None


async def _account_by_code(session: AsyncSession, code: str) -> TenantAccount | None:
    return (
        await session.execute(select(TenantAccount).where(TenantAccount.code == code))
    ).scalar_one_or_none()


async def _account_by_customer(
    session: AsyncSession, customer_id: str
) -> TenantAccount | None:
    row = (
        await session.execute(
            text(
                """
                SELECT a.* FROM tenant_account a
                JOIN tenant_billing_subscription s ON s.account_id = a.id
                WHERE s.provider_customer_id = :cid AND s.active
                ORDER BY s.effective_from DESC
                LIMIT 1
                """
            ),
            {"cid": customer_id},
        )
    ).first()
    if row is None:
        return None
    return (
        await session.execute(select(TenantAccount).where(TenantAccount.id == row.id))
    ).scalar_one_or_none()


async def _set_status(
    session: AsyncSession, account: TenantAccount, status: str
) -> None:
    await session.execute(
        text("UPDATE tenant_account SET billing_status = :s WHERE id = :id"),
        {"s": status, "id": account.id},
    )


async def _subs_of(session: AsyncSession, account: TenantAccount) -> list[str]:
    """Auth0 subs seated on this account — whose cached principal must be dropped."""
    rows = (
        await session.execute(
            text(
                "SELECT auth0_sub FROM tenant_user "
                "WHERE account_id = :aid AND is_active"
            ),
            {"aid": account.id},
        )
    ).fetchall()
    return [r[0] for r in rows]


def _ts(value: Any) -> datetime | None:
    if not value:
        return None
    return datetime.fromtimestamp(int(value), tz=timezone.utc)


async def _mirror_invoice(
    session: AsyncSession, account: TenantAccount, obj: dict[str, Any], rail: str
) -> None:
    existing = (
        await session.execute(
            select(TenantBillingInvoice).where(
                TenantBillingInvoice.provider == PROVIDER,
                TenantBillingInvoice.provider_invoice_id == obj.get("id"),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return
    session.add(
        TenantBillingInvoice(
            account_id=account.id,
            provider=PROVIDER,
            provider_invoice_id=str(obj.get("id")),
            number=obj.get("number"),
            amount_cents=int(obj.get("amount_due") or 0),
            amount_received_cents=int(obj.get("amount_paid") or 0),
            currency=str(obj.get("currency") or "eur").upper(),
            status=str(obj.get("status") or "open"),
            rail=rail,
            issued_at=_ts(obj.get("created")),
            due_at=_ts(obj.get("due_date")),
            paid_at=_ts(obj.get("status_transitions", {}).get("paid_at")),
            hosted_url=obj.get("hosted_invoice_url"),
            pdf_url=obj.get("invoice_pdf"),
        )
    )


async def apply_event(session: AsyncSession, event: dict[str, Any]) -> list[str]:
    """Apply an event to billing state. Return the Auth0 subs to invalidate.

    Unknown event types are ignored on purpose — Stripe sends far more than we
    subscribe to, and reacting to an unrecognised one is how you get surprises.
    """
    etype = str(event.get("type"))
    obj = dict(event.get("data", {}).get("object", {}))

    if etype == "checkout.session.completed":
        code = obj.get("client_reference_id")
        account = await _account_by_code(session, str(code)) if code else None
        if account is None:
            raise BillingError(
                f"checkout.session.completed has no resolvable account "
                f"(client_reference_id={code!r})"
            )
        await session.execute(
            text(
                """
                UPDATE tenant_billing_subscription
                   SET provider_customer_id = :cid,
                       provider_subscription_id = :sid,
                       status = 'active'
                 WHERE account_id = :aid AND active
                """
            ),
            {
                "cid": obj.get("customer"),
                "sid": obj.get("subscription"),
                "aid": account.id,
            },
        )
        await _set_status(session, account, "active")
        return await _subs_of(session, account)

    customer_id = obj.get("customer")
    if not customer_id:
        return []
    account = await _account_by_customer(session, str(customer_id))
    if account is None:
        # A Stripe customer we do not know about. Loud, but not fatal: returning
        # 500 would make Stripe retry an event we can never resolve.
        logger.warning(
            "Stripe event %s for unknown customer %s — ignored.", etype, customer_id
        )
        return []

    if etype == "invoice.paid":
        rail = "wire" if obj.get("paid_out_of_band") else "card"
        await _mirror_invoice(session, account, obj, rail)
        await _set_status(session, account, "active")
        # Invalidate so a client who just fixed their card regains access NOW,
        # instead of waiting out PRINCIPAL_CACHE_TTL.
        return await _subs_of(session, account)

    if etype == "invoice.payment_failed":
        await _mirror_invoice(session, account, obj, "card")
        await _set_status(session, account, "past_due")
        # No invalidation: past_due keeps access, so the cached principal is
        # still correct. The frontend banner comes from /auth/me on next load.
        return []

    if etype in ("customer.subscription.updated", "customer.subscription.deleted"):
        stripe_status = str(obj.get("status") or "")
        mapped = (
            "canceled"
            if etype == "customer.subscription.deleted"
            else _STATUS_MAP.get(stripe_status)
        )
        if mapped is None:
            logger.warning(
                "Unmapped Stripe subscription status %r for account %s — "
                "billing_status left unchanged.",
                stripe_status,
                account.code,
            )
            return []
        await session.execute(
            text(
                "UPDATE tenant_billing_subscription SET status = :s "
                "WHERE account_id = :aid AND active"
            ),
            {"s": mapped, "aid": account.id},
        )
        await _set_status(session, account, mapped)
        return await _subs_of(session, account)

    return []
