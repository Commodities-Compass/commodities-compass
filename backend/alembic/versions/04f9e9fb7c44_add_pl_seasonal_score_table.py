"""add pl_seasonal_score table

Revision ID: 04f9e9fb7c44
Revises: 5bf65ef24b63
Create Date: 2026-03-26 13:40:37.235774

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = "04f9e9fb7c44"
down_revision: Union[str, Sequence[str], None] = "5bf65ef24b63"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pl_seasonal_score",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("campaign", sa.VARCHAR(20), nullable=False),
        sa.Column("season_name", sa.VARCHAR(50), nullable=False),
        sa.Column("location_name", sa.VARCHAR(100), nullable=False),
        sa.Column("months_covered", sa.VARCHAR(50), nullable=False),
        sa.Column("start_date", sa.DATE, nullable=False),
        sa.Column("end_date", sa.DATE, nullable=False),
        sa.Column("total_precip_mm", sa.DECIMAL(8, 1)),
        sa.Column("total_et0_mm", sa.DECIMAL(8, 1)),
        sa.Column("cumulative_balance_mm", sa.DECIMAL(8, 1)),
        sa.Column("days_rain", sa.INTEGER),
        sa.Column("days_stress_temp", sa.INTEGER),
        sa.Column("avg_tmax", sa.DECIMAL(4, 1)),
        sa.Column("score", sa.DECIMAL(2, 1), nullable=False),
        sa.Column(
            "computed_at",
            sa.TIMESTAMP,
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "campaign",
            "season_name",
            "location_name",
            name="uq_seasonal_score",
        ),
    )
    op.create_index(
        "ix_seasonal_score_campaign",
        "pl_seasonal_score",
        ["campaign"],
    )


def downgrade() -> None:
    op.drop_index("ix_seasonal_score_campaign")
    op.drop_table("pl_seasonal_score")
