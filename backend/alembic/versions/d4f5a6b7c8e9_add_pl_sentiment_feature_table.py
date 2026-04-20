"""add pl_sentiment_feature table

Revision ID: d4f5a6b7c8e9
Revises: a7b8c9d0e1f2
Create Date: 2026-04-20
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "d4f5a6b7c8e9"
down_revision = "8f620009140e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pl_sentiment_feature",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("date", sa.DATE(), nullable=False, index=True),
        sa.Column("theme", sa.VARCHAR(30), nullable=False),
        sa.Column("raw_score", sa.DECIMAL(4, 3)),
        sa.Column("zscore", sa.DECIMAL(6, 3)),
        sa.Column("zscore_delta", sa.DECIMAL(6, 3)),
        sa.Column("min_periods_met", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.func.now()),
        sa.UniqueConstraint("date", "theme", name="uq_sentiment_feature_date_theme"),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_table("pl_sentiment_feature")
