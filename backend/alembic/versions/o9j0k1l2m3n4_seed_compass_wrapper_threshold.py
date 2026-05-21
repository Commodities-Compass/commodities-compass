"""seed compass_wrapper_dispersion_with_acc_threshold

Revision ID: o9j0k1l2m3n4
Revises: n8i9j0k1l2m3
Create Date: 2026-05-22

The Compass-side override of the R&D transition wrapper introduces an
AND-gated release of the cluster_dispersion veto (see
``backend/scripts/ensemble_compute/compass_wrapper.py``).

Per ``north-star-alignment.md`` rule #4 (config as data, not code), the
release threshold must live in ``pl_algorithm_config`` so it can be
A/B-tested or seasonally tuned without redeploying.

Seeds a single row keyed to the ``ensemble_v1_softgate_wrapper`` version:

    parameter_name = 'compass_wrapper_dispersion_with_acc_threshold'
    value          = '0.60'

Default value matches the locally-validated tuning point (2026-05-21
backfill: wrapper coverage 48.9%, accuracy 75.7% on 88 dates).

Idempotent — re-applying yields no changes (NOT EXISTS guard).
"""

from alembic import op


revision = "o9j0k1l2m3n4"
down_revision = "n8i9j0k1l2m3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO pl_algorithm_config (id, algorithm_version_id, parameter_name, value, description)
        SELECT gen_random_uuid(),
               v.id,
               'compass_wrapper_dispersion_with_acc_threshold',
               '0.60',
               'Compass override: release dispersion-only veto when running_acc_5d >= this. NaN running_acc is default-allow.'
        FROM pl_algorithm_version v
        WHERE v.name = 'ensemble_v1_softgate_wrapper'
          AND v.version = '1.0.0'
          AND NOT EXISTS (
              SELECT 1 FROM pl_algorithm_config c
              WHERE c.algorithm_version_id = v.id
                AND c.parameter_name = 'compass_wrapper_dispersion_with_acc_threshold'
          );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM pl_algorithm_config
        WHERE parameter_name = 'compass_wrapper_dispersion_with_acc_threshold'
          AND algorithm_version_id IN (
              SELECT id FROM pl_algorithm_version
              WHERE name = 'ensemble_v1_softgate_wrapper' AND version = '1.0.0'
          );
        """
    )
