-- Campaign 5 — model artifact registry.
--
-- One BYTEA payload per (algorithm_version, artifact_kind, artifact_name,
-- training_month). The pipeline reads from this table at job time, verifies
-- SHA-256 on every load (fail loud per rule §0 #1), then deserializes.
--
-- Layout: 14 specialist_model rows per training_month + 3 long_run rows
-- (anomaly, priors, regime_clusters; training_month=NULL) + 2 tuned_config rows
-- (soft_gate, wrapper; training_month=NULL) + 5 canonical_snapshot rows
-- (training_month=NULL). ~38 rows total per delivery, ~7-10 MB on disk before
-- TOAST compression.
--
-- Idempotent: re-running the migration is a no-op when the table exists.

CREATE TABLE IF NOT EXISTS pl_model_artifact (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    algorithm_version_id UUID NOT NULL REFERENCES pl_algorithm_version(id),

    artifact_kind        VARCHAR(64) NOT NULL,
    -- Values validated app-side. Allowed in v1.0.0:
    --   'specialist_model', 'specialist_hp',
    --   'long_run_anomaly', 'long_run_priors', 'long_run_regime_clusters',
    --   'soft_gate_config', 'wrapper_config',
    --   'canonical_snapshot'.

    artifact_name        VARCHAR(128) NOT NULL,
    -- Stable across monthly retrains (e.g. 'exp_optim_011') so the loader can
    -- ask for "this specialist, latest month" without hardcoding suffixes.

    training_month       VARCHAR(7) NULL,
    -- 'YYYY-MM' for specialist_model / specialist_hp; NULL for the long-run,
    -- tuned-config and canonical-snapshot artifacts that don't refit monthly.

    payload              BYTEA NOT NULL,
    payload_encoding     VARCHAR(16) NOT NULL,         -- 'pickle' | 'json-utf8' | 'parquet' | 'csv-utf8'
    sha256               CHAR(64) NOT NULL,            -- hex digest of payload bytes
    n_bytes              INTEGER NOT NULL,

    -- Provenance (rule §0 #3 — every column traces to a computation).
    fit_train_start      DATE NULL,
    fit_train_end        DATE NULL,
    n_train              INTEGER NULL,
    class_balance        JSONB NULL,                   -- {"DOWN":0.59,"FLAT":0.16,"UP":0.25}
    git_sha              VARCHAR(40) NOT NULL,
    python_version       VARCHAR(20) NOT NULL,
    lib_versions         JSONB NOT NULL,               -- {"numpy":"1.26.4","lightgbm":"4.3.0", ...}

    created_at           TIMESTAMP NOT NULL DEFAULT now(),

    CONSTRAINT uq_pl_model_artifact
        UNIQUE (algorithm_version_id, artifact_kind, artifact_name, training_month)
);

CREATE INDEX IF NOT EXISTS ix_pl_model_artifact_kind
    ON pl_model_artifact (algorithm_version_id, artifact_kind);
