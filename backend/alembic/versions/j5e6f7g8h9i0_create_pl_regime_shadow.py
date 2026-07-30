"""create pl_regime_shadow (Campaign 6 regime shadow log)

Revision ID: j5e6f7g8h9i0
Revises: i4d5e6f7g8h9
Create Date: 2026-07-29

Shadow-mode observation log for the INERT regime algorithm (Campaign 6). One row
per (session date, front-month contract, algorithm version): the routed decision
+ regime/specialist + prob_up + the causal router diagnostics at decide-time.
``realized_return`` / ``production_score`` are backfilled once the J+1 horizon
closes (README §6 eval). This table is NEVER read by the dashboard and NEVER
touches pl_indicator_daily.decision — the algo is inert until shadow clears.

Idempotent (safe re-apply on GCP): guarded by a table-existence check.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "j5e6f7g8h9i0"
down_revision = "i4d5e6f7g8h9"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return name in inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if _has_table("pl_regime_shadow"):
        return
    op.create_table(
        "pl_regime_shadow",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("date", sa.DATE(), nullable=False),
        sa.Column(
            "contract_id",
            sa.Uuid(),
            sa.ForeignKey("ref_contract.id"),
            nullable=False,
        ),
        sa.Column(
            "algorithm_version_id",
            sa.Uuid(),
            sa.ForeignKey("pl_algorithm_version.id"),
            nullable=False,
        ),
        sa.Column("decision", sa.VARCHAR(10), nullable=False),
        sa.Column("regime", sa.VARCHAR(20), nullable=False),
        sa.Column("specialist", sa.VARCHAR(20), nullable=False),
        sa.Column("prob_up", sa.DECIMAL(6, 4), nullable=False),
        sa.Column("state_rsi_14d", sa.DECIMAL(15, 6)),
        sa.Column("state_atr_14d", sa.DECIMAL(15, 6)),
        sa.Column("state_trend20", sa.DECIMAL(15, 6)),
        sa.Column("realized_return", sa.DECIMAL(15, 6)),
        sa.Column("production_score", sa.DECIMAL(15, 6)),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "date",
            "contract_id",
            "algorithm_version_id",
            name="uq_regime_shadow",
        ),
    )
    op.create_index("ix_regime_shadow_date", "pl_regime_shadow", ["date"])


def downgrade() -> None:
    if _has_table("pl_regime_shadow"):
        op.drop_index("ix_regime_shadow_date", table_name="pl_regime_shadow")
        op.drop_table("pl_regime_shadow")
