"""add pl_official_farmgate_price table (CCC/COCOBOD guaranteed price)

Revision ID: b1c2d3e4f5a6
Revises: 43a8a015a3d4
Create Date: 2026-07-22

Append-only table for the official guaranteed farmgate price announced by
CCC (Côte d'Ivoire, FCFA/kg) and COCOBOD (Ghana, GHS per 64 kg bag). Each
revision is a new row (immutable history). Manual ops entry via
``poetry run set-farmgate-price``.

See: docs/user-stories/P1-align-offre-v11-colonne-livree.md §T1
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "b1c2d3e4f5a6"
down_revision: str = "43a8a015a3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pl_official_farmgate_price",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("region", sa.VARCHAR(10), nullable=False),
        sa.Column("season_label", sa.VARCHAR(20), nullable=False),
        sa.Column("effective_date", sa.DATE(), nullable=False),
        sa.Column("announced_date", sa.DATE(), nullable=True),
        sa.Column("price_native", sa.DECIMAL(14, 4), nullable=False),
        sa.Column("currency", sa.VARCHAR(3), nullable=False),
        sa.Column("unit", sa.VARCHAR(16), nullable=False),
        sa.Column("source", sa.VARCHAR(16), nullable=False),
        sa.Column("source_url", sa.TEXT(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "region",
            "effective_date",
            "announced_date",
            name="uq_farmgate_region_effective_announced",
        ),
        sa.CheckConstraint("region IN ('civ', 'ghana')", name="ck_farmgate_region"),
        sa.CheckConstraint(
            "unit IN ('per_kg', 'per_bag_64kg', 'per_tonne')",
            name="ck_farmgate_unit",
        ),
        sa.CheckConstraint("source IN ('ccc', 'cocobod')", name="ck_farmgate_source"),
        sa.CheckConstraint("price_native > 0", name="ck_farmgate_price_positive"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_farmgate_region_effective",
        "pl_official_farmgate_price",
        ["region", "effective_date"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_farmgate_region_effective",
        table_name="pl_official_farmgate_price",
    )
    op.drop_table("pl_official_farmgate_price")
