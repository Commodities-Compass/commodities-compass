"""add pl_orchestrator_decision (soft-gate + wrapper audit trail)

Revision ID: k5f6g7h8i9j0
Revises: j4e5f6g7h8i9
Create Date: 2026-05-21

Source: campaign5_ensemble_v1.0.0/sql/003_create_pl_orchestrator_decision.sql

One row per (date, contract_id, algorithm_version_id). Captures both
decision layers: the raw soft-gate (`soft_gate_decision`) and the final
wrapped output (`decision_wrapped`) that `pl_indicator_daily` mirrors.

Every diagnostic column (running_acc_5d, realized_return_5d, …) is
NULLABLE so day-1 / data-edge cases write NULL rather than the silent 0.0
placeholder that rule §0 #3 (pipeline-continuity) forbids.

Idempotent.
"""

from alembic import op


revision = "k5f6g7h8i9j0"
down_revision = "j4e5f6g7h8i9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS pl_orchestrator_decision (
            id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            date                     DATE NOT NULL,
            contract_id              UUID NOT NULL REFERENCES ref_contract(id),
            algorithm_version_id     UUID NOT NULL REFERENCES pl_algorithm_version(id),
            soft_gate_decision       VARCHAR(10) NOT NULL,
            net_score                NUMERIC(15, 6) NOT NULL,
            weights_sum              NUMERIC(15, 6) NOT NULL,
            n_committed_specialists  SMALLINT NOT NULL,
            decision_wrapped         VARCHAR(10) NOT NULL,
            wrapper_active           BOOLEAN NOT NULL,
            fired_running_acc        BOOLEAN NOT NULL,
            fired_trend              BOOLEAN NOT NULL,
            fired_dispersion         BOOLEAN NOT NULL,
            fired_three_way          BOOLEAN NOT NULL,
            running_acc_5d           NUMERIC(8, 6) NULL,
            realized_return_5d       NUMERIC(15, 6) NULL,
            winter_vote_signed       SMALLINT NULL,
            spring_vote_signed       SMALLINT NULL,
            macro_direction          SMALLINT NULL,
            macro_surprise           NUMERIC(8, 6) NULL,
            macro_half_life_days     SMALLINT NULL,
            anomaly_score_z          NUMERIC(15, 6) NULL,
            prior_open               NUMERIC(8, 6) NULL,
            prior_hedge              NUMERIC(8, 6) NULL,
            prior_monitor            NUMERIC(8, 6) NULL,
            created_at               TIMESTAMP NOT NULL DEFAULT now(),
            CONSTRAINT uq_orchestrator_decision
                UNIQUE (date, contract_id, algorithm_version_id)
        );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_orchestrator_decision_date_version
            ON pl_orchestrator_decision (date, algorithm_version_id);
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_orchestrator_decision_date_version;")
    op.execute("DROP TABLE IF EXISTS pl_orchestrator_decision;")
