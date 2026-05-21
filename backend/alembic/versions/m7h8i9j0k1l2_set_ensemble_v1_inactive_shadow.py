"""set ensemble_v1_softgate_wrapper inactive (Option B shadow mode)

Revision ID: m7h8i9j0k1l2
Revises: l6g7h8i9j0k1
Create Date: 2026-05-21

The R&D-shipped seed migration (l6g7h8i9j0k1) set is_active=TRUE on
ensemble_v1 per day-1-promotion design. But Compass's dashboard backend
(`backend/app/utils/contract_resolver.py:get_active_algorithm_version_id`)
resolves the active algorithm version via the single
``is_active=TRUE`` filter — flipping ensemble_v1 active before the
frontend is adapted would make 4 critical endpoints return HTTP 404 for
every date that doesn't yet have an ensemble row in pl_indicator_daily.

This migration enforces Option B (shadow mode) until the cutover:

  * ensemble_v1_softgate_wrapper.is_active = FALSE
  * compute_enabled stays TRUE so cc-ensemble-compute keeps producing
    rows that we can audit before the bascule.

Legacy v1.0.0 remains is_active=TRUE and continues to drive the dashboard.

To bascule (when frontend supports multi-version OR pl_indicator_daily
ensemble rows are backfilled across all served dates), revert via:

    UPDATE pl_algorithm_version SET is_active = FALSE WHERE name = 'legacy';
    UPDATE pl_algorithm_version SET is_active = TRUE
        WHERE name = 'ensemble_v1_softgate_wrapper';

Idempotent — re-running has no effect once ensemble is inactive.
"""

from alembic import op


revision = "m7h8i9j0k1l2"
down_revision = "l6g7h8i9j0k1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE pl_algorithm_version
        SET is_active = FALSE
        WHERE name = 'ensemble_v1_softgate_wrapper'
          AND version = '1.0.0';
        """
    )


def downgrade() -> None:
    # Atomic flip: deactivate legacy AND activate ensemble in one go. The
    # contract_resolver in `backend/app/utils/contract_resolver.py` uses
    # `scalar_one_or_none()` on `WHERE is_active=TRUE LIMIT 1` — leaving
    # two rows TRUE simultaneously would cause `MultipleResultsFound` and
    # take down the 4 dashboard endpoints we tried to protect with this
    # migration. Asymmetric downgrades are an incident hazard.
    op.execute(
        """
        UPDATE pl_algorithm_version
        SET is_active = FALSE
        WHERE name = 'legacy';
        """
    )
    op.execute(
        """
        UPDATE pl_algorithm_version
        SET is_active = TRUE
        WHERE name = 'ensemble_v1_softgate_wrapper'
          AND version = '1.0.0';
        """
    )
