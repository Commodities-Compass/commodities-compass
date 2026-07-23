"""intraday alerts schema — 3 tables + seed 2 price rules

Revision ID: h3c4d5e6f7g8
Revises: g2b3c4d5e6f7
Create Date: 2026-07-23

Tables for the intraday threshold alerts feature (cc-intraday-monitor):
  - pl_contract_data_intraday : append-only delayed price observations
  - ref_alert_rule            : alert rule definitions (config-as-data)
  - aud_alert_event           : fired-alert journal + dedup guard

Dedup invariant: UNIQUE(rule_id, session_date, crossing_seq) on aud_alert_event
makes first-cross-only idempotent at the data level (ON CONFLICT DO NOTHING).

See docs/user-stories/P1-intraday-threshold-alerts-telegram.md §5.1.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "h3c4d5e6f7g8"
down_revision = "g2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Intraday price observations (append-only, pipeline domain)
    op.create_table(
        "pl_contract_data_intraday",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "contract_id",
            UUID(as_uuid=True),
            sa.ForeignKey("ref_contract.id"),
            nullable=False,
        ),
        # London trading session the observation belongs to.
        sa.Column("session_date", sa.DATE(), nullable=False),
        # When the scrape happened (UTC). Distinct from Barchart's tradeTime.
        sa.Column("observed_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("last_price", sa.DECIMAL(15, 6), nullable=False),
        # Barchart raw.tradeTime — last trade timestamp, for staleness checks.
        sa.Column("trade_time", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "source",
            sa.VARCHAR(30),
            nullable=False,
            server_default="barchart-delayed",
        ),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "contract_id", "observed_at", name="uq_contract_data_intraday"
        ),
        if_not_exists=True,
    )
    op.create_index(
        "ix_contract_data_intraday_session",
        "pl_contract_data_intraday",
        ["contract_id", "session_date", sa.text("observed_at DESC")],
        if_not_exists=True,
    )

    # 2. Alert rules (config-as-data, reference domain)
    op.create_table(
        "ref_alert_rule",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("rule_key", sa.VARCHAR(50), nullable=False, unique=True),
        sa.Column(
            "commodity_code",
            sa.VARCHAR(20),
            nullable=False,
            server_default="COCOA_LDN",
        ),
        sa.Column("metric_column", sa.VARCHAR(30), nullable=False),
        sa.Column("level_column", sa.VARCHAR(30), nullable=False),
        sa.Column("level_label", sa.VARCHAR(40), nullable=False),
        sa.Column("comparator", sa.VARCHAR(10), nullable=False),
        sa.Column("direction", sa.VARCHAR(10), nullable=False),
        sa.Column("severity", sa.VARCHAR(10), nullable=False, server_default="warning"),
        sa.Column(
            "message_template_key",
            sa.VARCHAR(40),
            nullable=False,
            server_default="invalidation_v1",
        ),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "comparator IN ('below', 'above')", name="ck_alert_rule_comparator"
        ),
        if_not_exists=True,
    )

    # 3. Fired-alert journal + dedup (append-only, audit domain)
    op.create_table(
        "aud_alert_event",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "rule_id",
            UUID(as_uuid=True),
            sa.ForeignKey("ref_alert_rule.id"),
            nullable=False,
        ),
        sa.Column(
            "contract_id",
            UUID(as_uuid=True),
            sa.ForeignKey("ref_contract.id"),
            nullable=False,
        ),
        sa.Column("session_date", sa.DATE(), nullable=False),
        # MVP: always 1 (first-cross-only). Re-arm/multi-fire = P2.
        sa.Column("crossing_seq", sa.INTEGER(), nullable=False, server_default="1"),
        sa.Column("level_value", sa.DECIMAL(15, 6), nullable=False),
        sa.Column("observed_price", sa.DECIMAL(15, 6), nullable=False),
        sa.Column("observed_at", sa.TIMESTAMP(timezone=True), nullable=False),
        # OPEN/HEDGE/MONITOR at fire time — message context, not a lookup key.
        sa.Column("signal_decision", sa.VARCHAR(10), nullable=True),
        sa.Column("channel", sa.VARCHAR(20), nullable=False),
        sa.Column(
            "delivery_status",
            sa.VARCHAR(20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("provider_message_id", sa.VARCHAR(60), nullable=True),
        sa.Column("payload", JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "rule_id", "session_date", "crossing_seq", name="uq_alert_event_dedup"
        ),
        if_not_exists=True,
    )
    op.create_index(
        "ix_alert_event_session_date",
        "aud_alert_event",
        ["session_date"],
        if_not_exists=True,
    )

    # Seed the 2 MVP price rules (idempotent on rule_key).
    op.execute(
        """
        INSERT INTO ref_alert_rule
            (rule_key, metric_column, level_column, level_label, comparator, direction)
        VALUES
            ('close_below_s1', 'close', 's1', 'SUPPORT 1', 'below', 'bearish'),
            ('close_above_r1', 'close', 'r1', 'RESISTANCE 1', 'above', 'bullish')
        ON CONFLICT (rule_key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_alert_event_session_date", table_name="aud_alert_event")
    op.drop_table("aud_alert_event")
    op.drop_table("ref_alert_rule")
    op.drop_index(
        "ix_contract_data_intraday_session", table_name="pl_contract_data_intraday"
    )
    op.drop_table("pl_contract_data_intraday")
