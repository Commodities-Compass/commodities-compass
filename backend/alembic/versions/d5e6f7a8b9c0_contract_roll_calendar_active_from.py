"""contract roll calendar — ref_contract.active_from + calendar-based v_contract_data_chained

Revision ID: d5e6f7a8b9c0
Revises: b1c2d3e4f5a6
Create Date: 2026-07-22

Introduces the canonical front-month roll calendar (single source of truth),
replacing the divergent contract-resolution heuristics that caused the recurring
roll split-brain. See docs/user-stories/P1-contract-roll-canonical-frontmonth.md.

DDL
  - ref_contract.active_from DATE — the session date a contract became the
    operator-pinned front-month. NULL = never front-month (e.g. next-month
    contracts scraped ahead of a roll). Index on (commodity_id, active_from)
    for the per-date lookup.

Seed (correctness-critical — reconstructs the OPERATOR's real roll history from
the DECISION series, NOT from liquidity which has the premature-roll bug that
writes CAZ26 from 2026-07-17):
  Within the ENSEMBLE era (date >= first ensemble date) the operator front-month
  per date = the contract carrying the ENSEMBLE decision ONLY (never legacy);
  before the ensemble era it falls back to legacy. active_from(contract) =
  MIN(date) where that per-date resolution == contract.
    → clean Feb-2026→now: CAK26=2026-03-02, CAN26=2026-04-10, CAU26=2026-06-17.
    → CAZ26 gets NO active_from STRUCTURALLY: it has no ensemble rows, and in the
      ensemble era legacy-only dates yield no per-date entry → CAZ26 can never be
      seeded, even if ensemble-compute had a gap on a buggy CAZ26 date.
    → boundary contracts of 2025 resolve via legacy for pre-ensemble dates
      (e.g. CAZ25 active_from = its first legacy date) so late-2025 stays correct.

VIEW v_contract_data_chained
  Rebuilt as a JOIN on the calendar: front-month for a date = the contract with
  the greatest active_from <= date. No oi/volume heuristic → no premature roll,
  and immutable (no retroactive boundary shift at the real roll).

Downgrade restores the OI-AND-volume VIEW (c7d8e9f0a1b2) and drops the column.
Idempotent (ADD COLUMN IF NOT EXISTS / CREATE OR REPLACE VIEW / guarded UPDATE).
"""

from alembic import op

revision: str = "d5e6f7a8b9c0"
down_revision: str = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


_ADD_COLUMN = """
ALTER TABLE ref_contract ADD COLUMN IF NOT EXISTS active_from DATE;
CREATE INDEX IF NOT EXISTS ix_ref_contract_commodity_active_from
    ON ref_contract (commodity_id, active_from);
"""

# Reconstruct active_from from the operator's real roll history (decision series).
# STRUCTURAL CAZ26 exclusion: inside the ensemble era we use ENSEMBLE rows ONLY,
# never legacy. So a legacy-only date (the buggy premature-roll CAZ26 rows from
# 2026-07-17) produces NO per-date entry — the calendar simply carries the
# incumbent (CAU26) forward — and CAZ26 can never be seeded, even if
# ensemble-compute had a gap on that exact date. The old "prefer ensemble, else
# legacy" version was NON-structural: one ensemble gap over the buggy window
# would have stamped CAZ26.active_from and re-created the very split-brain this
# migration exists to kill. Pre-ensemble-era dates fall back to legacy.
_SEED = """
WITH ens_era AS (
    SELECT MIN(iv.date) AS start_date
    FROM pl_indicator_daily iv
    JOIN pl_algorithm_version av ON av.id = iv.algorithm_version_id
    WHERE av.name = 'ensemble_v1_softgate_wrapper'
),
per_date_front AS (
    SELECT DISTINCT ON (iv.date) iv.date, iv.contract_id
    FROM pl_indicator_daily iv
    JOIN pl_algorithm_version av ON av.id = iv.algorithm_version_id
    CROSS JOIN ens_era
    WHERE (
        ens_era.start_date IS NOT NULL
        AND iv.date >= ens_era.start_date
        AND av.name = 'ensemble_v1_softgate_wrapper'
    ) OR (
        (ens_era.start_date IS NULL OR iv.date < ens_era.start_date)
        AND av.name = 'legacy'
    )
    ORDER BY iv.date, iv.contract_id
),
seed AS (
    SELECT contract_id, MIN(date) AS first_date
    FROM per_date_front
    GROUP BY contract_id
)
UPDATE ref_contract c
SET active_from = seed.first_date
FROM seed
WHERE c.id = seed.contract_id
  AND c.active_from IS DISTINCT FROM seed.first_date;
"""

_NEW_VIEW = """
CREATE OR REPLACE VIEW v_contract_data_chained AS
WITH front AS (
    SELECT dd.date,
           (SELECT c.id
              FROM ref_contract c
             WHERE c.active_from IS NOT NULL
               AND c.active_from <= dd.date
             ORDER BY c.active_from DESC
             LIMIT 1) AS front_id
    FROM (SELECT DISTINCT date
            FROM pl_contract_data_daily
           WHERE close IS NOT NULL) dd
)
SELECT d.date, d.display_date, d.contract_id,
       d.open, d.high, d.low, d.close,
       d.volume, d.oi, d.implied_volatility
FROM pl_contract_data_daily d
JOIN front f ON f.date = d.date AND f.front_id = d.contract_id
WHERE d.close IS NOT NULL;
"""

# Exact restore of the pre-refactor VIEW (revision c7d8e9f0a1b2).
_OLD_VIEW = """
CREATE OR REPLACE VIEW v_contract_data_chained AS
WITH per_date AS (
    SELECT date,
           MAX(COALESCE(oi, 0))     AS max_oi,
           MAX(COALESCE(volume, 0)) AS max_vol
    FROM pl_contract_data_daily
    WHERE close IS NOT NULL
    GROUP BY date
)
SELECT DISTINCT ON (d.date)
    d.date, d.display_date, d.contract_id,
    d.open, d.high, d.low, d.close,
    d.volume, d.oi, d.implied_volatility
FROM pl_contract_data_daily d
JOIN ref_contract c ON c.id = d.contract_id
JOIN per_date pd ON pd.date = d.date
WHERE d.close IS NOT NULL
ORDER BY d.date ASC,
    (COALESCE(d.oi, 0) >= pd.max_oi
     AND COALESCE(d.volume, 0) >= pd.max_vol) DESC,
    c.contract_month ASC;
"""


def upgrade() -> None:
    op.execute(_ADD_COLUMN)
    op.execute(_SEED)
    op.execute(_NEW_VIEW)


def downgrade() -> None:
    op.execute(_OLD_VIEW)
    op.execute("DROP INDEX IF EXISTS ix_ref_contract_commodity_active_from;")
    op.execute("ALTER TABLE ref_contract DROP COLUMN IF EXISTS active_from;")
