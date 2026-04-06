"""add display_date column to pl_contract_data_daily

Add a `display_date` column that represents when users see this data
on the dashboard (= next trading day after the session date).

The original `date` column is the session date (when trading happened)
and remains unchanged — it's the source of truth for computations.

Revision ID: 40aad93928c4
Revises: 08724a5d0bce
Create Date: 2026-04-06 16:06:55.675827

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "40aad93928c4"
down_revision: Union[str, Sequence[str], None] = "08724a5d0bce"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add display_date column and populate from trading calendar."""
    # Step 1: Add nullable column
    op.add_column(
        "pl_contract_data_daily",
        sa.Column("display_date", sa.Date(), nullable=True),
    )

    # Step 2: Populate for dates within the calendar range
    op.execute("""
        UPDATE pl_contract_data_daily t
        SET display_date = (
            SELECT MIN(tc.date)
            FROM ref_trading_calendar tc
            JOIN ref_exchange ex ON tc.exchange_id = ex.id
            WHERE ex.code = 'IFEU'
              AND tc.date > t.date
              AND tc.is_trading_day = true
        )
        WHERE t.date >= (
            SELECT MIN(tc2.date)
            FROM ref_trading_calendar tc2
            JOIN ref_exchange ex2 ON tc2.exchange_id = ex2.id
            WHERE ex2.code = 'IFEU'
        );
    """)

    # Step 3: Add index for dashboard queries by display_date
    op.create_index(
        "ix_contract_data_daily_display_date",
        "pl_contract_data_daily",
        ["display_date"],
    )


def downgrade() -> None:
    """Remove display_date column."""
    op.drop_index("ix_contract_data_daily_display_date", "pl_contract_data_daily")
    op.drop_column("pl_contract_data_daily", "display_date")
