"""seed ensemble_v1_softgate_wrapper v1.0.1 (INERT/shadow) + algorithm_kind + 30 config rows

Revision ID: f1a2b3c4d5e6
Revises: e7f8a9b0c1d2
Create Date: 2026-06-23

Source: campaign5_ensemble_v1.0.1/sql/004_seed_pl_algorithm_version.sql

Ships v1.0.1 INERT (is_active=FALSE, compute_enabled=FALSE) — prod owns the
atomic cutover (brief §8 / §9 item 1: a live Day-1 seed crashed
cc-compute-indicators with KeyError 'k'). v1.0.0 stays the live row; the
runner resolves the ensemble version by (name, version), defaulting to the
live version, so adding this second same-name row does NOT change live
selection.

New column `algorithm_kind` (vendor sql/004): added with default 'power_formula'
so existing legacy/power rows keep their semantics. We ALSO retro-tag every
`ensemble_v1_softgate_wrapper` row (incl. the live v1.0.0) to 'ensemble' —
the vendor SQL omits this, which would mis-tag v1.0.0 as power_formula.

31 pl_algorithm_config rows scoped to v1.0.1:
  * 6 soft-gate intensities (EXP-OPTIM-022b vol-stratified retune;
    alpha_macro 1.477 -> 0.065, commit_threshold 0.249 -> 0.081, + alpha_macro_cap).
  * 10 wrapper detector flags/thresholds (use_trend_conflict=1, aligned with PR #43).
  * 14 specialist -> cluster mappings (unchanged Winter/Spring duality).
  * 1 prod-side Compass lever (dispersion_with_acc_threshold [fail-loud required]).
    regime_monitor_atr_pctl is DELIBERATELY NOT seeded for v1.0.1 (recalibration —
    it mutes v1.0.1's correct high-vol commits; see step 5 comment).

Per-specialist HPs are NOT seeded here — they live in pl_model_artifact (BYTEA),
loaded into local/prod via cc-ensemble-bootstrap-artifacts.

Idempotent — re-applying yields no changes (IF NOT EXISTS / NOT EXISTS guards).
"""

from alembic import op


