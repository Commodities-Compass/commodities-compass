"""add pipeline query indexes

Revision ID: 6d4eef12be0c
Revises: 5bf65ef24b63
Create Date: 2026-03-26 20:20:00.756450

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "6d4eef12be0c"
down_revision: Union[str, Sequence[str], None] = "5bf65ef24b63"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_indicator_daily_algo_date",
        "pl_indicator_daily",
        ["algorithm_version_id", sa.text("date DESC")],
        if_not_exists=True,
    )
    op.create_index(
        "ix_indicator_daily_contract_date",
        "pl_indicator_daily",
        ["contract_id", "date"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_signal_component_lookup",
        "pl_signal_component",
        ["contract_id", "date", "indicator_name"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_signal_component_lookup", table_name="pl_signal_component")
    op.drop_index("ix_indicator_daily_contract_date", table_name="pl_indicator_daily")
    op.drop_index("ix_indicator_daily_algo_date", table_name="pl_indicator_daily")
