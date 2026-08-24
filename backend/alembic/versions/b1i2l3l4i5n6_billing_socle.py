"""billing socle: billing_status on tenant_account + 3 billing tables

Recurring EUR card-on-file billing (docs/architecture/billing-and-collection.md).

  - tenant_account.billing_status / paid_through : where billing bites
  - tenant_billing_subscription : what the client is signed up to (temporal)
  - tenant_billing_invoice      : mirror of Stripe invoices, history + PDF links
  - aud_billing_event           : raw webhook archive + idempotency key

NON-BREAKING BY CONSTRUCTION: `billing_status` defaults to 'manual' with a NULL
`paid_through`, and `_billing_blocks()` short-circuits on BILLING_ENFORCED=false.
So every existing account keeps working with no backfill — unlike the entitlement
socle, whose default-deny made a backfill mandatory before its flip.

`billing_interval` (not `interval`) and `event_type` (not `type`) are deliberate:
both plain names collide with SQL keywords, and while SQLAlchemy quotes
identifiers, any hand-written SQL against these tables would not.

Idempotent (safe re-apply on GCP): guarded table + column creation.

Revision ID: b1i2l3l4i5n6
Revises: u3j4u5d6g7e8
Create Date: 2026-08-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = "b1i2l3l4i5n6"
down_revision: Union[str, Sequence[str], None] = "u3j4u5d6g7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def _has_column(table: str, column: str) -> bool:
    insp = inspect(op.get_bind())
    if not insp.has_table(table):
        return False
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    # --- 1. Where billing bites: two columns on the existing account ---------
    if not _has_column("tenant_account", "billing_status"):
        op.add_column(
            "tenant_account",
            sa.Column(
                "billing_status",
                sa.VARCHAR(20),
                nullable=False,
                server_default="manual",
                comment=(
                    "trialing|active|past_due|unpaid|canceled|manual. "
                    "'manual' = wire/institutional, gated on paid_through."
                ),
            ),
        )
    if not _has_column("tenant_account", "paid_through"):
        op.add_column(
            "tenant_account",
            sa.Column(
                "paid_through",
                sa.Date(),
                nullable=True,
                comment="Manual/wire accounts: access granted while >= today.",
            ),
        )

    # --- 2. Subscriptions (temporal append-only) -----------------------------
    if not _has_table("tenant_billing_subscription"):
        op.create_table(
            "tenant_billing_subscription",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "account_id",
                sa.Uuid(),
                sa.ForeignKey("tenant_account.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            # `provider` exists from day one so a second collector is a row, not
            # a migration. Only 'stripe' is implemented.
            sa.Column(
                "provider", sa.VARCHAR(20), nullable=False, server_default="stripe"
            ),
            sa.Column("provider_customer_id", sa.VARCHAR(255), nullable=True),
            sa.Column("provider_subscription_id", sa.VARCHAR(255), nullable=True),
            # Denormalised on purpose: what was sold, at the time it was sold.
            sa.Column("tier", sa.VARCHAR(30), nullable=False),
            sa.Column("currency", sa.VARCHAR(3), nullable=False, server_default="EUR"),
            sa.Column("amount_cents", sa.Integer(), nullable=False),
            sa.Column("billing_interval", sa.VARCHAR(10), nullable=False),
            sa.Column("status", sa.VARCHAR(30), nullable=False),
            sa.Column("current_period_end", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column(
                "effective_from",
                sa.Date(),
                nullable=False,
                server_default=sa.func.current_date(),
            ),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.UniqueConstraint(
                "account_id",
                "provider_subscription_id",
                "effective_from",
                name="uq_billing_subscription_account_sub_from",
            ),
        )
        op.create_index(
            "ix_billing_subscription_account",
            "tenant_billing_subscription",
            ["account_id"],
        )

    # --- 3. Invoices (mirror of Stripe) --------------------------------------
    if not _has_table("tenant_billing_invoice"):
        op.create_table(
            "tenant_billing_invoice",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "account_id",
                sa.Uuid(),
                sa.ForeignKey("tenant_account.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column(
                "provider", sa.VARCHAR(20), nullable=False, server_default="stripe"
            ),
            sa.Column("provider_invoice_id", sa.VARCHAR(255), nullable=False),
            sa.Column("number", sa.VARCHAR(50), nullable=True),
            sa.Column("amount_cents", sa.Integer(), nullable=False),
            # Correspondent banks skim SWIFT transfers, so a wire routinely lands
            # short of the invoice. Storing both makes the gap visible instead of
            # silently failing an exact-match reconciliation.
            sa.Column("amount_received_cents", sa.Integer(), nullable=True),
            sa.Column("currency", sa.VARCHAR(3), nullable=False, server_default="EUR"),
            sa.Column("status", sa.VARCHAR(20), nullable=False),
            sa.Column("rail", sa.VARCHAR(10), nullable=False, server_default="card"),
            sa.Column("issued_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("due_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("paid_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("hosted_url", sa.VARCHAR(500), nullable=True),
            sa.Column("pdf_url", sa.VARCHAR(500), nullable=True),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.UniqueConstraint(
                "provider", "provider_invoice_id", name="uq_billing_invoice_provider_id"
            ),
        )
        op.create_index(
            "ix_billing_invoice_account", "tenant_billing_invoice", ["account_id"]
        )

    # --- 4. Webhook archive + idempotency ------------------------------------
    if not _has_table("aud_billing_event"):
        op.create_table(
            "aud_billing_event",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "provider", sa.VARCHAR(20), nullable=False, server_default="stripe"
            ),
            sa.Column("event_id", sa.VARCHAR(255), nullable=False),
            sa.Column("event_type", sa.VARCHAR(100), nullable=False),
            # Archived BEFORE interpretation: when something is wrong six months
            # from now, the raw payload is the only evidence.
            sa.Column(
                "payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False
            ),
            sa.Column(
                "received_at",
                sa.TIMESTAMP(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("processed_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            # The idempotency key. INSERT ... ON CONFLICT DO NOTHING on this pair
            # is what makes a Stripe redelivery a no-op.
            sa.UniqueConstraint(
                "provider", "event_id", name="uq_billing_event_provider_event"
            ),
        )
        op.create_index(
            "ix_billing_event_received", "aud_billing_event", ["received_at"]
        )


def downgrade() -> None:
    if _has_table("aud_billing_event"):
        op.drop_table("aud_billing_event")
    if _has_table("tenant_billing_invoice"):
        op.drop_table("tenant_billing_invoice")
    if _has_table("tenant_billing_subscription"):
        op.drop_table("tenant_billing_subscription")
    if _has_column("tenant_account", "paid_through"):
        op.drop_column("tenant_account", "paid_through")
    if _has_column("tenant_account", "billing_status"):
        op.drop_column("tenant_account", "billing_status")
