"""add confidence_rationale to pl_indicator_daily

Carries the short editorial explanation the LLM produces alongside the
1-5 confidence score (e.g. "Tech + macro baissiers, stocks neutres, climat
NUANCE."). Rendered next to the score in the daily brief Section I so the
podcast can voice which market pillars back the decision and which
slightly temper it.

Revision ID: 37f66a435891
Revises: r2m3n4o5p6q7
Create Date: 2026-06-03 14:16:18.577487

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "37f66a435891"
down_revision: Union[str, Sequence[str], None] = "r2m3n4o5p6q7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = inspect(bind)
    columns = [c["name"] for c in insp.get_columns(table)]
    return column in columns


def upgrade() -> None:
    """Add confidence_rationale column. Idempotent for safe GCP re-application."""
    if not _has_column("pl_indicator_daily", "confidence_rationale"):
        op.add_column(
            "pl_indicator_daily",
            sa.Column("confidence_rationale", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    if _has_column("pl_indicator_daily", "confidence_rationale"):
        op.drop_column("pl_indicator_daily", "confidence_rationale")
