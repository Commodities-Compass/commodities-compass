"""add session_type and reason to ref_trading_calendar

Revision ID: a1b2c3d4e5f6
Revises: 659baf3947da
Create Date: 2026-03-24 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "659baf3947da"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = inspect(bind)
    columns = [c["name"] for c in insp.get_columns(table)]
    return column in columns


def upgrade() -> None:
    if not _has_column("ref_trading_calendar", "session_type"):
        op.add_column(
            "ref_trading_calendar",
            sa.Column("session_type", sa.String(20), nullable=True),
        )
    if not _has_column("ref_trading_calendar", "reason"):
        op.add_column(
            "ref_trading_calendar",
            sa.Column("reason", sa.String(100), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("ref_trading_calendar", "reason")
    op.drop_column("ref_trading_calendar", "session_type")
