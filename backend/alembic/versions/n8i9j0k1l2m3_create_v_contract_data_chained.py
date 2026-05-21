"""create v_contract_data_chained VIEW (front-month-by-OI continuous series)

Revision ID: n8i9j0k1l2m3
Revises: m7h8i9j0k1l2
Create Date: 2026-05-21

Read-only VIEW over ``pl_contract_data_daily`` exposing a continuous
front-month-by-OI series. Consumed by ``cc-ensemble-compute`` so the
GARCH/long-run features chain across roll boundaries (PR 2 of the
"close the R&D coverage gap" plan).

Convention (matches scripts/contract_resolver.resolve_active_at_date):
    For each ``date``, pick the row with the highest OI (tiebreak: volume desc,
    contract_id asc). Audit-friendly: the underlying ``contract_id`` is exposed
    as a column so backtests can prove which contract produced each row.

Why VIEW (not MATERIALIZED VIEW):
    - Lookback ~600 rows per compute call → unmaterialized SELECT is sub-1s.
    - Zero maintenance (no REFRESH).
    - Frontend / dashboard read path is untouched (still queries
      pl_contract_data_daily directly via contract_id filters).

Idempotent: ``CREATE OR REPLACE VIEW`` in upgrade, ``DROP VIEW IF EXISTS``
in downgrade.
"""

from alembic import op


revision = "n8i9j0k1l2m3"
down_revision = "m7h8i9j0k1l2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE VIEW v_contract_data_chained AS
        SELECT DISTINCT ON (date)
            date,
            display_date,
            contract_id,
            open,
            high,
            low,
            close,
            volume,
            oi,
            implied_volatility,
            stock_us,
            stock_eu_bags60kg,
            com_net_us
        FROM pl_contract_data_daily
        WHERE close IS NOT NULL
        ORDER BY
            date ASC,
            COALESCE(oi, 0) DESC,
            COALESCE(volume, 0) DESC,
            contract_id ASC;
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_contract_data_chained;")
