"""tenant_account.exporter_entity_id — the benchmark's identity link

Adds the one column the "Benchmark « vos flux vs marché »" row of matrix block ②
needs: which exporter a tenant account *is*.

Deliberately nullable with no backfill and no default. NULL is a meaningful,
common state:

- Signal+ and Origin Desk have **no exporter identity at all** — the matrix marks
  their benchmark `n/a`, and the endpoint answers "not applicable" rather than
  403 or an empty book.
- A newly created Export Premium account is unmapped until a human maps it.

`ondelete="RESTRICT"` rather than SET NULL or CASCADE: `ref_origin_entity` is
rebuilt on every `watchai-sync` run, and silently repointing or clearing a
client's identity during an ingestion is exactly the failure mode this column
must never have. A refused delete is a loud, fixable problem; a silently changed
identity shows one client another client's book.

Design: docs/watchai/watchai-integration.md §3 and §6.

Revision ID: p1q2r3s4t5u6
Revises: n9c0d1e2f3g4
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "p1q2r3s4t5u6"
down_revision = "n9c0d1e2f3g4"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    """Idempotent by inspection — GCP re-applies migrations on cold start."""
    bind = op.get_bind()
    return column in {
        row["name"]
        for row in sa.inspect(bind).get_columns(table)  # type: ignore[index]
    }


def upgrade() -> None:
    if not _has_column("tenant_account", "exporter_entity_id"):
        op.add_column(
            "tenant_account",
            sa.Column("exporter_entity_id", sa.Uuid(), nullable=True),
        )
        op.create_foreign_key(
            "fk_tenant_account_exporter_entity",
            "tenant_account",
            "ref_origin_entity",
            ["exporter_entity_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        # Partial: only mapped accounts are indexed, and most never will be.
        op.create_index(
            "ix_tenant_account_exporter_entity",
            "tenant_account",
            ["exporter_entity_id"],
            unique=False,
            postgresql_where=sa.text("exporter_entity_id IS NOT NULL"),
        )


def downgrade() -> None:
    if _has_column("tenant_account", "exporter_entity_id"):
        op.drop_index("ix_tenant_account_exporter_entity", table_name="tenant_account")
        op.drop_constraint(
            "fk_tenant_account_exporter_entity", "tenant_account", type_="foreignkey"
        )
        op.drop_column("tenant_account", "exporter_entity_id")
