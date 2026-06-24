"""Front-month chain by OI AND volume (v_contract_data_chained).

Revision ID: c7d8e9f0a1b2
Revises: e7f8a9b0c1d2
Create Date: 2026-06-24

Rebuild ``v_contract_data_chained`` so the front-month rolls onto the next
delivery month only when that contract leads on BOTH open interest AND volume
on a date. On a *split* (one contract leads OI, another leads volume — the
ambiguous window of a roll) it stays on the **incumbent** (earliest
``contract_month``).

Mirrors ``app.engine.runner.load_all_market_data`` verbatim so
compute-indicators (which writes ``pl_derived_indicators`` per contract) and the
ensemble ``load_market_history`` (which INNER-JOINs this VIEW to
``pl_derived_indicators`` on ``(date, contract_id)``) never disagree on the
front-month for a date. Their disagreement is the split-brain that crashed the
pipeline on 2026-06-23/24: an OI-only crossover rolled the VIEW to CAZ26 while
``pl_derived_indicators`` stayed CAU26, dropping the latest date from the join.

Idempotent: ``CREATE OR REPLACE VIEW`` keeps the exact same column list/order as
the prior view, so it is safe to re-apply (GCP cold-start replays head).
"""

from alembic import op

revision = "c7d8e9f0a1b2"
down_revision = "e7f8a9b0c1d2"
branch_labels = None
depends_on = None


_NEW_VIEW = """
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
    d.date,
    d.display_date,
    d.contract_id,
    d.open,
    d.high,
    d.low,
    d.close,
    d.volume,
    d.oi,
    d.implied_volatility
FROM pl_contract_data_daily d
JOIN ref_contract c ON c.id = d.contract_id
JOIN per_date pd ON pd.date = d.date
WHERE d.close IS NOT NULL
ORDER BY
    d.date ASC,
    (COALESCE(d.oi, 0) >= pd.max_oi
     AND COALESCE(d.volume, 0) >= pd.max_vol) DESC,
    c.contract_month ASC;
"""


_OLD_VIEW = """
CREATE OR REPLACE VIEW v_contract_data_chained AS
SELECT DISTINCT ON (date)
    date,
    display_date,
    contract_id,
    open,
    high,
    low,
    close,
    volume,
    oi,
    implied_volatility
FROM pl_contract_data_daily
WHERE close IS NOT NULL
ORDER BY
    date ASC,
    COALESCE(oi, 0) DESC,
    COALESCE(volume, 0) DESC,
    contract_id ASC;
"""


def upgrade() -> None:
    op.execute(_NEW_VIEW)


def downgrade() -> None:
    op.execute(_OLD_VIEW)
