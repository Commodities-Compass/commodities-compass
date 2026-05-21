"""add pl_specialist_prediction (per-specialist daily vote audit)

Revision ID: j4e5f6g7h8i9
Revises: i3d4e5f6g7h8
Create Date: 2026-05-21

Source: campaign5_ensemble_v1.0.0/sql/002_create_pl_specialist_prediction.sql

One row per (date, contract_id, algorithm_version_id, specialist_name).
Feeds the wrapper's cluster-dispersion detector and Phase 5 post-hoc
analysis ("which specialists were wrong on day X?"). `forward_return_6d`
is back-filled once the h=6 horizon expires.

Idempotent.
"""

from alembic import op


revision = "j4e5f6g7h8i9"
down_revision = "i3d4e5f6g7h8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS pl_specialist_prediction (
            id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            date                 DATE NOT NULL,
            contract_id          UUID NOT NULL REFERENCES ref_contract(id),
            algorithm_version_id UUID NOT NULL REFERENCES pl_algorithm_version(id),
            specialist_name      VARCHAR(64) NOT NULL,
            window_months        SMALLINT NOT NULL,
            pred                 VARCHAR(10) NOT NULL,
            n_features_used      SMALLINT NULL,
            forward_return_6d    NUMERIC(15, 6) NULL,
            created_at           TIMESTAMP NOT NULL DEFAULT now(),
            CONSTRAINT uq_specialist_prediction
                UNIQUE (date, contract_id, algorithm_version_id, specialist_name)
        );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_specialist_prediction_date_version
            ON pl_specialist_prediction (date, algorithm_version_id);
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_specialist_prediction_date_version;")
    op.execute("DROP TABLE IF EXISTS pl_specialist_prediction;")
