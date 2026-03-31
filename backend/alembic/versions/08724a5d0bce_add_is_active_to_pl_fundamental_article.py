"""add is_active to pl_fundamental_article

Revision ID: 08724a5d0bce
Revises: 6929480a822e
Create Date: 2026-04-01 00:13:35.149472

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "08724a5d0bce"
down_revision: Union[str, Sequence[str], None] = "6929480a822e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add is_active column and backfill openai rows as active."""
    op.add_column(
        "pl_fundamental_article",
        sa.Column("is_active", sa.Boolean(), server_default="false", nullable=False),
    )
    # Backfill: openai/o4-mini is the production provider
    op.execute(
        "UPDATE pl_fundamental_article SET is_active = true"
        " WHERE llm_provider = 'openai'"
    )


def downgrade() -> None:
    """Remove is_active column."""
    op.drop_column("pl_fundamental_article", "is_active")
