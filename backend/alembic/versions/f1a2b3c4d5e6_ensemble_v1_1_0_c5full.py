"""ensemble v1.1.0 (C5-full retune) — new version row + config, go-forward only

Ships the C5-full retune as a NEW ensemble version (v1.1.0), leaving v1.0.0 and ALL its
historical rows FROZEN (decisions/briefs/podcasts untouched — the dashboard reads
pl_indicator_daily, never recomputed here). v1.1.0 is written only for new sessions
going forward; the dashboard resolver serves the newest ensemble version that HAS a row
per date (v1.1.0 forward, v1.0.0 historical).

Config deltas vs v1.0.0 (all config-as-data):
  - compass_softgate_alpha_macro_cap  0.9  -> 0.3   (de-weight noisy LLM macro signal)
  - commit_threshold                  0.2493 -> 0.15 (now wired from config; more actionable)
  - wrapper_tau_trend                 0.03 -> 0.05  (trend detector was over-vetoing)
  - compass_regime_monitor_atr_pctl   OMITTED       (absent row => regime-MONITOR lever OFF)
  All other wrapper_* / cluster_* / dispersion-release rows copied unchanged.

No is_active / compute_enabled changes (mirrors v1.0.0 flags): version selection is by
newest-created ensemble version, not the is_active flag, so get_active_algorithm_version_id
is undisturbed. Idempotent (NOT EXISTS guards) for safe GCP re-application.

Revision ID: f1a2b3c4d5e6
Revises: d5e6f7a8b9c0
Create Date: 2026-07-22
"""

from typing import Sequence, Union

from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ENSEMBLE = "ensemble_v1_softgate_wrapper"
_V_OLD = "1.0.0"
_V_NEW = "1.1.0"
_DESC = (
    "C5-full retune (2026-07-22): alpha_macro_cap 0.3, commit_threshold 0.15, "
    "regime-MONITOR OFF, tau_trend 0.05. First version computed on corrected indicators "
    "(post macroeco fan-out fix). Go-forward only; v1.0.0 frozen for historical dates."
)


def upgrade() -> None:
    # 1) New version row — clone v1.0.0's flags/horizon, bump version, new description.
    op.execute(
        f"""
        INSERT INTO pl_algorithm_version
            (id, name, version, horizon, is_active, description, compute_enabled)
        SELECT gen_random_uuid(), name, '{_V_NEW}', horizon, is_active,
               '{_DESC}', compute_enabled
        FROM pl_algorithm_version
        WHERE name = '{_ENSEMBLE}' AND version = '{_V_OLD}'
          AND NOT EXISTS (
              SELECT 1 FROM pl_algorithm_version
              WHERE name = '{_ENSEMBLE}' AND version = '{_V_NEW}'
          )
        """
    )

    # 2) Copy v1.0.0 config rows -> v1.1.0 with C5-full overrides; OMIT the regime lever
    #    (absent row => OFF). Idempotent per parameter_name.
    op.execute(
        f"""
        INSERT INTO pl_algorithm_config (id, algorithm_version_id, parameter_name, value, description)
        SELECT gen_random_uuid(),
               (SELECT id FROM pl_algorithm_version WHERE name = '{_ENSEMBLE}' AND version = '{_V_NEW}'),
               src.parameter_name,
               CASE src.parameter_name
                   WHEN 'wrapper_tau_trend'                 THEN '0.05'
                   WHEN 'compass_softgate_alpha_macro_cap'  THEN '0.3'
                   WHEN 'commit_threshold'                  THEN '0.15'
                   ELSE src.value
               END,
               src.description
        FROM pl_algorithm_config src
        WHERE src.algorithm_version_id =
                  (SELECT id FROM pl_algorithm_version WHERE name = '{_ENSEMBLE}' AND version = '{_V_OLD}')
          AND src.parameter_name <> 'compass_regime_monitor_atr_pctl'
          AND NOT EXISTS (
              SELECT 1 FROM pl_algorithm_config c
              WHERE c.algorithm_version_id =
                        (SELECT id FROM pl_algorithm_version WHERE name = '{_ENSEMBLE}' AND version = '{_V_NEW}')
                AND c.parameter_name = src.parameter_name
          )
        """
    )

    # 3) v1.1.0 is a CONFIG-only variant of v1.0.0 — same 14 specialist models. Copy the
    #    frozen model artifacts (BYTEA) so v1.1.0 is self-contained (DBArtifactLoader keys
    #    on algorithm_version_id). Server-side INSERT..SELECT, idempotent on the unique
    #    (algorithm_version_id, artifact_kind, artifact_name, training_month).
    op.execute(
        f"""
        INSERT INTO pl_model_artifact
            (id, algorithm_version_id, artifact_kind, artifact_name, training_month,
             payload, payload_encoding, sha256, n_bytes, fit_train_start, fit_train_end,
             n_train, class_balance, git_sha, python_version, lib_versions)
        SELECT gen_random_uuid(),
               (SELECT id FROM pl_algorithm_version WHERE name = '{_ENSEMBLE}' AND version = '{_V_NEW}'),
               src.artifact_kind, src.artifact_name, src.training_month,
               src.payload, src.payload_encoding, src.sha256, src.n_bytes,
               src.fit_train_start, src.fit_train_end, src.n_train, src.class_balance,
               src.git_sha, src.python_version, src.lib_versions
        FROM pl_model_artifact src
        WHERE src.algorithm_version_id =
                  (SELECT id FROM pl_algorithm_version WHERE name = '{_ENSEMBLE}' AND version = '{_V_OLD}')
          AND NOT EXISTS (
              SELECT 1 FROM pl_model_artifact d
              WHERE d.algorithm_version_id =
                        (SELECT id FROM pl_algorithm_version WHERE name = '{_ENSEMBLE}' AND version = '{_V_NEW}')
                AND d.artifact_kind = src.artifact_kind
                AND d.artifact_name = src.artifact_name
                AND d.training_month IS NOT DISTINCT FROM src.training_month
          )
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DELETE FROM pl_model_artifact
        WHERE algorithm_version_id =
            (SELECT id FROM pl_algorithm_version WHERE name = '{_ENSEMBLE}' AND version = '{_V_NEW}')
        """
    )
    op.execute(
        f"""
        DELETE FROM pl_algorithm_config
        WHERE algorithm_version_id =
            (SELECT id FROM pl_algorithm_version WHERE name = '{_ENSEMBLE}' AND version = '{_V_NEW}')
        """
    )
    op.execute(
        f"DELETE FROM pl_algorithm_version WHERE name = '{_ENSEMBLE}' AND version = '{_V_NEW}'"
    )
