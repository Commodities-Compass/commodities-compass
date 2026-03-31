"""add harmattan_days to pl_seasonal_score

Revision ID: 6fc0b37d63f0
Revises: 984453591f4a
Create Date: 2026-03-27 15:59:06.612639

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "6fc0b37d63f0"
down_revision: Union[str, Sequence[str], None] = "984453591f4a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "pl_seasonal_score",
        sa.Column("harmattan_days", sa.INTEGER(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("pl_seasonal_score", "harmattan_days")
