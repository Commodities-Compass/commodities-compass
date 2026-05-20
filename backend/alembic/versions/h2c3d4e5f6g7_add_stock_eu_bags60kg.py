"""add stock_eu_bags60kg to pl_contract_data_daily

Revision ID: h2c3d4e5f6g7
Revises: g1b2c3d4e5f6
Create Date: 2026-05-20

Adds the column populated by barchart_stocks_eu_scraper (ICE Europe
certified cocoa stocks, in 60kg bags). Native unit on Barchart cmdty —
no conversion at write time.
"""

from alembic import op
import sqlalchemy as sa

revision = "h2c3d4e5f6g7"
down_revision = "g1b2c3d4e5f6"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :column"
        ),
        {"table": table, "column": column},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    if not _has_column("pl_contract_data_daily", "stock_eu_bags60kg"):
        op.add_column(
            "pl_contract_data_daily",
            sa.Column(
                "stock_eu_bags60kg",
                sa.DECIMAL(precision=15, scale=6),
                nullable=True,
            ),
        )


def downgrade() -> None:
    if _has_column("pl_contract_data_daily", "stock_eu_bags60kg"):
        op.drop_column("pl_contract_data_daily", "stock_eu_bags60kg")
