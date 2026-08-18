"""serving chain (serving_rank) + algorithm_kind on pl_algorithm_version

Revision ID: q2s3e4r5v6i7
Revises: p1q2r3s4t5u6
Create Date: 2026-08-18

Splits two overloaded booleans into four columns that each own exactly one
concern. Before this migration, `is_active` and `compute_enabled` were doing
double duty and neither described what the dashboard actually serves:

  * the SERVED algorithm was decided by hardcoded constants in Python
    (ENSEMBLE_VERSION_NAME / LEGACY_VERSION_NAME), not by any DB flag —
    so "flip is_active to switch what users see" simply does not work;
  * `is_active` IS read by the compute layer (engine/runner.py resolves the
    legacy version with `is_active = true`), so flipping it to switch serving
    would instead break the nightly indicator job;
  * `compute_enabled` is consumed by `compute-indicators --all-versions`,
    which feeds every enabled version through the power-formula engine. Any
    ML/LLM version flagged there crashes (KeyError 'k' on the missing power
    coefficients) or — worse, when it has no config rows at all — silently
    falls back to LEGACY_V1 and writes power-formula decisions under that
    version's id.

After this migration:

  | column           | layer   | meaning                                      |
  |------------------|---------|----------------------------------------------|
  | algorithm_kind   | schema  | which engine can execute this version        |
  | compute_enabled  | compute | run this power-formula variant nightly       |
  | is_active        | compute | the singleton "current" power-formula version|
  | serving_rank     | serving | dashboard preference order, NULL = not served|

serving_rank semantics — IT DESIGNATES A NAME, NOT A ROW. The resolver has
always keyed on `pl_algorithm_version.name` and, within a name, picked the
newest version that actually has a `pl_indicator_daily` row (that is what
lets ensemble v1.1.0 serve recent dates while v1.0.0 keeps the historical
ones). To preserve that, at most one row per name may carry a rank, enforced
by a partial unique index on `name`. The row carrying it is incidental.

This migration is a FUNCTIONAL NO-OP: ranks are seeded to reproduce exactly
the behaviour the hardcoded constants produce today (ensemble preferred,
legacy fallback, everything else unserved). The actual bascule is a separate,
later migration that only moves ranks around.

Idempotent (guarded ADD COLUMN / CREATE INDEX IF NOT EXISTS / guarded UPDATE)
so it is safe to re-apply on GCP.
"""

import sqlalchemy as sa
from alembic import op

revision = "q2s3e4r5v6i7"
down_revision = "p1q2r3s4t5u6"
branch_labels = None
depends_on = None


# Kinds that exist today. Anything not listed keeps the 'power_formula'
# default — which is correct for legacy v1.0.0 / v1.0.1 and power10years,
# the three versions the indicator engine really does compute.
_KIND_BY_NAME = {
    "ensemble_v1_softgate_wrapper": "ml_ensemble",
    "regime": "ml_regime",
    "judge": "llm_overlay",
}

# Serving chain seeded to today's hardcoded behaviour. `regime` and `judge`
# stay NULL: regime is not served until the bascule, and judge never gets a
# rank at all (it does not write pl_indicator_daily — it is fused into the
# regime decision by the adapter row).
_SEED_RANKS = (
    ("ensemble_v1_softgate_wrapper", 1),
    ("legacy", 2),
)


def _has_column(table: str, column: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :column"
        ),
        {"table": table, "column": column},
    )
    return result.fetchone() is not None


def _has_constraint(name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text("SELECT 1 FROM pg_constraint WHERE conname = :name"),
        {"name": name},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    if not _has_column("pl_algorithm_version", "algorithm_kind"):
        op.add_column(
            "pl_algorithm_version",
            sa.Column(
                "algorithm_kind",
                sa.VARCHAR(length=30),
                nullable=False,
                server_default="power_formula",
            ),
        )

    if not _has_column("pl_algorithm_version", "serving_rank"):
        op.add_column(
            "pl_algorithm_version",
            sa.Column("serving_rank", sa.Integer(), nullable=True),
        )

    # Backfill kinds. Guarded on the current value so a re-run never clobbers a
    # kind that was corrected by hand in the meantime.
    for name, kind in _KIND_BY_NAME.items():
        op.execute(
            sa.text(
                "UPDATE pl_algorithm_version SET algorithm_kind = :kind "
                "WHERE name = :name AND algorithm_kind = 'power_formula'"
            ).bindparams(kind=kind, name=name)
        )

    if not _has_constraint("ck_algorithm_kind"):
        op.execute(
            "ALTER TABLE pl_algorithm_version "
            "ADD CONSTRAINT ck_algorithm_kind CHECK (algorithm_kind IN "
            "('power_formula', 'ml_ensemble', 'ml_regime', 'llm_overlay'))"
        )

    # One row per rank, and one ranked row per name (the rank designates the
    # name — see module docstring).
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_algorithm_serving_rank "
        "ON pl_algorithm_version (serving_rank) WHERE serving_rank IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_algorithm_serving_name "
        "ON pl_algorithm_version (name) WHERE serving_rank IS NOT NULL"
    )

    # Seed the chain = today's behaviour. Only touch rows when NO row of that
    # name is ranked yet, so re-running is inert and a later bascule migration
    # is never undone by a replay of this one.
    for name, rank in _SEED_RANKS:
        op.execute(
            sa.text(
                """
                UPDATE pl_algorithm_version SET serving_rank = :rank
                WHERE id = (
                    SELECT id FROM pl_algorithm_version
                    WHERE name = :name
                    ORDER BY is_active DESC, created_at DESC
                    LIMIT 1
                )
                AND NOT EXISTS (
                    SELECT 1 FROM pl_algorithm_version
                    WHERE name = :name AND serving_rank IS NOT NULL
                )
                AND NOT EXISTS (
                    SELECT 1 FROM pl_algorithm_version WHERE serving_rank = :rank
                )
                """
            ).bindparams(rank=rank, name=name)
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_algorithm_serving_name")
    op.execute("DROP INDEX IF EXISTS uq_algorithm_serving_rank")
    op.execute(
        "ALTER TABLE pl_algorithm_version DROP CONSTRAINT IF EXISTS ck_algorithm_kind"
    )
    if _has_column("pl_algorithm_version", "serving_rank"):
        op.drop_column("pl_algorithm_version", "serving_rank")
    if _has_column("pl_algorithm_version", "algorithm_kind"):
        op.drop_column("pl_algorithm_version", "algorithm_kind")
