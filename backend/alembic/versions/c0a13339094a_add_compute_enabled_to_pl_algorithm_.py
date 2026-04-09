"""add compute_enabled to pl_algorithm_version

Revision ID: c0a13339094a
Revises: a7b8c9d0e1f2
Create Date: 2026-04-09 10:47:08.208758

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c0a13339094a"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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
    if not _has_column("pl_algorithm_version", "compute_enabled"):
        op.add_column(
            "pl_algorithm_version",
            sa.Column(
                "compute_enabled", sa.Boolean(), nullable=False, server_default="false"
            ),
        )
    # Existing rows with is_active=True should also be compute_enabled
    op.execute(
        "UPDATE pl_algorithm_version SET compute_enabled = true WHERE is_active = true"
    )


def downgrade() -> None:
    if _has_column("pl_algorithm_version", "compute_enabled"):
        op.drop_column("pl_algorithm_version", "compute_enabled")
