"""widen pl_sentiment_feature.raw_score from DECIMAL(4,3) to DECIMAL(6,3)

DECIMAL(4,3) only allows 1 digit before the decimal point (max 9.999).
Sentiment scores near ±1.0 can overflow on edge cases. DECIMAL(6,3)
matches zscore/zscore_delta columns (3 digits before decimal).

Revision ID: e5f6a7b8c9d0
Revises: d4f5a6b7c8e9
Create Date: 2026-04-29
"""

from alembic import op
import sqlalchemy as sa

revision = "e5f6a7b8c9d0"
down_revision = "d4f5a6b7c8e9"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    """Check if a column exists (safe for re-runs on GCP)."""
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :column"
        ),
        {"table": table, "column": column},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    if _has_column("pl_sentiment_feature", "raw_score"):
        op.alter_column(
            "pl_sentiment_feature",
            "raw_score",
            type_=sa.DECIMAL(6, 3),
            existing_type=sa.DECIMAL(4, 3),
            existing_nullable=True,
        )


def downgrade() -> None:
    if _has_column("pl_sentiment_feature", "raw_score"):
        op.alter_column(
            "pl_sentiment_feature",
            "raw_score",
            type_=sa.DECIMAL(4, 3),
            existing_type=sa.DECIMAL(6, 3),
            existing_nullable=True,
        )
