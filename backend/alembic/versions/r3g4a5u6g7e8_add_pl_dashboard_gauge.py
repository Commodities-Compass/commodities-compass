"""add pl_dashboard_gauge — technical gauges decoupled from any algorithm

Revision ID: r3g4a5u6g7e8
Revises: q2s3e4r5v6i7
Create Date: 2026-08-18

The five technical gauges served by /indicators-grid (RSI / MACD / %K / ATR /
VOL-OI) were read from ``pl_indicator_daily.*_norm`` — that is, from whichever
ALGORITHM happened to write that row. They would therefore vanish the moment
that algorithm stopped writing, which is precisely what a bascule does.

The gauges describe the market, not a decision. This table gives them their own
home, fed by their own job (``cc-compute-gauges``), with no dependency on
pl_algorithm_version.

Three stages are stored (raw → 5d-SMA score → 252d z-score): the third is what
the gauge plots, the first two make a discrepancy auditable without recomputing
a year of history.

No color zone is stored: RED/ORANGE/GREEN comes from ``test_range``, which is
mutable config. Freezing it here would pin a stale calibration and force a
backfill on every threshold retune — the zone is resolved at read time.

Idempotent (guarded CREATE) so it is safe to re-apply on GCP.
"""

import sqlalchemy as sa
from alembic import op

revision = "r3g4a5u6g7e8"
down_revision = "q2s3e4r5v6i7"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = :name"
        ),
        {"name": name},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    if _has_table("pl_dashboard_gauge"):
        return

    op.create_table(
        "pl_dashboard_gauge",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("date", sa.DATE(), nullable=False),
        sa.Column(
            "contract_id",
            sa.Uuid(),
            sa.ForeignKey("ref_contract.id"),
            nullable=False,
        ),
        # Matches test_range.indicator so the read-time join is plain equality.
        sa.Column("indicator_name", sa.VARCHAR(length=50), nullable=False),
        # Stage 1 — the value straight out of pl_derived_indicators.
        sa.Column("raw_value", sa.DECIMAL(precision=15, scale=6), nullable=True),
        # Stage 2 — 5-day SMA (engine: smoothing.compute_raw_scores).
        sa.Column("score_value", sa.DECIMAL(precision=15, scale=6), nullable=True),
        # Stage 3 — rolling 252d z-score clipped ±10 (engine: rolling_zscore).
        # THIS is what the gauge plots.
        sa.Column("norm_value", sa.DECIMAL(precision=15, scale=6), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "date", "contract_id", "indicator_name", name="uq_dashboard_gauge"
        ),
    )
    op.create_index("ix_dashboard_gauge_date", "pl_dashboard_gauge", ["date"])


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_dashboard_gauge_date")
    op.execute("DROP TABLE IF EXISTS pl_dashboard_gauge")
