-- Campaign 5 — soft-gate + wrapper audit trail.
--
-- One row per (date, contract_id, algorithm_version_id). Captures both layers
-- of the decision: the raw soft-gate output (``soft_gate_decision``) and the
-- final wrapped output (``decision_wrapped``) that ``pl_indicator_daily``
-- mirrors. Every diagnostic column (running_acc_5d, realized_return_5d, …)
-- is NULLABLE so we can write NULL on day-1 / data-edge cases rather than
-- the silent 0.0 placeholder that rule §0 #3 forbids.

CREATE TABLE IF NOT EXISTS pl_orchestrator_decision (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    date                     DATE NOT NULL,
    contract_id              UUID NOT NULL REFERENCES ref_contract(id),
    algorithm_version_id     UUID NOT NULL REFERENCES pl_algorithm_version(id),

    -- Soft-gate outputs ----------------------------------------------------
    soft_gate_decision       VARCHAR(10) NOT NULL,         -- decision BEFORE the wrapper
    net_score                NUMERIC(15, 6) NOT NULL,
    weights_sum              NUMERIC(15, 6) NOT NULL,
    n_committed_specialists  SMALLINT NOT NULL,

    -- Wrapper outputs ------------------------------------------------------
    decision_wrapped         VARCHAR(10) NOT NULL,         -- final decision (mirrored in pl_indicator_daily)
    wrapper_active           BOOLEAN NOT NULL,
    fired_running_acc        BOOLEAN NOT NULL,
    fired_trend              BOOLEAN NOT NULL,
    fired_dispersion         BOOLEAN NOT NULL,
    fired_three_way          BOOLEAN NOT NULL,

    -- Context (audit trail) — every column traces to a computation per rule §0 #3.
    running_acc_5d           NUMERIC(8, 6) NULL,           -- NaN -> NULL
    realized_return_5d       NUMERIC(15, 6) NULL,
    winter_vote_signed       SMALLINT NULL,
    spring_vote_signed       SMALLINT NULL,
    macro_direction          SMALLINT NULL,                -- {-1, 0, +1}
    macro_surprise           NUMERIC(8, 6) NULL,
    macro_half_life_days     SMALLINT NULL,
    anomaly_score_z          NUMERIC(15, 6) NULL,
    prior_open               NUMERIC(8, 6) NULL,
    prior_hedge              NUMERIC(8, 6) NULL,
    prior_monitor            NUMERIC(8, 6) NULL,

    created_at               TIMESTAMP NOT NULL DEFAULT now(),

    CONSTRAINT uq_orchestrator_decision
        UNIQUE (date, contract_id, algorithm_version_id)
);

CREATE INDEX IF NOT EXISTS ix_orchestrator_decision_date_version
    ON pl_orchestrator_decision (date, algorithm_version_id);
