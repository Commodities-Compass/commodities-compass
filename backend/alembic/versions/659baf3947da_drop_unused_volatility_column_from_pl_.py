"""drop unused volatility column from pl_derived_indicators

Revision ID: 659baf3947da
Revises: e36e360fb184
Create Date: 2026-03-22 14:17:06.607921

"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "659baf3947da"
down_revision: Union[str, Sequence[str], None] = "e36e360fb184"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = inspect(bind)
    columns = [c["name"] for c in insp.get_columns(table)]
    return column in columns


def upgrade() -> None:
    if _has_column("pl_derived_indicators", "volatility"):
        op.drop_column("pl_derived_indicators", "volatility")


def downgrade() -> None:
    op.add_column(
        "pl_derived_indicators",
        sa.Column(
            "volatility",
            sa.NUMERIC(precision=15, scale=6),
            autoincrement=False,
            nullable=True,
        ),
    )
