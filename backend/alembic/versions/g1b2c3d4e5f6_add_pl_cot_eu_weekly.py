"""add pl_cot_eu_weekly table for ICE COT Europe positioning

Revision ID: g1b2c3d4e5f6
Revises: f0a1b2c3d4e5
Create Date: 2026-05-20

Source: ICE public CSV at
  https://www.theice.com/publicdocs/futures/COTHistYYYY.csv

Filters for "ICE Cocoa Futures - ICE Futures Europe" + FutOnly format.

prod_merc_net and m_money_net are Postgres GENERATED columns — auto-computed,
never written directly. See docs/user-stories/P1-scrapers-stock-cot-eu.md §4.1.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "g1b2c3d4e5f6"
down_revision = "f0a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pl_cot_eu_weekly",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # When ICE published the report (Friday for Tuesday snapshot).
        sa.Column("release_date", sa.DATE(), nullable=False),
        # The Tuesday the report covers.
        sa.Column("report_date", sa.DATE(), nullable=False),
        sa.Column(
            "contract_market",
            sa.VARCHAR(50),
            nullable=False,
            server_default="cocoa",
        ),
        # Commercial: Producer / Merchant / Processor / User
        sa.Column("prod_merc_long", sa.INTEGER(), nullable=True),
        sa.Column("prod_merc_short", sa.INTEGER(), nullable=True),
        sa.Column(
            "prod_merc_net",
            sa.INTEGER(),
            sa.Computed("prod_merc_long - prod_merc_short", persisted=True),
        ),
        # Non-commercial: Managed Money (the R&D signal)
        sa.Column("m_money_long", sa.INTEGER(), nullable=True),
        sa.Column("m_money_short", sa.INTEGER(), nullable=True),
        sa.Column(
            "m_money_net",
            sa.INTEGER(),
            sa.Computed("m_money_long - m_money_short", persisted=True),
        ),
        # Other Reportables + Non-Reportable (audit categories)
        sa.Column("other_rept_long", sa.INTEGER(), nullable=True),
        sa.Column("other_rept_short", sa.INTEGER(), nullable=True),
        sa.Column("non_rept_long", sa.INTEGER(), nullable=True),
        sa.Column("non_rept_short", sa.INTEGER(), nullable=True),
        # Total OI on the report — for %OI normalization downstream
        sa.Column("open_interest", sa.INTEGER(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.func.now()),
        sa.UniqueConstraint("release_date", "contract_market", name="uq_cot_eu_weekly"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_cot_eu_weekly_report_date",
        "pl_cot_eu_weekly",
        ["report_date"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_cot_eu_weekly_report_date", table_name="pl_cot_eu_weekly")
    op.drop_table("pl_cot_eu_weekly")
