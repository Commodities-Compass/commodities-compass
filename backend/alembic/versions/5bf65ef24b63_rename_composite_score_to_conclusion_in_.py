"""rename composite_score to conclusion in pl_indicator_daily

Revision ID: 5bf65ef24b63
Revises: a1b2c3d4e5f6
Create Date: 2026-03-25 15:00:56.314652

"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "5bf65ef24b63"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = inspect(bind)
    columns = [c["name"] for c in insp.get_columns(table)]
    return column in columns


def upgrade() -> None:
    if _has_column("pl_indicator_daily", "composite_score"):
        op.alter_column(
            "pl_indicator_daily",
            "composite_score",
            new_column_name="conclusion",
        )


def downgrade() -> None:
    if _has_column("pl_indicator_daily", "conclusion"):
        op.alter_column(
            "pl_indicator_daily",
            "conclusion",
            new_column_name="composite_score",
        )
