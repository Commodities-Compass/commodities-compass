"""add is_roll_boundary to pl_derived_indicators

Revision ID: i4d5e6f7g8h9
Revises: h3c4d5e6f7g8
Create Date: 2026-07-28

Contract-roll contamination flag (option (b), C5 retrain handoff §3.7). True on the
first row of each new front-month contract in the chained series (the splice row,
where the continuous close steps by the calendar spread). Return-based indicators
(RSI/ATR/daily_return) neutralize the phantom jump on these rows; the flag is
persisted so R&D can exclude roll rows from training and the ensemble wrapper can
stay cautious near rolls.

Idempotent (safe re-apply on GCP): guarded by _has_column. NOT NULL DEFAULT FALSE
back-fills every existing row to False (correct — the flag is recomputed on the next
`compute-indicators --full`).
"""

from alembic import op
from sqlalchemy import inspect

revision = "i4d5e6f7g8h9"
down_revision = "h3c4d5e6f7g8"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    return column in [c["name"] for c in inspect(op.get_bind()).get_columns(table)]


def upgrade() -> None:
    if not _has_column("pl_derived_indicators", "is_roll_boundary"):
        op.execute(
            "ALTER TABLE pl_derived_indicators "
            "ADD COLUMN is_roll_boundary BOOLEAN NOT NULL DEFAULT FALSE"
        )


def downgrade() -> None:
    if _has_column("pl_derived_indicators", "is_roll_boundary"):
        op.execute("ALTER TABLE pl_derived_indicators DROP COLUMN is_roll_boundary")
