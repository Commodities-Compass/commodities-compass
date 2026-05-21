"""add pl_model_artifact (Campaign 5 ensemble artifact registry)

Revision ID: i3d4e5f6g7h8
Revises: h2c3d4e5f6g7
Create Date: 2026-05-21

Source: campaign5_ensemble_v1.0.0/sql/001_create_pl_model_artifact.sql

One BYTEA payload per (algorithm_version, artifact_kind, artifact_name,
training_month). The ensemble pipeline reads from this table at job time,
verifies SHA-256 on every load (fail-loud per rule §0 #1), then deserializes.

Layout per delivery: 14 specialist_model + 14 specialist_hp + 3 long_run
+ 2 tuned_config + 5 canonical_snapshot ≈ 38 rows, ~7-10 MB on disk
before TOAST compression.

Idempotent — re-running yields no changes when the table exists.
"""

from alembic import op


revision = "i3d4e5f6g7h8"
down_revision = "h2c3d4e5f6g7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS pl_model_artifact (
            id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            algorithm_version_id UUID NOT NULL REFERENCES pl_algorithm_version(id),
            artifact_kind        VARCHAR(64) NOT NULL,
            artifact_name        VARCHAR(128) NOT NULL,
            training_month       VARCHAR(7) NULL,
            payload              BYTEA NOT NULL,
            payload_encoding     VARCHAR(16) NOT NULL,
            sha256               CHAR(64) NOT NULL,
            n_bytes              INTEGER NOT NULL,
            fit_train_start      DATE NULL,
            fit_train_end        DATE NULL,
            n_train              INTEGER NULL,
            class_balance        JSONB NULL,
            git_sha              VARCHAR(40) NOT NULL,
            python_version       VARCHAR(20) NOT NULL,
            lib_versions         JSONB NOT NULL,
            created_at           TIMESTAMP NOT NULL DEFAULT now(),
            CONSTRAINT uq_pl_model_artifact
                UNIQUE (algorithm_version_id, artifact_kind, artifact_name, training_month)
        );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_pl_model_artifact_kind
            ON pl_model_artifact (algorithm_version_id, artifact_kind);
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_pl_model_artifact_kind;")
    op.execute("DROP TABLE IF EXISTS pl_model_artifact;")
