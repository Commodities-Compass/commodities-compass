"""Tenant resolution + entitlement enforcement (serving layer).

The whole per-client visibility boundary lives here:

- ``resolve_principal(sub, session)`` maps an Auth0 ``sub`` to a
  :class:`TenantPrincipal` (account + entitlement key set), cached in-memory
  with a 10-minute TTL (a grant/revoke bites within the TTL — acceptable for
  manual ops; see the docs cache caveat).
- ``get_current_principal`` is the FastAPI dependency that resolves it per
  request (cache hit ⇒ no DB round-trip).
- ``require_entitlement(key)`` is the gate: it raises **403** when the flag
  ``ENTITLEMENTS_ENFORCED`` is on and the principal lacks the key.

Default-deny: an authenticated user with no active ``tenant_user`` row resolves
to an EMPTY entitlement set, so every gated route 403s. Existing logins must be
seeded before the flag is flipped on (rollout §10).

This module is import-safe from endpoints only — the pipeline never imports it
("pipelines are shared, tenants subscribe").
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date

from cachetools import TTLCache
from fastapi import Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.entitlements import ALL_ENTITLEMENT_KEYS, INTERNAL
from app.models.billing import BLOCKING_STATUSES, STATUS_MANUAL

# sub -> TenantPrincipal cache (bounds staleness of a downgrade). TTL from config
# (prod 600s / 10 min). TTL <= 0 disables caching entirely (local demos), so a
# tier change is reflected on the next request.
_principal_cache: TTLCache[str, "TenantPrincipal"] | None = (
    TTLCache(maxsize=4096, ttl=settings.PRINCIPAL_CACHE_TTL)
    if settings.PRINCIPAL_CACHE_TTL > 0
    else None
)


@dataclass(frozen=True)
class TenantPrincipal:
    """Immutable per-request identity + entitlements.

    ``account_id is None`` means the authenticated user has no active tenant
    seat → empty entitlements → default-deny under enforcement.
    """

    sub: str
    account_id: uuid.UUID | None = None
    account_code: str | None = None
    tier: str | None = None
    locale: str = "fr"
    algorithm_version_id: uuid.UUID | None = None
    #: Which exporter this account IS, for the benchmark. ``None`` is normal and
    #: means "no exporter identity" — Signal+/Origin Desk have none by nature.
    #: Read-time only: the cube never carries a tenant.
    exporter_entity_id: uuid.UUID | None = None
    #: Payment state of the account (``tenant_account.billing_status``). Surfaced
    #: on /auth/me so the frontend can show the "update your card" banner while
    #: the client is in the retry window and still has full access.
    billing_status: str | None = None
    entitlements: frozenset[str] = field(default_factory=frozenset)

    def has(self, key: str) -> bool:
        return key in self.entitlements


def invalidate_principal(sub: str) -> None:
    """Drop a cached principal (e.g. after a grant/revoke). Best-effort.

    Also called by the Stripe webhook on ``invoice.paid``: without it a client
    who has just fixed a failed card would wait out ``PRINCIPAL_CACHE_TTL``
    (10 min in prod) before regaining access.
    """
    if _principal_cache is not None:
        _principal_cache.pop(sub, None)


def _billing_blocks(status: str | None, paid_through: date | None) -> bool:
    """Does this account's PAYMENT state deny access right now?

    The second axis of the boundary, orthogonal to entitlements: grants record
    *what was bought*, this answers *did they pay*. It never reads or writes
    ``tenant_entitlement`` — a payment incident must not destroy the record of a
    sale (billing design §9 / entitlement design §11.4).

    ``past_due`` deliberately does NOT block: it is the Stripe Smart Retries
    window (~2-3 weeks), and a UEMOA card-ceiling overrun is a banking incident,
    not an unpaid invoice. Cutting access on the first failed debit loses a
    client who was about to be recovered by a card update.
    """
    if not settings.BILLING_ENFORCED:
        return False
    if status is None:
        # No billing row at all — treat as unbilled, not as unpaid. Billing is
        # opt-in per account; default-deny belongs to entitlement, not here.
        return False
    if status == STATUS_MANUAL:
        # Wire / institutional: gated on the date ops last recorded a payment.
        return paid_through is None or paid_through < date.today()
    return status in BLOCKING_STATUSES


async def resolve_principal(sub: str, session: AsyncSession) -> TenantPrincipal:
    """Resolve (and cache) the tenant principal for an Auth0 ``sub``."""
    if _principal_cache is not None:
        cached = _principal_cache.get(sub)
        if cached is not None:
            return cached

    account_row = (
        await session.execute(
            text(
                """
                SELECT a.id, a.code, a.tier, a.locale, a.algorithm_version_id,
                       a.exporter_entity_id, a.billing_status, a.paid_through
                FROM tenant_user u
                JOIN tenant_account a ON a.id = u.account_id
                WHERE u.auth0_sub = :sub AND u.is_active AND a.is_active
                LIMIT 1
                """
            ),
            {"sub": sub},
        )
    ).first()

    if account_row is None:
        principal = TenantPrincipal(sub=sub)
        if _principal_cache is not None:
            _principal_cache[sub] = principal
        return principal

    (
        account_id,
        code,
        tier,
        locale,
        algo_id,
        exporter_entity_id,
        billing_status,
        paid_through,
    ) = account_row

    # `internal` is a NON-COMMERCIAL marker (staff + the grandfathered logins) —
    # it is never billed, so a payment state must never gate it. This exclusion
    # is load-bearing: internal accounts sit at ('manual', NULL) by default, so
    # without it, flipping BILLING_ENFORCED would blank every one of them — the
    # exact failure mode the entitlement backfill existed to prevent.
    billing_denied = tier != INTERNAL and _billing_blocks(billing_status, paid_through)

    # Internal / full-access accounts resolve to the COMPLETE catalogue at
    # read-time — always everything, including keys added after provisioning.
    if tier == INTERNAL:
        principal = TenantPrincipal(
            sub=sub,
            account_id=account_id,
            account_code=code,
            tier=tier,
            locale=locale or "fr",
            algorithm_version_id=algo_id,
            exporter_entity_id=exporter_entity_id,
            billing_status=billing_status,
            entitlements=frozenset(ALL_ENTITLEMENT_KEYS),
        )
        if _principal_cache is not None:
            _principal_cache[sub] = principal
        return principal

    # Unpaid → deny, WITHOUT touching the grants. The account keeps every row in
    # tenant_entitlement (that is the record of what it bought); we simply serve
    # an empty set until payment resumes. Skipping the query is also cheaper.
    if billing_denied:
        principal = TenantPrincipal(
            sub=sub,
            account_id=account_id,
            account_code=code,
            tier=tier,
            locale=locale or "fr",
            algorithm_version_id=algo_id,
            exporter_entity_id=exporter_entity_id,
            billing_status=billing_status,
            entitlements=frozenset(),
        )
        if _principal_cache is not None:
            _principal_cache[sub] = principal
        return principal

    key_rows = (
        await session.execute(
            text(
                "SELECT entitlement_key FROM v_tenant_entitlement_current "
                "WHERE account_id = :aid"
            ),
            {"aid": account_id},
        )
    ).fetchall()

    principal = TenantPrincipal(
        sub=sub,
        account_id=account_id,
        account_code=code,
        tier=tier,
        locale=locale or "fr",
        algorithm_version_id=algo_id,
        exporter_entity_id=exporter_entity_id,
        billing_status=billing_status,
        entitlements=frozenset(r[0] for r in key_rows),
    )
    if _principal_cache is not None:
        _principal_cache[sub] = principal
    return principal


async def get_current_principal(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TenantPrincipal:
    """FastAPI dependency: the resolved principal for the request's token."""
    sub = current_user.get("sub")
    if not sub:
        # No subject on a validated token — treat as anonymous (deny under enforcement).
        return TenantPrincipal(sub="")
    return await resolve_principal(sub, db)


def require_any_entitlement(*keys: str):
    """Return a dependency that 403s unless the principal holds AT LEAST ONE key.

    Endpoints are shared across sections (e.g. ``position-status`` feeds both
    ``SignalHero`` and the ticker), so a route is allowed when the client is
    entitled to ANY section that consumes it. No-op passthrough when
    ``ENTITLEMENTS_ENFORCED`` is off (dark deploy) — the principal is still
    resolved so handlers can read it.
    """
    if not keys:
        raise ValueError("require_any_entitlement needs at least one key")

    async def _dependency(
        principal: TenantPrincipal = Depends(get_current_principal),
    ) -> TenantPrincipal:
        if not settings.ENTITLEMENTS_ENFORCED:
            return principal
        if not any(principal.has(k) for k in keys):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not included in your plan.",
            )
        return principal

    return _dependency


def require_entitlement(key: str):
    """Single-key convenience wrapper over :func:`require_any_entitlement`."""
    return require_any_entitlement(key)
