"""temporal config (effective_from) + collapse ensemble v1.1.0 into v1.0.0

Collapses the ensemble back to ONE continuous version (v1.0.0) — the pipeline's
history-spanning reads (YTD, wrapper trailing windows, briefs) assume a single
version, and splitting into v1.1.0 broke them. To keep versioning/provenance WITHOUT
splitting the version, config becomes TEMPORAL (append-only with effective_from):

  - pl_algorithm_config gains ``effective_from DATE`` + ``active BOOLEAN``.
  - Config changes APPEND a new row (effective_from = switch date) instead of UPDATE,
    so the old value is preserved (audit: "alpha_macro was 0.9 until 2026-07-22").
  - Removals APPEND a tombstone row (active=false).
  - VIEW ``v_algorithm_config_current`` exposes the latest active row per param
    (as of today) — the loaders read the view, so runtime picks the current config.

C5-full (the 2026-07-22 retune) is applied to v1.0.0 as effective_from='2026-07-22':
alpha_macro_cap 0.9→0.3, commit_threshold 0.2493→0.15, wrapper_tau_trend 0.03→0.05,
regime-MONITOR OFF (tombstone). v1.0.0's original rows stay (effective_from floor) as
the pre-retune config. v1.1.0 (+ its config/artifacts/today's rows) is dropped.

Revision ID: g2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-07-22
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect

revision: str = "g2b3c4d5e6f7"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ENSEMBLE = "ensemble_v1_softgate_wrapper"
_SWITCH = "2026-07-22"


def _has_column(table: str, column: str) -> bool:
    return column in [c["name"] for c in inspect(op.get_bind()).get_columns(table)]


def _has_constraint(table: str, name: str) -> bool:
    insp = inspect(op.get_bind())
    return name in [c["name"] for c in insp.get_unique_constraints(table)]


def upgrade() -> None:
    # 1) Temporal columns (idempotent). Existing rows → floor date, active.
    if not _has_column("pl_algorithm_config", "effective_from"):
        op.execute(
            "ALTER TABLE pl_algorithm_config "
            "ADD COLUMN effective_from DATE NOT NULL DEFAULT DATE '2000-01-01'"
        )
    if not _has_column("pl_algorithm_config", "active"):
        op.execute(
            "ALTER TABLE pl_algorithm_config "
            "ADD COLUMN active BOOLEAN NOT NULL DEFAULT TRUE"
        )

    # 2) Unique now includes effective_from (append-only per param over time).
    if _has_constraint("pl_algorithm_config", "uq_algorithm_config_param"):
        op.execute(
            "ALTER TABLE pl_algorithm_config DROP CONSTRAINT uq_algorithm_config_param"
        )
    if not _has_constraint("pl_algorithm_config", "uq_algorithm_config_param_eff"):
        op.execute(
            "ALTER TABLE pl_algorithm_config "
            "ADD CONSTRAINT uq_algorithm_config_param_eff "
            "UNIQUE (algorithm_version_id, parameter_name, effective_from)"
        )

    # 3) Current-config VIEW: latest row per param as of today, then keep active ones.
    op.execute(
        """
        CREATE OR REPLACE VIEW v_algorithm_config_current AS
        SELECT latest.* FROM (
            SELECT DISTINCT ON (algorithm_version_id, parameter_name) *
            FROM pl_algorithm_config
            WHERE effective_from <= CURRENT_DATE
            ORDER BY algorithm_version_id, parameter_name, effective_from DESC
        ) latest
        WHERE latest.active
        """
    )

    # 4) Append C5-full (effective 2026-07-22) to v1.0.0. New values as active rows;
    #    regime-MONITOR as a tombstone (active=false) so the current config omits it.
    op.execute(
        f"""
        INSERT INTO pl_algorithm_config
            (id, algorithm_version_id, parameter_name, value, description, effective_from, active)
        SELECT gen_random_uuid(),
               (SELECT id FROM pl_algorithm_version WHERE name = '{_ENSEMBLE}' AND version = '1.0.0'),
               kv.k, kv.v, kv.d, DATE '{_SWITCH}', kv.active
        FROM (VALUES
            ('compass_softgate_alpha_macro_cap', '0.3',  'C5-full retune: de-weight noisy LLM macro (was 0.9)', TRUE),
            ('commit_threshold',                 '0.15', 'C5-full retune: more actionable soft-gate band (was 0.2493)', TRUE),
            ('wrapper_tau_trend',                '0.05', 'C5-full retune: relax over-vetoing trend detector (was 0.03)', TRUE),
            ('compass_regime_monitor_atr_pctl',  '0.80', 'C5-full retune: regime-MONITOR OFF (tombstone) — harmful on corrected data', FALSE)
        ) AS kv(k, v, d, active)
        WHERE NOT EXISTS (
            SELECT 1 FROM pl_algorithm_config c
            WHERE c.algorithm_version_id =
                      (SELECT id FROM pl_algorithm_version WHERE name = '{_ENSEMBLE}' AND version = '1.0.0')
              AND c.parameter_name = kv.k
              AND c.effective_from = DATE '{_SWITCH}'
        )
        """
    )

    # 5) Drop ensemble v1.1.0 entirely (collapse) — delete FK-dependent rows first.
    for tbl in (
        "pl_indicator_daily",
        "pl_orchestrator_decision",
        "pl_specialist_prediction",
        "pl_signal_component",
        "pl_model_artifact",
        "pl_algorithm_config",
    ):
        op.execute(
            f"""
            DELETE FROM {tbl} WHERE algorithm_version_id =
                (SELECT id FROM pl_algorithm_version WHERE name = '{_ENSEMBLE}' AND version = '1.1.0')
            """
        )
    op.execute(
        f"DELETE FROM pl_algorithm_version WHERE name = '{_ENSEMBLE}' AND version = '1.1.0'"
    )


def downgrade() -> None:
    # Best-effort: remove the C5-full temporal rows + view + temporal columns.
    # v1.1.0 is NOT recreated (the collapse is intentional); re-run ensemble-compute if needed.
    op.execute("DROP VIEW IF EXISTS v_algorithm_config_current")
    op.execute(
        f"DELETE FROM pl_algorithm_config WHERE effective_from = DATE '{_SWITCH}' "
        f"AND algorithm_version_id = "
        f"(SELECT id FROM pl_algorithm_version WHERE name = '{_ENSEMBLE}' AND version = '1.0.0')"
    )
    if _has_constraint("pl_algorithm_config", "uq_algorithm_config_param_eff"):
        op.execute(
            "ALTER TABLE pl_algorithm_config DROP CONSTRAINT uq_algorithm_config_param_eff"
        )
    if not _has_constraint("pl_algorithm_config", "uq_algorithm_config_param"):
        op.execute(
            "ALTER TABLE pl_algorithm_config "
            "ADD CONSTRAINT uq_algorithm_config_param UNIQUE (algorithm_version_id, parameter_name)"
        )
    if _has_column("pl_algorithm_config", "active"):
        op.execute("ALTER TABLE pl_algorithm_config DROP COLUMN active")
    if _has_column("pl_algorithm_config", "effective_from"):
        op.execute("ALTER TABLE pl_algorithm_config DROP COLUMN effective_from")
