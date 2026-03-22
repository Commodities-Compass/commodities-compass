"""drop unused volatility column from pl_derived_indicators

Revision ID: 659baf3947da
Revises: e36e360fb184
Create Date: 2026-03-22 14:17:06.607921

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "659baf3947da"
down_revision: Union[str, Sequence[str], None] = "e36e360fb184"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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
