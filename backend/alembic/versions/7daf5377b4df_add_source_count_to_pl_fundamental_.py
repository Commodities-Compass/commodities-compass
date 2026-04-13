"""add source_count to pl_fundamental_article

Revision ID: 7daf5377b4df
Revises: c0a13339094a
Create Date: 2026-04-13 10:58:02.410086

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7daf5377b4df"
down_revision: Union[str, Sequence[str], None] = "c0a13339094a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "pl_fundamental_article",
        sa.Column("source_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "pl_fundamental_article",
        sa.Column("total_sources", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("pl_fundamental_article", "total_sources")
    op.drop_column("pl_fundamental_article", "source_count")
