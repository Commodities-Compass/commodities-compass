"""add diagnostics jsonb to pl_weather_observation

Revision ID: 8f620009140e
Revises: 7daf5377b4df
Create Date: 2026-04-14 15:11:04.071449

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "8f620009140e"
down_revision: Union[str, Sequence[str], None] = "7daf5377b4df"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "pl_weather_observation",
        sa.Column("diagnostics", sa.dialects.postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("pl_weather_observation", "diagnostics")
