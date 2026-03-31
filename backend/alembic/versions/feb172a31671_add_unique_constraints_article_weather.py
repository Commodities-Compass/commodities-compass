"""add_unique_constraints_article_weather

Revision ID: feb172a31671
Revises: 6d4eef12be0c
Create Date: 2026-03-31 14:30:28.075489

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = "feb172a31671"
down_revision: Union[str, Sequence[str], None] = "6d4eef12be0c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Clean duplicates, add NOT NULL + unique constraints."""
    conn = op.get_bind()

    # --- pl_fundamental_article ---

    # 1. Backfill any NULL llm_provider to 'unknown'
    conn.execute(
        text("""
            UPDATE pl_fundamental_article
            SET llm_provider = 'unknown'
            WHERE llm_provider IS NULL
        """)
    )

    # 2. Delete duplicates: keep latest created_at per (date, llm_provider)
    conn.execute(
        text("""
            DELETE FROM pl_fundamental_article
            WHERE id NOT IN (
                SELECT DISTINCT ON (date, llm_provider) id
                FROM pl_fundamental_article
                ORDER BY date, llm_provider, created_at DESC
            )
        """)
    )

    # 3. Make llm_provider NOT NULL
    op.alter_column(
        "pl_fundamental_article",
        "llm_provider",
        nullable=False,
        existing_type=sa.VARCHAR(50),
    )

    # 4. Add unique constraint
    op.create_unique_constraint(
        "uq_fundamental_article_date_provider",
        "pl_fundamental_article",
        ["date", "llm_provider"],
    )

    # --- pl_weather_observation ---

    # 5. Delete duplicates: keep latest created_at per (date)
    conn.execute(
        text("""
            DELETE FROM pl_weather_observation
            WHERE id NOT IN (
                SELECT DISTINCT ON (date) id
                FROM pl_weather_observation
                ORDER BY date, created_at DESC
            )
        """)
    )

    # 6. Add unique constraint
    op.create_unique_constraint(
        "uq_weather_observation_date",
        "pl_weather_observation",
        ["date"],
    )


def downgrade() -> None:
    """Drop unique constraints, revert NOT NULL."""
    op.drop_constraint(
        "uq_weather_observation_date",
        "pl_weather_observation",
        type_="unique",
    )
    op.drop_constraint(
        "uq_fundamental_article_date_provider",
        "pl_fundamental_article",
        type_="unique",
    )
    op.alter_column(
        "pl_fundamental_article",
        "llm_provider",
        nullable=True,
        existing_type=sa.VARCHAR(50),
    )
