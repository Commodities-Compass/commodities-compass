"""remove NCA pre-2021 ghost rows from publication calendar

Revision ID: q1l2m3n4o5p6
Revises: p0k1l2m3n4o5
Create Date: 2026-05-27

The seed of p0k1l2m3n4o5 generates calendar rows for both ECA and NCA from
Q1-2019 -> Q4-2027 uniformly, without modeling each publisher's actual public
start date. NCA Cocoa Grinds Report only started publishing publicly in
Q1-2021 (the backfill ingested Q1-2021 onwards but found nothing earlier;
the NCA parser only recognizes filenames like ``2021_1stQtr_...``).
The 8 NCA rows Q1-2019 -> Q4-2020 are therefore ghost rows the watchdog
flags forever -- they will never be ingested because the publisher never
published.

This migration removes them. ECA pre-2020 NULL rows are NOT touched here:
the publisher did publish (PDFs are still on eurococoa.com), those are real
ingestion gaps to fix separately via regex/parser improvements + backfill
re-run.

If a future publisher with a non-2019 start date is added, encode its
start_quarter in a shared seed module rather than copying the unfiltered
``range(2019, ...)`` pattern from p0k1l2m3n4o5.
"""

from __future__ import annotations

from alembic import op


revision = "q1l2m3n4o5p6"
down_revision = "p0k1l2m3n4o5"
branch_labels = None
depends_on = None


_GHOST_PERIODS = (
    "Q1-2019",
    "Q2-2019",
    "Q3-2019",
    "Q4-2019",
    "Q1-2020",
    "Q2-2020",
    "Q3-2020",
    "Q4-2020",
)


def upgrade() -> None:
    period_list = ", ".join(f"'{p}'" for p in _GHOST_PERIODS)
    op.execute(
        f"""
        DELETE FROM ref_publication_calendar
        WHERE source = 'nca'
          AND category = 'grindings'
          AND period_label IN ({period_list})
          AND actual_publication_date IS NULL
        """
    )


def downgrade() -> None:
    # Ghost rows are removed by design. Downgrade is a no-op -- if a rollback
    # is truly needed, manually re-INSERT via the original seed logic in
    # p0k1l2m3n4o5._build_quarterly_seed_rows.
    pass
