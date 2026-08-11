"""tenant accounts, seats, entitlements (+ current-entitlement view)

Per-client entitlement socle (serving-layer only — the pipeline never reads it).
Three tables + one view, following the temporal append-only pattern already used
by pl_algorithm_config / v_algorithm_config_current:

  - tenant_account            : the client/org (code, name, tier, locale, algo pin)
  - tenant_user              : a seat — Auth0 sub → account
  - tenant_entitlement       : append-only per-key grant (effective_from + active)
  - v_tenant_entitlement_current : latest active row per (account, key) as of today

Idempotent (safe re-apply on GCP): guarded table creation + CREATE OR REPLACE VIEW.

Revision ID: t1e2n3a4n5t6
Revises: m8b9c0d1e2f3
Create Date: 2026-07-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "t1e2n3a4n5t6"
down_revision: Union[str, Sequence[str], None] = "m8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if not _has_table("tenant_account"):
        op.create_table(
            "tenant_account",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("code", sa.VARCHAR(50), nullable=False),
            sa.Column("name", sa.VARCHAR(200), nullable=False),
            sa.Column("tier", sa.VARCHAR(30), nullable=False),
            sa.Column(
                "locale", sa.VARCHAR(5), nullable=False, server_default="fr"
            ),
            sa.Column(
                "max_seats",
                sa.INTEGER(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "algorithm_version_id",
                sa.Uuid(),
                sa.ForeignKey("pl_algorithm_version.id"),
                nullable=True,
            ),
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
            sa.Column(
                "created_at", sa.TIMESTAMP(), server_default=sa.func.now()
            ),
            sa.UniqueConstraint("code", name="uq_tenant_account_code"),
        )

    if not _has_table("tenant_user"):
        op.create_table(
            "tenant_user",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "account_id",
                sa.Uuid(),
                sa.ForeignKey("tenant_account.id"),
                nullable=False,
            ),
            sa.Column("auth0_sub", sa.VARCHAR(255), nullable=False),
            sa.Column("email", sa.VARCHAR(255), nullable=True),
            sa.Column(
                "role", sa.VARCHAR(30), nullable=False, server_default="viewer"
            ),
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
            sa.Column(
                "created_at", sa.TIMESTAMP(), server_default=sa.func.now()
            ),
            sa.UniqueConstraint("auth0_sub", name="uq_tenant_user_auth0_sub"),
        )
        op.create_index("ix_tenant_user_account", "tenant_user", ["account_id"])

    if not _has_table("tenant_entitlement"):
        op.create_table(
            "tenant_entitlement",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "account_id",
                sa.Uuid(),
                sa.ForeignKey("tenant_account.id"),
                nullable=False,
            ),
            sa.Column("entitlement_key", sa.VARCHAR(100), nullable=False),
            sa.Column(
                "effective_from",
                sa.DATE(),
                nullable=False,
                server_default=sa.text("DATE '2000-01-01'"),
            ),
            sa.Column(
                "active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
            sa.Column(
                "created_at", sa.TIMESTAMP(), server_default=sa.func.now()
            ),
            sa.UniqueConstraint(
                "account_id",
                "entitlement_key",
                "effective_from",
                name="uq_tenant_entitlement_key_eff",
            ),
        )
        op.create_index(
            "ix_tenant_entitlement_account", "tenant_entitlement", ["account_id"]
        )

    # Current-entitlement VIEW: latest row per (account, key) as of today, active only.
    op.execute(
        """
        CREATE OR REPLACE VIEW v_tenant_entitlement_current AS
        SELECT latest.* FROM (
            SELECT DISTINCT ON (account_id, entitlement_key) *
            FROM tenant_entitlement
            WHERE effective_from <= CURRENT_DATE
            ORDER BY account_id, entitlement_key, effective_from DESC
        ) latest
        WHERE latest.active
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_tenant_entitlement_current")
    op.execute("DROP TABLE IF EXISTS tenant_entitlement")
    op.execute("DROP TABLE IF EXISTS tenant_user")
    op.execute("DROP TABLE IF EXISTS tenant_account")
