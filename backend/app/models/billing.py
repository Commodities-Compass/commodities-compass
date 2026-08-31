"""Billing tables — recurring EUR card-on-file collection.

Serving-layer only, like the tenant tables they hang off. The pipeline never
reads these. Design: docs/architecture/billing-and-collection.md.

**The load-bearing separation**: billing NEVER writes ``tenant_entitlement``.
Grants record *what the client bought* (append-only, with provenance); billing
answers *did they pay*, and that answer lives in ``tenant_account.billing_status``.
A payment incident must never destroy the record of a sale — see
``_billing_blocks`` in ``app/core/tenancy.py``, which ANDs the two axes at
read time and leaves grants untouched.

  - tenant_billing_subscription : what the client is signed up to (temporal)
  - tenant_billing_invoice      : mirror of the provider's invoices
  - aud_billing_event           : raw webhook archive + the idempotency key
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import (
    DATE,
    INTEGER,
    TEXT,
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

#: Statuses that deny access when BILLING_ENFORCED is on. `past_due` is
#: deliberately absent: it is the Stripe Smart Retries window (~2-3 weeks), and a
#: UEMOA card-ceiling overrun is a banking incident, not an unpaid invoice.
BLOCKING_STATUSES: frozenset[str] = frozenset({"unpaid", "canceled"})

#: The default for every account, including every pre-existing one. Gated on
#: `paid_through` rather than on a provider subscription — this is the wire /
#: institutional path, and it is what makes the migration non-breaking.
STATUS_MANUAL = "manual"

#: Legal regime of a contract. French consumer protections (14-day withdrawal,
#: simplified cancellation, renewal notice) bind at CONTRACT FORMATION, so the
#: regime that applied has to be recorded per contract rather than derived from
#: a current account attribute — it cannot be reconstructed after the fact.
#: Constant `business` while we sell B2B only; the column exists so that opening
#: to consumers later does not leave existing contracts undocumented.
CUSTOMER_TYPE_BUSINESS = "business"
CUSTOMER_TYPE_CONSUMER = "consumer"
CUSTOMER_TYPES: frozenset[str] = frozenset(
    {CUSTOMER_TYPE_BUSINESS, CUSTOMER_TYPE_CONSUMER}
)


class TenantBillingSubscription(Base):
    """What an account is signed up to. Temporal append-only."""

    __tablename__ = "tenant_billing_subscription"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "provider_subscription_id",
            "effective_from",
            name="uq_billing_subscription_account_sub_from",
        ),
        Index("ix_billing_subscription_account", "account_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenant_account.id", ondelete="RESTRICT"), nullable=False
    )
    #: 'stripe' today. The column exists so a second collector is a row, not a
    #: migration — see the design doc §7 (three rails, one event).
    provider: Mapped[str] = mapped_column(
        VARCHAR(20), nullable=False, server_default="stripe"
    )
    provider_customer_id: Mapped[Optional[str]] = mapped_column(VARCHAR(255))
    provider_subscription_id: Mapped[Optional[str]] = mapped_column(VARCHAR(255))
    #: Denormalised on purpose: what was sold, at the time it was sold. The
    #: account's current tier can change without rewriting billing history.
    tier: Mapped[str] = mapped_column(VARCHAR(30), nullable=False)
    #: Same logic, applied to the legal regime — see CUSTOMER_TYPES above.
    customer_type: Mapped[str] = mapped_column(
        VARCHAR(20), nullable=False, server_default=CUSTOMER_TYPE_BUSINESS
    )
    currency: Mapped[str] = mapped_column(
        VARCHAR(3), nullable=False, server_default="EUR"
    )
    amount_cents: Mapped[int] = mapped_column(INTEGER, nullable=False)
    #: 'month' | 'year'. Named `billing_interval` because `interval` is a SQL
    #: keyword — SQLAlchemy would quote it, hand-written SQL would not.
    billing_interval: Mapped[str] = mapped_column(VARCHAR(10), nullable=False)
    status: Mapped[str] = mapped_column(VARCHAR(30), nullable=False)
    current_period_end: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True)
    )
    effective_from: Mapped[date] = mapped_column(
        DATE, nullable=False, server_default=func.current_date()
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )


class TenantBillingInvoice(Base):
    """Mirror of a provider invoice — history, amounts, PDF links."""

    __tablename__ = "tenant_billing_invoice"
    __table_args__ = (
        UniqueConstraint(
            "provider", "provider_invoice_id", name="uq_billing_invoice_provider_id"
        ),
        Index("ix_billing_invoice_account", "account_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenant_account.id", ondelete="RESTRICT"), nullable=False
    )
    provider: Mapped[str] = mapped_column(
        VARCHAR(20), nullable=False, server_default="stripe"
    )
    provider_invoice_id: Mapped[str] = mapped_column(VARCHAR(255), nullable=False)
    number: Mapped[Optional[str]] = mapped_column(VARCHAR(50))
    amount_cents: Mapped[int] = mapped_column(INTEGER, nullable=False)
    #: Correspondent banks skim SWIFT transfers, so a wire routinely arrives
    #: short of the invoiced amount. Storing both makes the gap queryable
    #: instead of silently failing an exact-match reconciliation.
    amount_received_cents: Mapped[Optional[int]] = mapped_column(INTEGER)
    currency: Mapped[str] = mapped_column(
        VARCHAR(3), nullable=False, server_default="EUR"
    )
    status: Mapped[str] = mapped_column(VARCHAR(20), nullable=False)
    #: 'card' | 'wire' | 'manual' — which rail actually settled it.
    rail: Mapped[str] = mapped_column(
        VARCHAR(10), nullable=False, server_default="card"
    )
    issued_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    due_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    paid_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    hosted_url: Mapped[Optional[str]] = mapped_column(VARCHAR(500))
    pdf_url: Mapped[Optional[str]] = mapped_column(VARCHAR(500))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )


class AudBillingEvent(Base):
    """Raw provider webhook. The archive AND the idempotency key.

    ``UNIQUE(provider, event_id)`` is what makes a redelivery a no-op: the
    handler INSERTs first and stops if the row already existed. Stripe retries
    on any non-2xx, so this table is the difference between "retry is safe" and
    "a payment was applied twice".
    """

    __tablename__ = "aud_billing_event"
    __table_args__ = (
        UniqueConstraint(
            "provider", "event_id", name="uq_billing_event_provider_event"
        ),
        Index("ix_billing_event_received", "received_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(
        VARCHAR(20), nullable=False, server_default="stripe"
    )
    event_id: Mapped[str] = mapped_column(VARCHAR(255), nullable=False)
    event_type: Mapped[str] = mapped_column(VARCHAR(100), nullable=False)
    #: Archived BEFORE interpretation. When something is wrong six months from
    #: now, this is the only evidence of what the provider actually sent.
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    #: Set when handling raised. Non-NULL here + a Sentry event is the fail-loud
    #: trail; the webhook still returns 500 so the provider retries.
    error: Mapped[Optional[str]] = mapped_column(TEXT)
