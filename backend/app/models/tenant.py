"""Tenant tables — per-client accounts, seats, and entitlements.

Serving-layer only. The pipeline (app/engine, scrapers) NEVER reads these —
"pipelines are shared, tenants subscribe" (North Star principle #3). These
tables gate WHAT a client sees, not WHAT is computed.

Public schema with a ``tenant_`` prefix (like ``pl_`` / ``ref_`` / ``aud_``),
mapping onto the future North Star ``tenant`` PG schema:
- tenant_account      → tenant.account   (the client/org)
- tenant_user         → tenant.user      (a seat: Auth0 identity → account)
- tenant_entitlement  → a subset of tenant.subscription (which keys the account holds)

Entitlements are TEMPORAL (append-only), mirroring pl_algorithm_config:
a grant/revoke INSERTs a new row (old value preserved = provenance); the
``v_tenant_entitlement_current`` view exposes the latest active row per
(account, key). NEVER UPDATE/DELETE an entitlement row.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    DATE,
    INTEGER,
    TIMESTAMP,
    VARCHAR,
    Boolean,
    ForeignKey,
    Index,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class TenantAccount(Base):
    """A client account / organisation. The anchor entitlements hang off."""

    __tablename__ = "tenant_account"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(VARCHAR(50), nullable=False)
    name: Mapped[str] = mapped_column(VARCHAR(200), nullable=False)
    # Provenance of the grant set (starter | pro | enterprise). Not enforced at
    # runtime — the per-key rows in tenant_entitlement are the source of truth.
    tier: Mapped[str] = mapped_column(VARCHAR(30), nullable=False)
    # North Star tenant.account.locale (default fr, matches the content tables).
    locale: Mapped[str] = mapped_column(VARCHAR(5), nullable=False, server_default="fr")
    # Contracted dashboard-seat cap (matrix "Accès dashboard"). NOT hard-enforced
    # — link-seat warns past it. 0 = push-only tier (no dashboard login).
    max_seats: Mapped[int] = mapped_column(
        INTEGER, nullable=False, server_default=text("0")
    )
    # North Star per-tenant knob #1: pin a decision track (legacy vs ensemble).
    # NULL = latest stable / dashboard default (no per-client pin).
    #: Which exporter this account IS, for the "vos flux vs marché" benchmark.
    #:
    #: **Filled by hand and reviewed — never fuzzy-matched.** A mis-mapping shows a
    #: client a competitor's book, which is the single worst failure this codebase
    #: can produce. NULL is the normal state: Signal+ and Origin Desk have no
    #: exporter identity at all (the matrix marks their benchmark `n/a`), and an
    #: account that simply has not been mapped yet must read as "not applicable"
    #: rather than as an empty book.
    exporter_entity_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("ref_origin_entity.id", ondelete="RESTRICT"), nullable=True
    )

    algorithm_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("pl_algorithm_version.id"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )

    #: Payment state — the SECOND axis of the access boundary, orthogonal to the
    #: entitlement grants. `trialing|active|past_due|unpaid|canceled|manual`.
    #: Only `unpaid`/`canceled` deny (and `manual` past `paid_through`); see
    #: `_billing_blocks` in app/core/tenancy.py. Defaults to `manual` so the
    #: migration is non-breaking for every pre-existing account.
    billing_status: Mapped[str] = mapped_column(
        VARCHAR(20), nullable=False, server_default="manual"
    )
    #: Wire / institutional accounts: access is granted while this is >= today.
    #: NULL on a card-billed account, where the provider status governs instead.
    paid_through: Mapped[Optional[date]] = mapped_column(DATE, nullable=True)

    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())

    __table_args__ = (UniqueConstraint("code", name="uq_tenant_account_code"),)


class TenantUser(Base):
    """A seat: maps one Auth0 identity (JWT ``sub``) to an account.

    Entitlements live on the account, so every login under one account shares
    the same view. Makes "N seats per client" real (vs the honor-system today).
    """

    __tablename__ = "tenant_user"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenant_account.id"), nullable=False
    )
    auth0_sub: Mapped[str] = mapped_column(VARCHAR(255), nullable=False)
    email: Mapped[Optional[str]] = mapped_column(VARCHAR(255))
    # Reserved for future admin/viewer distinction — unused at MVP.
    role: Mapped[str] = mapped_column(
        VARCHAR(30), nullable=False, server_default="viewer"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("auth0_sub", name="uq_tenant_user_auth0_sub"),
        Index("ix_tenant_user_account", "account_id"),
    )


class TenantEntitlement(Base):
    """Temporal (append-only) per-account grant of one entitlement key.

    A grant INSERTs ``active=true``; a revoke INSERTs an ``active=false``
    tombstone with a later effective_from. The old row is preserved as
    provenance. ``v_tenant_entitlement_current`` collapses to the latest
    active row per (account, key). NEVER UPDATE/DELETE.
    """

    __tablename__ = "tenant_entitlement"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenant_account.id"), nullable=False
    )
    entitlement_key: Mapped[str] = mapped_column(VARCHAR(100), nullable=False)
    effective_from: Mapped[date] = mapped_column(
        DATE, nullable=False, server_default=text("DATE '2000-01-01'")
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "entitlement_key",
            "effective_from",
            name="uq_tenant_entitlement_key_eff",
        ),
        Index("ix_tenant_entitlement_account", "account_id"),
    )
