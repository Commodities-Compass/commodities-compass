"""rename composite_score to conclusion in pl_indicator_daily

Revision ID: 5bf65ef24b63
Revises: a1b2c3d4e5f6
Create Date: 2026-03-25 15:00:56.314652

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "5bf65ef24b63"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "pl_indicator_daily",
        "composite_score",
        new_column_name="conclusion",
    )


def downgrade() -> None:
    op.alter_column(
        "pl_indicator_daily",
        "conclusion",
        new_column_name="composite_score",
    )
