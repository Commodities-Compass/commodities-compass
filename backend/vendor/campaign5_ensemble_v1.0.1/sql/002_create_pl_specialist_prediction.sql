-- Campaign 5 — per-specialist daily vote audit table.
--
-- One row per (date, contract_id, algorithm_version_id, specialist_name).
-- Source for the wrapper's cluster-dispersion detector and the
-- post-hoc Phase 5 analysis ("which specialists were wrong on day X?").

CREATE TABLE IF NOT EXISTS pl_specialist_prediction (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    date                 DATE NOT NULL,
    contract_id          UUID NOT NULL REFERENCES ref_contract(id),
    algorithm_version_id UUID NOT NULL REFERENCES pl_algorithm_version(id),
    specialist_name      VARCHAR(64) NOT NULL,           -- e.g. "exp_optim_011"
    window_months        SMALLINT NOT NULL,              -- 12 (baseline / TB / calibrated-TB) or 24 (GARCH)
    pred                 VARCHAR(10) NOT NULL,           -- "OPEN" | "HEDGE" | "MONITOR"
    n_features_used      SMALLINT NULL,                  -- post-imputer feature count
    forward_return_6d    NUMERIC(15, 6) NULL,            -- back-filled once horizon h=6 expires
    created_at           TIMESTAMP NOT NULL DEFAULT now(),

    CONSTRAINT uq_specialist_prediction
        UNIQUE (date, contract_id, algorithm_version_id, specialist_name)
);

CREATE INDEX IF NOT EXISTS ix_specialist_prediction_date_version
    ON pl_specialist_prediction (date, algorithm_version_id);