revision = "f1a2b3c4d5e6"
down_revision = "e7f8a9b0c1d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) algorithm_kind column (vendor sql/004) — idempotent.
    op.execute(
        """
        ALTER TABLE pl_algorithm_version
            ADD COLUMN IF NOT EXISTS algorithm_kind VARCHAR(32)
            NOT NULL DEFAULT 'power_formula';
        """
    )
    # 2) Retro-tag ALL ensemble rows (incl. live v1.0.0) to 'ensemble'. The
    #    vendor SQL only tags the new v1.0.1 row; without this the column
    #    default would mis-classify v1.0.0 as power_formula.
    op.execute(
        """
        UPDATE pl_algorithm_version
        SET algorithm_kind = 'ensemble'
        WHERE name = 'ensemble_v1_softgate_wrapper'
          AND algorithm_kind <> 'ensemble';
        """
    )
    # 3) Insert the v1.0.1 version row — INERT.
    op.execute(
        """
        INSERT INTO pl_algorithm_version (id, name, version, horizon, is_active, compute_enabled, algorithm_kind, description)
        SELECT gen_random_uuid(),
               'ensemble_v1_softgate_wrapper', '1.0.1', 'short_term',
               FALSE, FALSE, 'ensemble',
               'C5 ensemble v1.0.1: 14 specialists retrained on the 2026-06 window (incl. the May high-vol regime) + vol-stratified soft-gate (alpha_macro 1.477->0.065, capped <=0.9, EXP-OPTIM-022b) + transition wrapper. Ship inert; prod owns cutover.'
        WHERE NOT EXISTS (
            SELECT 1 FROM pl_algorithm_version
            WHERE name = 'ensemble_v1_softgate_wrapper' AND version = '1.0.1'
        );
        """
    )
    # 4) Insert the 30 config rows, scoped to the v1.0.1 version id.
    op.execute(
        """
        INSERT INTO pl_algorithm_config (id, algorithm_version_id, parameter_name, value, description)
        SELECT gen_random_uuid(), v.id, kv.k, kv.v, kv.d
        FROM pl_algorithm_version v,
             (VALUES
                ('alpha_macro', '0.0651', 'soft-gate macro factor intensity (EXP-OPTIM-022b, capped)'),
                ('alpha_prior', '0.0032', 'soft-gate prior factor intensity (EXP-OPTIM-022b)'),
                ('alpha_anomaly', '0.3452', 'soft-gate anomaly factor intensity (EXP-OPTIM-022b)'),
                ('commit_threshold', '0.0809', 'soft-gate commit threshold on |net_score|'),
                ('anomaly_clip_abs', '2.5', 'soft-gate clip on anomaly z-score'),
                ('alpha_macro_cap', '0.9', 'v1.0.1 guardrail: effective alpha_macro ceiling (== compass cap)'),
                ('wrapper_use_running_acc', '1', 'TPW-001 detector A ACTIVE'),
                ('wrapper_tau_run', '0.5931', 'TPW-001 running-accuracy gate threshold'),
                ('wrapper_running_window', '3', 'TPW-001 running-accuracy window (trading days)'),
                ('wrapper_min_running_n', '2', 'TPW-001 minimum committed days in window'),
                ('wrapper_use_cluster_dispersion', '1', 'TPW-001 detector C ACTIVE'),
                ('wrapper_min_cluster_n', '2', 'TPW-001 minimum committed votes per cluster'),
                ('wrapper_use_trend_conflict', '1', 'detector B ACTIVE — aligned with live prod (PR #43); §4.E'),
                ('wrapper_tau_trend', '0.03', 'TPW-001 trend-conflict threshold'),
                ('wrapper_trend_window', '7', 'TPW-001 trend-conflict window (trading days)'),
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
          AND v.version = '1.0.1'
          AND NOT EXISTS (
              SELECT 1 FROM pl_algorithm_config c
              WHERE c.algorithm_version_id = v.id AND c.parameter_name = kv.k
          );
        """
    )
    # 5) Prod-side Compass wrapper lever (NOT in the vendor pack — the live
    #    equivalent of migration o9j0k1l2m3n4, scoped to the v1.0.1 version id):
    #    dispersion_with_acc_threshold is FAIL-LOUD required by
    #    CompassTransitionWrapper (load_compass_wrapper_threshold).
    #
    #    RECALIBRATION vs v1.0.0 — two live levers are DELIBERATELY NOT seeded:
    #    - regime_monitor_atr_pctl (e7f8a9b0c1d2): OMITTED. Shadow backfill
    #      (Apr-Jun 2026) showed it mutes v1.0.1's *correct* high-vol HEDGEs
    #      (-14% total edge): v1.0.1's de-saturated soft-gate (alpha_macro
    #      1.477->0.065) no longer has the saturated-HEDGE pathology that
    #      regime-MONITOR was built to abstain from. Absent row => loader
    #      returns None => detector off. Re-introduce only if OOS data warrants.
    #    - alpha_macro cap (compass_softgate_alpha_macro_cap): OMITTED — v1.0.1
    #      caps natively in soft_gate.py (alpha_macro_cap=0.9 row above).
    op.execute(
        """
        INSERT INTO pl_algorithm_config (id, algorithm_version_id, parameter_name, value, description)
        SELECT gen_random_uuid(), v.id, kv.k, kv.v, kv.d
        FROM pl_algorithm_version v,
             (VALUES
                ('compass_wrapper_dispersion_with_acc_threshold', '0.60', 'Compass wrapper: release dispersion-only veto when running_acc >= this (PR #46 / o9j0k1l2m3n4)')
             ) AS kv(k, v, d)
        WHERE v.name = 'ensemble_v1_softgate_wrapper'
          AND v.version = '1.0.1'
          AND NOT EXISTS (
              SELECT 1 FROM pl_algorithm_config c
              WHERE c.algorithm_version_id = v.id AND c.parameter_name = kv.k
          );
        """
    )


def downgrade() -> None:
    # Artifacts FK pl_algorithm_version — clear them first so the version delete
    # below doesn't trip the FK once cc-ensemble-bootstrap-artifacts has loaded.
    op.execute(
        """
        DELETE FROM pl_model_artifact
        WHERE algorithm_version_id IN (
            SELECT id FROM pl_algorithm_version
            WHERE name = 'ensemble_v1_softgate_wrapper' AND version = '1.0.1'
        );
        """
    )
    # Remove v1.0.1 config rows then the version row (FK order). Leave the
    # algorithm_kind column + the v1.0.0 retro-tag in place — dropping the
    # column would lose data for other rows, and the tag is harmless.
    op.execute(
        """
        DELETE FROM pl_algorithm_config
        WHERE algorithm_version_id IN (
            SELECT id FROM pl_algorithm_version
            WHERE name = 'ensemble_v1_softgate_wrapper' AND version = '1.0.1'
        );
        """
    )
    op.execute(
        """
        DELETE FROM pl_algorithm_version
        WHERE name = 'ensemble_v1_softgate_wrapper' AND version = '1.0.1';
        """
    )
