"""Billing endpoints — the Stripe webhook and the Customer Portal link.

Two routes, deliberately small:

- ``POST /v1/webhooks/stripe`` — unauthenticated by necessity (Stripe cannot
  send an Auth0 token), gated on the HMAC signature instead. Same shape as the
  signed ``/audio/stream`` boundary.
- ``POST /v1/billing/portal-session`` — authenticated; returns the URL where a
  client updates a failed card.

Design: docs/architecture/billing-and-collection.md
"""

from __future__ import annotations

import logging

import sentry_sdk
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.tenancy import (
    TenantPrincipal,
    get_current_principal,
    invalidate_principal,
)
from app.services import billing_service

logger = logging.getLogger(__name__)

router = APIRouter()


class PortalSessionResponse(BaseModel):
    url: str


@router.post("/webhooks/stripe", include_in_schema=False)
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(default="", alias="Stripe-Signature"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Apply a Stripe event to billing state. Idempotent, fail-loud.

    Returning **500 on a processing failure so Stripe retries is intentional and
    is NOT a violation of .claude/rules/pipeline-error-handling.md.** That rule
    forbids a *producer* from silently retrying to hide a root cause. Here:

    - the failure is loud (ERROR log + Sentry + a persisted `error` column),
    - the retry is the webhook transport contract, not a recovery hack,
    - and the alternative — swallowing a payment event with a 200 — is exactly
      the silent wrong state the rule exists to prevent.

    Do not "fix" this by returning 200 on error.
    """
    payload = await request.body()

    try:
        event = billing_service.verify_and_parse(payload, stripe_signature)
    except billing_service.BillingError as exc:
        # A bad signature is an attacker or a misconfiguration, never a retry
        # candidate — 400 so Stripe stops resending.
        logger.error("Rejected Stripe webhook: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature."
        ) from exc

    event_id = str(event.get("id"))
    event_type = str(event.get("type"))

    # Archive first. If this returns False the event was already applied, so a
    # redelivery is a no-op rather than a double application.
    is_new = await billing_service.record_event(db, event)
    if not is_new:
        logger.info(
            "Stripe event %s (%s) already handled — skipped.", event_id, event_type
        )
        return {"status": "duplicate"}

    try:
        subs = await billing_service.apply_event(db, event)
        await db.execute(
            text(
                "UPDATE aud_billing_event SET processed_at = now() "
                "WHERE provider = 'stripe' AND event_id = :eid"
            ),
            {"eid": event_id},
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        # Persist the reason on the archived row so the failure is diagnosable
        # from the DB alone, then let the 500 trigger Stripe's retry.
        await db.execute(
            text(
                "UPDATE aud_billing_event SET error = :err "
                "WHERE provider = 'stripe' AND event_id = :eid"
            ),
            {"err": str(exc)[:2000], "eid": event_id},
        )
        await db.commit()
        logger.exception("Stripe event %s (%s) failed", event_id, event_type)
        sentry_sdk.capture_exception(exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Webhook processing failed.",
        ) from exc

    # Drop cached principals so a restored payment grants access immediately
    # rather than after PRINCIPAL_CACHE_TTL (10 min in prod).
    for sub in subs:
        invalidate_principal(sub)

    logger.info(
        "Stripe event %s (%s) applied, %d principal(s) invalidated.",
        event_id,
        event_type,
        len(subs),
    )
    return {"status": "ok"}


@router.post("/billing/portal-session", response_model=PortalSessionResponse)
async def create_portal_session(
    principal: TenantPrincipal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> PortalSessionResponse:
    """Return the Stripe Customer Portal URL for the caller's account.

    Deliberately NOT behind an entitlement key: a client whose access is denied
    for non-payment must still be able to reach the portal and fix their card.
    Gating this would be a trap that makes recovery impossible.
    """
    if principal.account_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No tenant account."
        )

    row = (
        await db.execute(
            text(
                "SELECT provider_customer_id FROM tenant_billing_subscription "
                "WHERE account_id = :aid AND active "
                "AND provider_customer_id IS NOT NULL "
                "ORDER BY effective_from DESC LIMIT 1"
            ),
            {"aid": principal.account_id},
        )
    ).first()

    if row is None:
        # Manual/wire accounts have no Stripe customer — there is nothing to
        # manage, and saying so beats a 500 from the Stripe SDK.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No card billing on this account.",
        )

    try:
        url = await billing_service.create_portal_session(
            customer_id=row[0],
            return_url=f"{settings.frontend_url}/dashboard",
        )
    except billing_service.BillingError as exc:
        logger.error("Portal session failed for %s: %s", principal.account_code, exc)
        sentry_sdk.capture_exception(exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Billing provider unavailable.",
        ) from exc

    return PortalSessionResponse(url=url)
