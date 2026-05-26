"""add pl_supply_demand_observation + ref_publication_calendar

Revision ID: p0k1l2m3n4o5
Revises: o9j0k1l2m3n4
Create Date: 2026-05-26

Two new tables to support fundamental data scrapers (P3 user story):

* ``ref_publication_calendar`` (reference)
    Source of truth for expected publication dates of fundamental data
    (ECA / NCA quarterly grindings, and future sources). Scrapers gate
    against this table — they only fetch when ``today()`` falls within
    ``expected_publication_date ± tolerance_days`` and
    ``actual_publication_date IS NULL``. Seeded with ECA + NCA quarterly
    dates 2019-Q1 → 2027-Q4 (~72 rows).

* ``pl_supply_demand_observation`` (pipeline)
    Unified EAV-style storage for fundamental metrics (grindings volumes,
    crop forecasts, arrivals). Distinct from ``pl_fundamental_article``
    (narrative LLM-extracted articles) to avoid naming collisions.

See docs/user-stories/P3-fundamental-data-scrapers-grindings.md.

ICCO scope dropped in this iteration — data is paywalled (members only).
"""

from __future__ import annotations

from datetime import date

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = "p0k1l2m3n4o5"
down_revision = "o9j0k1l2m3n4"
branch_labels = None
depends_on = None


# Expected publication dates for ECA + NCA quarterly grindings.
# Both associations publish ~mid-month after each quarter end:
#   Q1 (Jan-Mar)  → mid-April same year
#   Q2 (Apr-Jun)  → mid-July same year
#   Q3 (Jul-Sep)  → mid-October same year
#   Q4 (Oct-Dec)  → mid-January following year
# Tolerance of 14 days absorbs Thursday-of-week shifts and one-week delays.
_ECA_NCA_PUBLICATION_DAYS = {
    1: (4, 16),  # Q1 → April 16
    2: (7, 16),  # Q2 → July 16
    3: (10, 15),  # Q3 → October 15
    4: (1, 21),  # Q4 → January 21 (year + 1)
}


def _build_quarterly_seed_rows() -> list[dict]:
    rows: list[dict] = []
    for year in range(2019, 2028):
        for quarter in range(1, 5):
            month, day = _ECA_NCA_PUBLICATION_DAYS[quarter]
            pub_year = year + 1 if quarter == 4 else year
            expected = date(pub_year, month, day)
            period_label = f"Q{quarter}-{year}"
            # Period_date = 1st day of the first month of the quarter
            period_date = date(year, (quarter - 1) * 3 + 1, 1)
            for source in ("eca", "nca"):
                rows.append(
                    {
                        "source": source,
                        "category": "grindings",
                        "region": "europe" if source == "eca" else "north_america",
                        "period_label": period_label,
                        "period_date": period_date,
                        "expected_publication_date": expected,
                        "tolerance_days": 14,
                    }
                )
    return rows


def upgrade() -> None:
    op.create_table(
        "ref_publication_calendar",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("source", sa.VARCHAR(30), nullable=False),
        sa.Column("category", sa.VARCHAR(30), nullable=False),
        sa.Column("region", sa.VARCHAR(30), nullable=True),
        sa.Column("period_label", sa.VARCHAR(20), nullable=False),
        sa.Column("period_date", sa.DATE(), nullable=False),
        sa.Column("expected_publication_date", sa.DATE(), nullable=False),
        sa.Column(
            "tolerance_days",
            sa.INTEGER(),
            nullable=False,
            server_default=sa.text("14"),
        ),
        sa.Column("actual_publication_date", sa.DATE(), nullable=True),
        sa.Column("notes", sa.TEXT(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "source", "category", "period_label", name="uq_publication_calendar"
        ),
        if_not_exists=True,
    )
    op.create_index(
        "ix_publication_calendar_lookup",
        "ref_publication_calendar",
        ["source", "expected_publication_date"],
        if_not_exists=True,
    )

    op.create_table(
        "pl_supply_demand_observation",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("publication_date", sa.DATE(), nullable=False),
        sa.Column("period_date", sa.DATE(), nullable=False),
        sa.Column("period_label", sa.VARCHAR(20), nullable=False),
        sa.Column("category", sa.VARCHAR(30), nullable=False),
        sa.Column("source", sa.VARCHAR(30), nullable=False),
        sa.Column("region", sa.VARCHAR(30), nullable=True),
        sa.Column("metric_name", sa.VARCHAR(50), nullable=False),
        sa.Column("value", sa.DOUBLE_PRECISION(), nullable=True),
        sa.Column("metadata_json", JSONB, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "publication_date",
            "category",
            "source",
            "region",
            "period_label",
            "metric_name",
            name="uq_supply_demand_observation",
        ),
        if_not_exists=True,
    )
    op.create_index(
        "ix_supply_demand_observation_lookup",
        "pl_supply_demand_observation",
        ["category", "source", "period_date"],
        postgresql_using="btree",
        if_not_exists=True,
    )

    # Seed ref_publication_calendar with ECA + NCA quarterly dates 2019-2027.
    # ON CONFLICT DO NOTHING makes it idempotent for GCP re-application.
    rows = _build_quarterly_seed_rows()
    if rows:
        conn = op.get_bind()
        conn.execute(
            sa.text(
                """
                INSERT INTO ref_publication_calendar (
                    source, category, region, period_label,
                    period_date, expected_publication_date, tolerance_days
                )
                VALUES (
                    :source, :category, :region, :period_label,
                    :period_date, :expected_publication_date, :tolerance_days
                )
                ON CONFLICT (source, category, period_label) DO NOTHING
                """
            ),
            rows,
        )


def downgrade() -> None:
    op.drop_index(
        "ix_supply_demand_observation_lookup",
        table_name="pl_supply_demand_observation",
    )
    op.drop_table("pl_supply_demand_observation")
    op.drop_index(
        "ix_publication_calendar_lookup", table_name="ref_publication_calendar"
    )
    op.drop_table("ref_publication_calendar")
