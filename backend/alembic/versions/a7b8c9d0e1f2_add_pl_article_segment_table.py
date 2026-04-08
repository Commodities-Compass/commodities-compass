"""add pl_article_segment table

WHY THIS MIGRATION EXISTS ON MAIN
----------------------------------
This migration was originally created on feat/pattern-extractor and applied
directly to the GCP prod database before the branch was merged. Alembic
recorded revision a7b8c9d0e1f2 in prod's alembic_version table, so every
subsequent deploy on main crashed at startup because main didn't have this
file → "Can't locate revision identified by 'a7b8c9d0e1f2'".

Fix: cherry-pick the migration + model onto main so alembic upgrade head
finds the revision. The table already exists in prod (if_not_exists=True
makes this a no-op). The feature code (extraction pipeline, API endpoints)
stays on feat/pattern-extractor until that branch is merged.

WHAT IT DOES
------------
Stores structured segments extracted from press review articles (pl_fundamental_article),
segmented by geographic zone (london, west_africa, global) and business theme
(price_action, supply, demand, macro). Each article produces 0-8 segments via
LLM extraction. Segments are immutable — re-extraction creates rows with a new
extraction_version.

Revision ID: a7b8c9d0e1f2
Revises: 40aad93928c4
Create Date: 2026-04-08

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "40aad93928c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pl_article_segment",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "article_id",
            sa.Uuid(),
            sa.ForeignKey("pl_fundamental_article.id"),
            nullable=False,
        ),
        sa.Column("article_date", sa.DATE(), nullable=False),
        sa.Column("zone", sa.VARCHAR(30), nullable=False),
        sa.Column("theme", sa.VARCHAR(30), nullable=False),
        sa.Column("facts", sa.TEXT()),
        sa.Column("causal_chains", sa.TEXT()),
        sa.Column("sentiment", sa.VARCHAR(20)),
        sa.Column("sentiment_score", sa.DECIMAL(3, 2)),
        sa.Column("entities", sa.TEXT()),
        sa.Column("confidence", sa.DECIMAL(3, 2)),
        sa.Column("llm_provider", sa.VARCHAR(50), nullable=False),
        sa.Column("llm_model", sa.VARCHAR(100), nullable=False),
        sa.Column(
            "extraction_version", sa.VARCHAR(20), nullable=False, server_default="v1"
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "article_id",
            "zone",
            "theme",
            "extraction_version",
            name="uq_article_segment",
        ),
        if_not_exists=True,
    )
    op.create_index(
        "ix_article_segment_article_id",
        "pl_article_segment",
        ["article_id"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_article_segment_article_date",
        "pl_article_segment",
        ["article_date"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_article_segment_zone_theme",
        "pl_article_segment",
        ["zone", "theme"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_article_segment_zone_theme", table_name="pl_article_segment")
    op.drop_index("ix_article_segment_article_date", table_name="pl_article_segment")
    op.drop_index("ix_article_segment_article_id", table_name="pl_article_segment")
    op.drop_table("pl_article_segment")
