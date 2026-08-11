"""create pl_judge_shadow (Campaign 6 judge macro overlay, shadow log)

Revision ID: l7a8b9c0d1e2
Revises: k6f7g8h9i0j1
Create Date: 2026-08-10

Shadow-mode observation log for the ``judge`` v0.1 macro overlay (Layer 3 above
``regime``). One row per (session date, front-month contract, algorithm version):
the base call it received from regime, the LLM verdict, the drift signal and the
fused final decision. ``realized_return`` / ``production_score`` are backfilled
once the horizon closes (README §6 eval, symmetric with pl_regime_shadow).

This table is NEVER read by the dashboard and NEVER touches pl_indicator_daily —
judge advises, never controls, until shadow clears >=30 sessions of eval.

Idempotent (safe re-apply on GCP): guarded by a table-existence check.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision = "l7a8b9c0d1e2"
down_revision = "k6f7g8h9i0j1"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return name in inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if _has_table("pl_judge_shadow"):
        return
    op.create_table(
        "pl_judge_shadow",
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
        # Base call ingested from the underlying algorithm (regime today).
        sa.Column("base_source", sa.VARCHAR(50), nullable=False),
        sa.Column("base_decision", sa.VARCHAR(10), nullable=False),
        sa.Column("base_confidence", sa.DECIMAL(4, 2), nullable=False),
        sa.Column("base_direction_label", sa.VARCHAR(20)),
        # Regime provenance (which pl_regime_shadow row was consumed).
        sa.Column("regime_source_date", sa.DATE(), nullable=False),
        sa.Column("regime", sa.VARCHAR(30), nullable=False),
        sa.Column("specialist", sa.VARCHAR(30), nullable=False),
        sa.Column("prob_up", sa.DECIMAL(6, 4), nullable=False),
        # LLM verdict.
        sa.Column("judge_direction", sa.VARCHAR(10), nullable=False),
        sa.Column("judge_stance", sa.VARCHAR(15), nullable=False),
        sa.Column("judge_confidence", sa.INTEGER(), nullable=False),
        sa.Column("is_anomaly", sa.BOOLEAN(), nullable=False),
        sa.Column("evidence", postgresql.JSONB()),
        sa.Column("drift_summary", sa.TEXT()),
        sa.Column("disconfirming_case", sa.TEXT()),
        sa.Column("key_risk", sa.TEXT()),
        # Drift signal (deterministic).
        sa.Column("weather_series", postgresql.JSONB()),
        sa.Column("weather_delta", sa.DECIMAL(6, 3)),
        sa.Column("drift_notes", postgresql.JSONB()),
        sa.Column("n_days_window", sa.INTEGER(), nullable=False),
        # Fused outcome.
        sa.Column("final_decision", sa.VARCHAR(10), nullable=False),
        sa.Column("changed", sa.BOOLEAN(), nullable=False),
        sa.Column("rationale", sa.TEXT()),
        # Provenance.
        sa.Column("prompt_version", sa.VARCHAR(50), nullable=False),
        sa.Column("model_id", sa.VARCHAR(100), nullable=False),
        # Eval (backfilled by future scoring pass, symmetric with pl_regime_shadow).
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
            name="uq_judge_shadow",
        ),
    )
    op.create_index("ix_judge_shadow_date", "pl_judge_shadow", ["date"])


def downgrade() -> None:
    if _has_table("pl_judge_shadow"):
        op.drop_index("ix_judge_shadow_date", table_name="pl_judge_shadow")
        op.drop_table("pl_judge_shadow")
