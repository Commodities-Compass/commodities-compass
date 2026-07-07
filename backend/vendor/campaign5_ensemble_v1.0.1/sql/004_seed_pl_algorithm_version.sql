-- Campaign 5 — algorithm_version + algorithm_config seed rows.
--
-- Idempotent: re-running yields no changes when the version row already exists
-- (the WHERE ... NOT EXISTS guard skips both the version INSERT and the
-- config rows, which key off the version's id).
--
-- Notes per CAMPAIGN_5_PROD_DEPLOYMENT.md:
--   * v1.0.1 ships INERT (is_active=FALSE, compute_enabled=FALSE) — prod owns the
--     atomic cutover (§9 item 1: a live Day-1 seed crashed cc-compute-indicators
--     with KeyError 'k'). The algorithm_kind='ensemble' tag makes the runner DISPATCH
--     to the ensemble path instead of forcing the legacy power-formula path. Prod:
--     formalize the ALTER below via an Alembic migration merged to main.
--   * Per-specialist HPs are NOT inserted here — they live in pl_model_artifact
--     (BYTEA) and are looked up by name + training_month.
--   * No GCS artifact URI rows: prod loads artifacts from pl_model_artifact,
--     not from gs://. The earlier draft of this seed included
--     'specialist_artifacts_uri' / 'long_run_artifacts_uri' — both REMOVED.
--   * Specialist→cluster mapping rows ('cluster_<name>') implement rule §0 #5
--     (config as data) by externalizing the Winter/Spring duality assignment
--     out of code into ``pl_algorithm_config``. The wrapper's prod loader
--     reads these at job start; future C6 specialists are DB-only additions.

ALTER TABLE pl_algorithm_version
    ADD COLUMN IF NOT EXISTS algorithm_kind VARCHAR(32) NOT NULL DEFAULT 'power_formula';

INSERT INTO pl_algorithm_version (id, name, version, horizon, is_active, compute_enabled, algorithm_kind, description)
SELECT gen_random_uuid(),
       'ensemble_v1_softgate_wrapper', '1.0.1', 'short_term',
       FALSE, FALSE, 'ensemble',
       'C5 ensemble v1.0.1: 14 specialists retrained on the 2026-06 window (incl. the May high-vol regime) + vol-stratified soft-gate (alpha_macro 1.477->0.065, capped <=0.9, EXP-OPTIM-022b) + transition wrapper. Ship inert; prod owns cutover.'
WHERE NOT EXISTS (
    SELECT 1 FROM pl_algorithm_version
    WHERE name = 'ensemble_v1_softgate_wrapper' AND version = '1.0.1'
);

INSERT INTO pl_algorithm_config (id, algorithm_version_id, parameter_name, value, description)
SELECT gen_random_uuid(), v.id, kv.k, kv.v, kv.d
FROM pl_algorithm_version v,
     (VALUES
        -- Soft-gate intensities (v1.0.1 VOL-STRATIFIED retune, EXP-OPTIM-022b).
        -- alpha_macro dropped 1.477 -> 0.065 (capped <=0.9); collapse share 40.5%->10.8%,
        -- hi-vol commit-acc +13pp. MUST match the frozen soft_gate_config BYTEA payload.
        ('alpha_macro', '0.0651', 'soft-gate macro factor intensity (EXP-OPTIM-022b, capped)'),
        ('alpha_prior', '0.0032', 'soft-gate prior factor intensity (EXP-OPTIM-022b)'),
        ('alpha_anomaly', '0.3452', 'soft-gate anomaly factor intensity (EXP-OPTIM-022b)'),
        ('commit_threshold', '0.0809', 'soft-gate commit threshold on |net_score|'),
        ('anomaly_clip_abs', '2.5', 'soft-gate clip on anomaly z-score'),
        ('alpha_macro_cap', '0.9', 'v1.0.1 guardrail: effective alpha_macro ceiling (== compass cap)'),

        -- Wrapper detectors (output/exp_optim_025/tuned_config.json — TPW-001).
        ('wrapper_use_running_acc', '1', 'TPW-001 detector A ACTIVE'),
        ('wrapper_tau_run', '0.5931', 'TPW-001 running-accuracy gate threshold'),
        ('wrapper_running_window', '3', 'TPW-001 running-accuracy window (trading days)'),
        ('wrapper_min_running_n', '2', 'TPW-001 minimum committed days in window'),
        ('wrapper_use_cluster_dispersion', '1', 'TPW-001 detector C ACTIVE'),
        ('wrapper_min_cluster_n', '2', 'TPW-001 minimum committed votes per cluster'),
        ('wrapper_use_trend_conflict', '1', 'detector B ACTIVE — aligned with live prod (PR #43); §4.E'),
        ('wrapper_tau_trend', '0.03', 'kept for reproducibility; detector OFF'),
        ('wrapper_trend_window', '7', 'kept for reproducibility; detector OFF'),
        ('wrapper_use_three_way_disagreement', '0', 'TPW-001 detector D INACTIVE'),

        -- Specialist → cluster mapping (rule §0 #5).
        -- Winter pool (Jan-Feb specialists + W-class xpol):
        ('cluster_exp_optim_002', 'winter', 'specialist cluster membership (CL-001 Winter)'),
        ('cluster_exp_optim_005', 'winter', 'specialist cluster membership (CL-001 Winter)'),
        ('cluster_exp_optim_006', 'winter', 'specialist cluster membership (CL-001 Winter)'),
        ('cluster_exp_optim_011', 'winter', 'specialist cluster membership (CL-001 Winter)'),
        ('cluster_xpol_W_TB_garch', 'winter', 'specialist cluster membership (CL-001 Winter)'),
        ('cluster_xpol_W_TB_macro', 'winter', 'specialist cluster membership (CL-001 Winter)'),

        -- Spring pool (Mar-Apr specialists + S-class xpol):
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
