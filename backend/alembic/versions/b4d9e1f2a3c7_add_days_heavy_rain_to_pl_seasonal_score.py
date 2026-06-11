"""add days_heavy_rain to pl_seasonal_score

Symmetric excess-water counterpart to harmattan_days. Counts days with
precip > HEAVY_RAIN_MM_DAY (acute black-pod / waterlogging signal), consumed
by compute_score() in rainy seasons. Nullable: rows computed before this
feature legitimately carry no value (NULL means "not computed", not 0).

Revision ID: b4d9e1f2a3c7
Revises: 37f66a435891
Create Date: 2026-06-11 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4d9e1f2a3c7"
down_revision: Union[str, Sequence[str], None] = "37f66a435891"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    """Idempotency guard — safe to re-apply on GCP."""
    inspector = sa.inspect(op.get_bind())
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    """Upgrade schema."""
    if not _has_column("pl_seasonal_score", "days_heavy_rain"):
        op.add_column(
            "pl_seasonal_score",
            sa.Column("days_heavy_rain", sa.INTEGER(), nullable=True),
        )


def downgrade() -> None:
    """Downgrade schema."""
    if _has_column("pl_seasonal_score", "days_heavy_rain"):
        op.drop_column("pl_seasonal_score", "days_heavy_rain")
