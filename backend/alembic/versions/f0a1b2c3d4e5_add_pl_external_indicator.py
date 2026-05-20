"""add pl_external_indicator table for ENSO + FX features

Revision ID: f0a1b2c3d4e5
Revises: e5f6a7b8c9d0
Create Date: 2026-05-20

Commodity-agnostic table, keyed on date only. Shared by:
  * cc-enso-scraper (NOAA PSL, monthly, writes enso_* columns)
  * cc-fx-scraper (ECB SDMX, daily, writes fx_* columns)

See:
  * docs/user-stories/P1-scraper-enso.md §4.1
  * docs/user-stories/P1-scraper-fx.md §4
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "f0a1b2c3d4e5"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pl_external_indicator",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("date", sa.DATE(), nullable=False),
        # ENSO (monthly publication, date = 1st of month, lag applied at compute-time)
        sa.Column("enso_oni_month", sa.DECIMAL(8, 4), nullable=True),
        sa.Column("enso_nino34_anomaly", sa.DECIMAL(8, 4), nullable=True),
        # FX (daily business-days)
        sa.Column("fx_dxy_proxy", sa.DECIMAL(15, 6), nullable=True),
        sa.Column("fx_gbpusd", sa.DECIMAL(15, 6), nullable=True),
        sa.Column("fx_eurusd", sa.DECIMAL(15, 6), nullable=True),
        sa.Column("fx_gbpeur", sa.DECIMAL(15, 6), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.func.now()),
        sa.UniqueConstraint("date", name="uq_external_indicator_date"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_external_indicator_date",
        "pl_external_indicator",
        ["date"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_external_indicator_date", table_name="pl_external_indicator")
    op.drop_table("pl_external_indicator")
