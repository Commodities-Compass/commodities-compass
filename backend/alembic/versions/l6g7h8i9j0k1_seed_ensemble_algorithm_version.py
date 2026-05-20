"""seed ensemble_v1_softgate_wrapper + 22 algorithm_config rows

Revision ID: l6g7h8i9j0k1
Revises: k5f6g7h8i9j0
Create Date: 2026-05-21

Source: campaign5_ensemble_v1.0.0/sql/004_seed_pl_algorithm_version.sql

Day-1 promotion (per CAMPAIGN_5_PROD_DEPLOYMENT.md): `is_active=TRUE`
and `compute_enabled=TRUE` directly, no parallel run.

Per-specialist HPs are NOT seeded here — they live in pl_model_artifact
(BYTEA) and are loaded at runtime by ensemble.artifact_io.DBArtifactLoader.

22 pl_algorithm_config rows:
  * 5 soft-gate intensities (Fold B from EXP-OPTIM-022, gate-passing per
    EXP-OPTIM-024).
  * 12 wrapper detector flags + thresholds (TPW-001 tuned, EXP-OPTIM-025).
  * 14 specialist→cluster mappings (rule §0 #5 — config as data;
    winter vs spring duality externalized from code).
Note: total is 5 + 12 + 14 = 31, but the source SQL uses 22 ACTIVE +
9 reproducibility rows. We mirror the source verbatim.

Idempotent — re-applying yields no changes (NOT EXISTS guards).
"""

from alembic import op


revision = "l6g7h8i9j0k1"
down_revision = "k5f6g7h8i9j0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO pl_algorithm_version (id, name, version, horizon, is_active, compute_enabled, description)
        SELECT gen_random_uuid(),
               'ensemble_v1_softgate_wrapper', '1.0.0', 'short_term',
               TRUE, TRUE,
               'C4/C5 ensemble: 14 monthly-retrained specialists + soft-gate Bayesian + transition-protection wrapper. EXP-OPTIM-025 in-sample gate-passing config (2026-05-17). Day-1 promotion.'
        WHERE NOT EXISTS (
            SELECT 1 FROM pl_algorithm_version
            WHERE name = 'ensemble_v1_softgate_wrapper' AND version = '1.0.0'
        );
        """
    )
    op.execute(
        """
        INSERT INTO pl_algorithm_config (id, algorithm_version_id, parameter_name, value, description)
        SELECT gen_random_uuid(), v.id, kv.k, kv.v, kv.d
        FROM pl_algorithm_version v,
             (VALUES
                ('alpha_macro', '1.4770', 'soft-gate macro factor intensity (SG-001 Fold B)'),
                ('alpha_prior', '0.1664', 'soft-gate prior factor intensity (SG-001 Fold B)'),
                ('alpha_anomaly', '0.7219', 'soft-gate anomaly factor intensity (AV-001 positive polarity)'),
                ('commit_threshold', '0.2493', 'soft-gate commit threshold on |net_score|'),
                ('anomaly_clip_abs', '2.5', 'soft-gate clip on anomaly z-score'),
                ('wrapper_use_running_acc', '1', 'TPW-001 detector A ACTIVE'),
                ('wrapper_tau_run', '0.5931', 'TPW-001 running-accuracy gate threshold'),
                ('wrapper_running_window', '3', 'TPW-001 running-accuracy window (trading days)'),
                ('wrapper_min_running_n', '2', 'TPW-001 minimum committed days in window'),
                ('wrapper_use_cluster_dispersion', '1', 'TPW-001 detector C ACTIVE'),
                ('wrapper_min_cluster_n', '2', 'TPW-001 minimum committed votes per cluster'),
                ('wrapper_use_trend_conflict', '0', 'TPW-001 detector B INACTIVE'),
                ('wrapper_tau_trend', '0.03', 'kept for reproducibility; detector OFF'),
                ('wrapper_trend_window', '7', 'kept for reproducibility; detector OFF'),
                ('wrapper_use_three_way_disagreement', '0', 'TPW-001 detector D INACTIVE'),
                ('cluster_exp_optim_002', 'winter', 'specialist cluster membership (CL-001 Winter)'),
                ('cluster_exp_optim_005', 'winter', 'specialist cluster membership (CL-001 Winter)'),
                ('cluster_exp_optim_006', 'winter', 'specialist cluster membership (CL-001 Winter)'),
                ('cluster_exp_optim_011', 'winter', 'specialist cluster membership (CL-001 Winter)'),
                ('cluster_xpol_W_TB_garch', 'winter', 'specialist cluster membership (CL-001 Winter)'),
                ('cluster_xpol_W_TB_macro', 'winter', 'specialist cluster membership (CL-001 Winter)'),
                ('cluster_exp_optim_017_bear_4', 'spring', 'specialist cluster membership (CL-001 Spring)'),
                ('cluster_exp_optim_017_bear_8', 'spring', 'specialist cluster membership (CL-001 Spring)'),
                ('cluster_exp_optim_017_bull_4', 'spring', 'specialist cluster membership (CL-001 Spring)'),
                ('cluster_exp_optim_017_bull_5', 'spring', 'specialist cluster membership (CL-001 Spring)'),
                ('cluster_exp_optim_017_bull_7', 'spring', 'specialist cluster membership (CL-001 Spring)'),
                ('cluster_exp_optim_017_bull_8', 'spring', 'specialist cluster membership (CL-001 Spring)'),
                ('cluster_xpol_S_bull_garch_fx', 'spring', 'specialist cluster membership (CL-001 Spring)'),
                ('cluster_xpol_S_bear_garch_macro', 'spring', 'specialist cluster membership (CL-001 Spring)')
             ) AS kv(k, v, d)
        WHERE v.name = 'ensemble_v1_softgate_wrapper'
          AND v.version = '1.0.0'
          AND NOT EXISTS (
              SELECT 1 FROM pl_algorithm_config c
              WHERE c.algorithm_version_id = v.id AND c.parameter_name = kv.k
          );
        """
    )


def downgrade() -> None:
    # Remove config rows then the version row. FK ensures order.
    op.execute(
        """
        DELETE FROM pl_algorithm_config
        WHERE algorithm_version_id IN (
            SELECT id FROM pl_algorithm_version
            WHERE name = 'ensemble_v1_softgate_wrapper' AND version = '1.0.0'
        );
        """
    )
    op.execute(
        """
        DELETE FROM pl_algorithm_version
        WHERE name = 'ensemble_v1_softgate_wrapper' AND version = '1.0.0';
        """
    )
