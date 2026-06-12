"""enable trend-conflict + regime-MONITOR + alpha_macro cap (config-as-data) + regime_monitor_fired column

Activates three Compass levers on the ensemble version, all config-as-data so they are
tunable / disable-able without a redeploy:
  - wrapper_use_trend_conflict 0 -> 1  (FIX2: re-enable the trend-conflict detector; +1.69 on 6mo)
  - compass_regime_monitor_atr_pctl = 0.80  (override commit->MONITOR in top-vol regimes; EV break-even ~81% acc)
  - compass_softgate_alpha_macro_cap = 0.9  (cap alpha_macro<1 so contrarian specialists are never zeroed)
Plus a new pl_orchestrator_decision.regime_monitor_fired audit column.

Idempotent for safe GCP re-application (column guarded by _has_column; config rows by NOT EXISTS / scoped UPDATE).

Revision ID: e7f8a9b0c1d2
Revises: b4d9e1f2a3c7
Create Date: 2026-06-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, Sequence[str], None] = "b4d9e1f2a3c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ENSEMBLE = "ensemble_v1_softgate_wrapper"


def _has_column(table: str, column: str) -> bool:
    insp = inspect(op.get_bind())
    return column in [c["name"] for c in insp.get_columns(table)]


def upgrade() -> None:
    # 1) Audit column for the regime-MONITOR lever (idempotent).
    if not _has_column("pl_orchestrator_decision", "regime_monitor_fired"):
        op.add_column(
            "pl_orchestrator_decision",
            sa.Column(
                "regime_monitor_fired",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )

    # 2) Enable the trend-conflict detector (FIX2). _build_diagnostics now reads the
    #    real fired_trend from the wrapper, so the former fail-loud guard is removed.
    op.execute(
        f"""
        UPDATE pl_algorithm_config SET
            value = '1',
            description = 'TPW-001 detector B ACTIVE (trend-conflict; enabled 2026-06)'
        WHERE parameter_name = 'wrapper_use_trend_conflict'
          AND algorithm_version_id = (
              SELECT id FROM pl_algorithm_version WHERE name = '{_ENSEMBLE}'
          )
        """
    )

    # 3) Compass levers — config-as-data, idempotent (absent row would mean lever OFF).
    op.execute(
        f"""
        INSERT INTO pl_algorithm_config (id, algorithm_version_id, parameter_name, value, description)
        SELECT gen_random_uuid(), v.id, kv.k, kv.v, kv.d
        FROM pl_algorithm_version v,
             (VALUES
                ('compass_regime_monitor_atr_pctl', '0.80',
                 'regime-MONITOR: override commit->MONITOR when atr%-pctl(252d) exceeds this (EV break-even ~81% dir-acc)'),
                ('compass_softgate_alpha_macro_cap', '0.9',
                 'cap on soft-gate alpha_macro so a specialist voting against macro is down-weighted, never zeroed')
             ) AS kv(k, v, d)
        WHERE v.name = '{_ENSEMBLE}'
          AND NOT EXISTS (
              SELECT 1 FROM pl_algorithm_config c
              WHERE c.algorithm_version_id = v.id AND c.parameter_name = kv.k
          )
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DELETE FROM pl_algorithm_config
        WHERE parameter_name IN (
            'compass_regime_monitor_atr_pctl', 'compass_softgate_alpha_macro_cap'
        )
          AND algorithm_version_id = (
              SELECT id FROM pl_algorithm_version WHERE name = '{_ENSEMBLE}'
          )
        """
    )
    op.execute(
        f"""
        UPDATE pl_algorithm_config SET
            value = '0',
            description = 'TPW-001 detector B INACTIVE'
        WHERE parameter_name = 'wrapper_use_trend_conflict'
          AND algorithm_version_id = (
              SELECT id FROM pl_algorithm_version WHERE name = '{_ENSEMBLE}'
          )
        """
    )
    if _has_column("pl_orchestrator_decision", "regime_monitor_fired"):
        op.drop_column("pl_orchestrator_decision", "regime_monitor_fired")
