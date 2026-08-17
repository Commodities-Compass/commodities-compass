"""WatchAI origin ingestion — 6 tables for CI physical export flows

Revision ID: n9c0d1e2f3g4
Revises: m8b9c0d1e2f3
Create Date: 2026-08-12

Why
---
Block ② of the commercial matrix (origin physical flows: exports, purchases,
grindings for Côte d'Ivoire) is today a separate Streamlit product reading
parquet files on an OVH VPS. This migration lands the Compass-side schema so
the data can be replicated into our Postgres and served under Compass
entitlements, with no runtime coupling to that VPS.

Design: docs/watchai/watchai-integration.md §3.

What this migration does
------------------------
Creates six tables, all additive — nothing existing is touched:

1. ``pl_origin_ingest_batch``      — provenance of one manual load. With no
   Cloud Run execution to point at, this row is the only record the operation
   happened. Partial unique index enforces at most one ``is_current`` batch.
2. ``ref_origin_entity``           — canonical exporters / destinations, plus
   GEPEX membership as data rather than a hardcoded list.
3. ``pl_origin_export_declaration``— line-level customs declarations, reduced
   9-column projection. Deliberately no unique key (snapshot semantics; the
   source has no trustworthy line identifier).
4. ``pl_origin_purchase_monthly``  — exporter × month purchases.
5. ``pl_origin_grinding_monthly``  — GEPEX-aggregate grindings, no exporter
   dimension by construction.
6. ``pl_origin_flow_monthly``      — the cube; the only table the API reads.

Two constraint choices worth calling out
----------------------------------------
* The cube's unique key is ``NULLS NOT DISTINCT``. ``destination_entity_id`` is
  nullable and default Postgres semantics treat NULLs as never colliding, which
  would let duplicate cells slip past the exact guard this key exists to give
  (cf .claude/rules/timeseries-uniqueness.md — the cube backs cross-series
  ratios where a fan-out corrupts silently). Requires PG ≥ 15; prod Cloud SQL
  and the local container are both 15.
* ``pl_origin_flow_monthly.is_bean_equivalent`` is GENERATED from
  ``product_code`` so the solde formulas cannot re-list the product set and get
  it wrong (business-rules §2: bean-equivalent = FEVES | HORS_GRADE).

Idempotent: every CREATE uses ``if_not_exists=True``, safe to re-apply.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "n9c0d1e2f3g4"
# Head of `main` as of 2026-08-17 (farmgate sub-campaign, PR #92), which descends
# from the tenant/entitlement tables (PR #91). Both landed after this branch was
# cut, so this value was bumped from `m8b9c0d1e2f3` — chaining to the older head
# would leave two heads and break `alembic upgrade head` at the next Cloud Run
# cold start (.claude/rules/migrations-prod-via-main-only.md). Re-check it against
# `alembic heads` before merging, not after.
down_revision = "f1g2c3m4p5n6"
branch_labels = None
depends_on = None


# Canonical product taxonomy (business-rules §2). Kept in sync with
# app/models/origin.py::PRODUCT_CODES — the CHECK constraints below are the
# database-side enforcement of the same set.
PRODUCT_CODES = (
    "FEVES",
    "HORS_GRADE",
    "MASSE",
    "BEURRE",
    "POUDRE",
    "CHOCOLAT",
    "COQUES",
)
BEAN_EQUIVALENT_CODES = ("FEVES", "HORS_GRADE")

_PRODUCTS_SQL = ", ".join(f"'{c}'" for c in PRODUCT_CODES)
_BEANS_SQL = ", ".join(f"'{c}'" for c in BEAN_EQUIVALENT_CODES)


def _uuid_pk() -> sa.Column:
    return sa.Column(
        "id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )


def _batch_fk() -> sa.Column:
    """FK to the batch, ON DELETE CASCADE.

    Batch pruning (keep N=2 for restatement diffing) deletes whole batches;
    cascading is what makes that a single statement instead of a manual
    child-first teardown that can half-fail.
    """
    return sa.Column(
        "ingest_batch_id",
        UUID(as_uuid=True),
        sa.ForeignKey("pl_origin_ingest_batch.id", ondelete="CASCADE"),
        nullable=False,
    )


# ---------------------------------------------------------------------------
# upgrade
# ---------------------------------------------------------------------------
def upgrade() -> None:
    _create_ingest_batch()
    _create_origin_entity()
    _create_export_declaration()
    _create_purchase_monthly()
    _create_grinding_monthly()
    _create_flow_monthly()


def _create_ingest_batch() -> None:
    op.create_table(
        "pl_origin_ingest_batch",
        _uuid_pk(),
        # "files" — a plain folder holding the four masters, which is the
        # acquisition contract (decision #5). No deploy key, no bucket, no
        # credential, no dependency on WatchAI's repository: the CLI reads a path
        # on disk. "git" means that folder happened to be a checkout, so the
        # metadata below was captured too and a clean working tree was enforced.
        sa.Column("source", sa.VARCHAR(20), nullable=False, server_default="files"),
        # sha256 per source file — THE batch identity. Content-addressed on
        # purpose: pushing the data is an optional step in Julien's monthly
        # procedure (it ends at `scp` to his VPS, not at `git push`), so a commit
        # SHA can describe a different dataset than the one actually read.
        sa.Column(
            "source_hashes",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        # Bonus provenance — nullable because git is never required.
        sa.Column("source_ref", sa.VARCHAR(64), nullable=True),
        sa.Column("source_branch", sa.VARCHAR(120), nullable=True),
        sa.Column("source_committed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "ingested_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # Manual load = named human, never a service account.
        sa.Column("ingested_by", sa.VARCHAR(100), nullable=False),
        sa.Column(
            "row_counts", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        # Newest period across the three sources → the UI's "Données au <mois>".
        sa.Column("data_as_of", sa.DATE(), nullable=False),
        # NULL on the first load (nothing to diff); {} means nothing moved.
        sa.Column("restatement_summary", JSONB, nullable=True),
        # Source-quality counters that are reported, never fatal.
        sa.Column("quality_report", JSONB, nullable=True),
        sa.Column(
            "is_current", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.CheckConstraint("source IN ('git', 'files')", name="ck_origin_batch_source"),
        if_not_exists=True,
    )
    # At most one current batch. Partial unique index rather than application
    # discipline: the flip is a two-statement operation and a crash between them
    # must not be able to leave two current batches.
    op.create_index(
        "uq_origin_batch_current",
        "pl_origin_ingest_batch",
        ["is_current"],
        unique=True,
        postgresql_where=sa.text("is_current"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_origin_batch_ingested_at",
        "pl_origin_ingest_batch",
        [sa.text("ingested_at DESC")],
        if_not_exists=True,
    )


def _create_origin_entity() -> None:
    op.create_table(
        "ref_origin_entity",
        _uuid_pk(),
        sa.Column("entity_type", sa.VARCHAR(20), nullable=False),
        # WatchAI's *_SIMPLE value — their canonicalization, already applied in
        # the parquet. The raw customs name is not ingested (decision #7) and is
        # a literal "0" in the extract anyway.
        sa.Column("source_name", sa.VARCHAR(120), nullable=False),
        # Ours — a second normalization layer we control.
        sa.Column("canonical_name", sa.VARCHAR(120), nullable=False),
        sa.Column("country_code", sa.VARCHAR(2), nullable=True),
        # Config as data (decision #14): replaces the hardcoded 11-name GEPEX
        # list, editable without a deploy.
        sa.Column(
            "is_gepex_member",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        # False when the name appears in the extract but not in
        # Entity_Mappings.xlsx (47 exporters + 8 destinations today). Reported,
        # never fatal — the mapping file is not a complete universe.
        sa.Column(
            "in_entity_mappings",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "entity_type", "source_name", name="uq_origin_entity_source"
        ),
        sa.CheckConstraint(
            "entity_type IN ('exporter', 'destination')", name="ck_origin_entity_type"
        ),
        if_not_exists=True,
    )
    op.create_index(
        "ix_origin_entity_type_canonical",
        "ref_origin_entity",
        ["entity_type", "canonical_name"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_origin_entity_gepex",
        "ref_origin_entity",
        ["entity_type"],
        postgresql_where=sa.text("is_gepex_member"),
        if_not_exists=True,
    )


def _create_export_declaration() -> None:
    op.create_table(
        "pl_origin_export_declaration",
        _uuid_pk(),
        _batch_fk(),
        sa.Column("declaration_date", sa.DATE(), nullable=False),
        sa.Column("season", sa.VARCHAR(9), nullable=False),
        sa.Column(
            "exporter_entity_id",
            UUID(as_uuid=True),
            sa.ForeignKey("ref_origin_entity.id"),
            nullable=False,
        ),
        sa.Column(
            "destination_entity_id",
            UUID(as_uuid=True),
            sa.ForeignKey("ref_origin_entity.id"),
            nullable=True,
        ),
        sa.Column("port", sa.VARCHAR(20), nullable=False),
        sa.Column("postar", sa.VARCHAR(20), nullable=False),
        sa.Column("product_code", sa.VARCHAR(15), nullable=False),
        # Stored in kg exactly as the source ships it. The kg→tonne conversion
        # happens once, in the cube (business-rules §1).
        sa.Column("net_weight_kg", sa.BIGINT(), nullable=False),
        # FCFA absolute. NULL on every row before 2024 — the extract carries no
        # money data for 131 296 of 170 453 rows.
        sa.Column("valcaf", sa.NUMERIC(20, 4), nullable=True),
        sa.Column("duties_taxes", sa.NUMERIC(20, 4), nullable=True),
        sa.CheckConstraint("net_weight_kg >= 0", name="ck_origin_declaration_weight"),
        sa.CheckConstraint(
            f"product_code IN ({_PRODUCTS_SQL})", name="ck_origin_declaration_product"
        ),
        # No unique constraint by design: under snapshot semantics two identical
        # lines in one month are legitimate data, and DECLARATION is null on
        # 71 599 rows so there is no trustworthy line identifier.
        if_not_exists=True,
    )
    op.create_index(
        "ix_origin_declaration_batch_date",
        "pl_origin_export_declaration",
        ["ingest_batch_id", "declaration_date"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_origin_declaration_batch_season",
        "pl_origin_export_declaration",
        ["ingest_batch_id", "season"],
        if_not_exists=True,
    )


def _create_purchase_monthly() -> None:
    op.create_table(
        "pl_origin_purchase_monthly",
        _uuid_pk(),
        _batch_fk(),
        sa.Column("period_date", sa.DATE(), nullable=False),
        sa.Column("season", sa.VARCHAR(9), nullable=False),
        sa.Column(
            "exporter_entity_id",
            UUID(as_uuid=True),
            sa.ForeignKey("ref_origin_entity.id"),
            nullable=False,
        ),
        sa.Column("net_weight_kg", sa.NUMERIC(20, 4), nullable=False),
        # One row per natural key. The source ships up to 3 rows per
        # (exporter, month) because distinct raw customs names collapse onto one
        # EXPORTATEUR_SIMPLE; the writer sums them before insert.
        sa.UniqueConstraint(
            "ingest_batch_id",
            "period_date",
            "exporter_entity_id",
            name="uq_origin_purchase_monthly",
        ),
        sa.CheckConstraint("net_weight_kg >= 0", name="ck_origin_purchase_weight"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_origin_purchase_batch_season",
        "pl_origin_purchase_monthly",
        ["ingest_batch_id", "season"],
        if_not_exists=True,
    )


def _create_grinding_monthly() -> None:
    op.create_table(
        "pl_origin_grinding_monthly",
        _uuid_pk(),
        _batch_fk(),
        sa.Column("period_date", sa.DATE(), nullable=False),
        sa.Column("season", sa.VARCHAR(9), nullable=False),
        # Already in tonnes at source — must NOT be divided by 1000
        # (business-rules §1, the trap that webapp_tax.py:1919 flags).
        sa.Column("tons_ground", sa.NUMERIC(18, 4), nullable=False),
        sa.UniqueConstraint(
            "ingest_batch_id", "period_date", name="uq_origin_grinding_monthly"
        ),
        sa.CheckConstraint("tons_ground >= 0", name="ck_origin_grinding_tons"),
        if_not_exists=True,
    )


def _create_flow_monthly() -> None:
    op.create_table(
        "pl_origin_flow_monthly",
        _uuid_pk(),
        _batch_fk(),
        sa.Column("period_date", sa.DATE(), nullable=False),
        sa.Column("season", sa.VARCHAR(9), nullable=False),
        sa.Column(
            "exporter_entity_id",
            UUID(as_uuid=True),
            sa.ForeignKey("ref_origin_entity.id"),
            nullable=False,
        ),
        sa.Column("product_code", sa.VARCHAR(15), nullable=False),
        sa.Column(
            "destination_entity_id",
            UUID(as_uuid=True),
            sa.ForeignKey("ref_origin_entity.id"),
            nullable=True,
        ),
        sa.Column("port", sa.VARCHAR(20), nullable=False),
        # The single kg→tonne conversion point.
        sa.Column("export_tonnes", sa.NUMERIC(18, 6), nullable=False),
        sa.Column("valcaf", sa.NUMERIC(20, 4), nullable=True),
        sa.Column("duties_taxes", sa.NUMERIC(20, 4), nullable=True),
        # GENERATED so a query can never re-list the bean set and get it wrong.
        sa.Column(
            "is_bean_equivalent",
            sa.Boolean(),
            sa.Computed(f"product_code IN ({_BEANS_SQL})", persisted=True),
        ),
        sa.UniqueConstraint(
            "ingest_batch_id",
            "period_date",
            "exporter_entity_id",
            "product_code",
            "destination_entity_id",
            "port",
            name="uq_origin_flow_monthly",
            postgresql_nulls_not_distinct=True,
        ),
        sa.CheckConstraint("export_tonnes >= 0", name="ck_origin_flow_tonnes"),
        sa.CheckConstraint(
            f"product_code IN ({_PRODUCTS_SQL})", name="ck_origin_flow_product"
        ),
        if_not_exists=True,
    )
    op.create_index(
        "ix_origin_flow_batch_period",
        "pl_origin_flow_monthly",
        ["ingest_batch_id", "period_date"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_origin_flow_batch_season",
        "pl_origin_flow_monthly",
        ["ingest_batch_id", "season"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_origin_flow_exporter",
        "pl_origin_flow_monthly",
        ["ingest_batch_id", "exporter_entity_id"],
        if_not_exists=True,
    )


# ---------------------------------------------------------------------------
# downgrade
# ---------------------------------------------------------------------------
def downgrade() -> None:
    """Drop in FK-dependency order. Purely additive migration, so a downgrade
    returns the schema to exactly its prior state — no data of any other
    subsystem is involved."""
    op.drop_table("pl_origin_flow_monthly", if_exists=True)
    op.drop_table("pl_origin_grinding_monthly", if_exists=True)
    op.drop_table("pl_origin_purchase_monthly", if_exists=True)
    op.drop_table("pl_origin_export_declaration", if_exists=True)
    op.drop_table("ref_origin_entity", if_exists=True)
    op.drop_table("pl_origin_ingest_batch", if_exists=True)
