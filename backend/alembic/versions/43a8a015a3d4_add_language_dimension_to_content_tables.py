"""add language dimension to content tables

Revision ID: 43a8a015a3d4
Revises: a9b8c7d6e5f4
Create Date: 2026-07-16 10:37:09.364053

Adds a ``language`` column (VARCHAR(5), NOT NULL, server_default 'fr') to the
three content tables and widens their unique constraints to include it, so
FR + EN content can coexist per date (US-0, EN/Ghana edition). Every existing
row is French, so the server_default backfills them as 'fr'.

Idempotent + GCP-safe: guarded by column / constraint introspection so a
partial or repeated apply is a no-op.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "43a8a015a3d4"
down_revision: Union[str, Sequence[str], None] = "a9b8c7d6e5f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table, unique_constraint_name, base_columns before language)
_CONTENT_TABLES: tuple[tuple[str, str, list[str]], ...] = (
    (
        "pl_indicator_daily",
        "uq_indicator_daily",
        ["date", "contract_id", "algorithm_version_id"],
    ),
    (
        "pl_fundamental_article",
        "uq_fundamental_article_date_provider",
        ["date", "llm_provider"],
    ),
    (
        "pl_weather_observation",
        "uq_weather_observation_date",
        ["date"],
    ),
)


def _has_column(table: str, column: str) -> bool:
    cols = [c["name"] for c in inspect(op.get_bind()).get_columns(table)]
    return column in cols


def _unique_columns(table: str, name: str) -> list[str]:
    for uc in inspect(op.get_bind()).get_unique_constraints(table):
        if uc["name"] == name:
            return list(uc["column_names"])
    return []


def upgrade() -> None:
    """Add ``language`` + widen the unique constraints. Idempotent."""
    for table, uq_name, base_cols in _CONTENT_TABLES:
        if not _has_column(table, "language"):
            op.add_column(
                table,
                sa.Column(
                    "language",
                    sa.VARCHAR(length=5),
                    nullable=False,
                    server_default="fr",
                ),
            )
        if "language" not in _unique_columns(table, uq_name):
            op.drop_constraint(uq_name, table, type_="unique")
            op.create_unique_constraint(uq_name, table, [*base_cols, "language"])


def downgrade() -> None:
    """Revert to the language-agnostic constraints + drop the column."""
    for table, uq_name, base_cols in reversed(_CONTENT_TABLES):
        if "language" in _unique_columns(table, uq_name):
            op.drop_constraint(uq_name, table, type_="unique")
            op.create_unique_constraint(uq_name, table, base_cols)
        if _has_column(table, "language"):
            op.drop_column(table, "language")
