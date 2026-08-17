"""Origin physical-flow tables — Côte d'Ivoire customs exports, purchases, grindings.

Ingested from the WatchAI monthly parquet masters by ``poetry run watchai-sync``.
Design: docs/watchai/watchai-integration.md §3.

Two invariants shape every table here:

* **Snapshot, not ledger.** The three upstream masters are rebuilt from scratch
  on each monthly run (business-rules §12), so history legitimately moves
  between batches. Every observation row therefore carries an
  ``ingest_batch_id`` and the batch — not the row — is what gets replaced.
* **Nothing is contract-keyed.** This is physical-origin data, not market data.
  It never joins the daily ``DashboardDateContext``; the time grain is a month.

``pl_origin_flow_monthly`` is the only table the API is allowed to read
(decision #9). The line-level table exists so we own the transform, not because
a feature reads it.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    BIGINT,
    DATE,
    NUMERIC,
    TIMESTAMP,
    VARCHAR,
    Boolean,
    CheckConstraint,
    Computed,
    ForeignKey,
    Index,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

# Canonical product codes (business-rules §2). MASSE absorbs LIQUEUR/PATE at
# ingestion. COQUES is reachable only through the POSTAR fallback (1802) — the
# current extract labels every 1802 row HORS GRADE, so it never occurs today.
PRODUCT_CODES: tuple[str, ...] = (
    "FEVES",
    "HORS_GRADE",
    "MASSE",
    "BEURRE",
    "POUDRE",
    "CHOCOLAT",
    "COQUES",
)

# The solde formulas key on this set, never on a re-listed literal
# (business-rules §2: is_bean_equivalent = FEVES | HORS_GRADE).
BEAN_EQUIVALENT_CODES: tuple[str, ...] = ("FEVES", "HORS_GRADE")

_PRODUCT_CODES_SQL = ", ".join(f"'{code}'" for code in PRODUCT_CODES)
_BEAN_CODES_SQL = ", ".join(f"'{code}'" for code in BEAN_EQUIVALENT_CODES)

ENTITY_TYPES: tuple[str, ...] = ("exporter", "destination")
PORTS: tuple[str, ...] = ("ABIDJAN", "SAN PEDRO")


class PlOriginIngestBatch(Base):
    """Provenance of one manual ``watchai-sync`` load.

    With no Cloud Run execution to point at, this row *is* the record that the
    operation happened (integration doc §4, "Governance of the prod write").
    ``is_current`` is guarded by a partial unique index — at most one true row.

    Identity is ``source_hashes``, not the commit (decision #5). Pushing the data
    is an optional step in Julien's monthly procedure — it ends at ``scp`` to his
    VPS, not at ``git push`` — so a commit SHA can describe a different dataset
    than the one that was read. A content hash cannot.
    """

    __tablename__ = "pl_origin_ingest_batch"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    # "files" = a plain folder holding the four masters (the contract);
    # "git" = that folder happened to be a checkout, so we also captured the
    # metadata below and enforced a clean working tree.
    source: Mapped[str] = mapped_column(
        VARCHAR(20), nullable=False, server_default="files"
    )
    # sha256 per source file: {"Db_Master_Tax.parquet": "4da2…", …}. THE batch
    # identity — content-addressed, so it holds whether or not anyone committed.
    source_hashes: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # Bonus provenance, present only when the source folder was a git checkout.
    # Never required: Compass has no relationship with WatchAI's repository.
    source_ref: Mapped[Optional[str]] = mapped_column(VARCHAR(64))
    source_branch: Mapped[Optional[str]] = mapped_column(VARCHAR(120))
    source_committed_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True)
    )
    ingested_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    # Manual load = named human. No service account writes this table.
    ingested_by: Mapped[str] = mapped_column(VARCHAR(100), nullable=False)
    # {"declarations": 170453, "purchases": 3149, "grindings": 163, ...}
    row_counts: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # Newest period present across the three sources → what the UI stamps as
    # "Données au <mois>" (decision #15). Staleness is made visible, not alerted.
    data_as_of: Mapped[date] = mapped_column(DATE, nullable=False)
    # Months whose totals moved vs the previous current batch. NULL on the very
    # first load (nothing to diff against); {} means "nothing moved".
    restatement_summary: Mapped[Optional[dict]] = mapped_column(JSONB)
    # Source-quality counters that are reported, never fatal: entity names absent
    # from Entity_Mappings, sentinel VALCAF rows, precomputed-column mismatches.
    quality_report: Mapped[Optional[dict]] = mapped_column(JSONB)
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    __table_args__ = (
        # At most one current batch — the serving layer reads exactly this row.
        Index(
            "uq_origin_batch_current",
            "is_current",
            unique=True,
            postgresql_where=text("is_current"),
        ),
        Index("ix_origin_batch_ingested_at", text("ingested_at DESC")),
        CheckConstraint("source IN ('git', 'files')", name="ck_origin_batch_source"),
    )


class RefOriginEntity(Base):
    """Canonical exporters and destinations.

    ``source_name`` is WatchAI's ``*_SIMPLE`` value — their canonicalization,
    already applied upstream in the parquet. ``canonical_name`` is ours, a
    second normalization layer we control, so a future rename on their side
    does not fragment a client's flows.

    Seeded from the union of the parquet ``*_SIMPLE`` values and the
    ``Entity_Mappings.xlsx`` sheets: 47 exporters and 8 destinations present in
    the extract appear nowhere in the mapping file, so the mapping file alone is
    not a complete universe and cannot act as a gate.
    """

    __tablename__ = "ref_origin_entity"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    entity_type: Mapped[str] = mapped_column(VARCHAR(20), nullable=False)
    source_name: Mapped[str] = mapped_column(VARCHAR(120), nullable=False)
    canonical_name: Mapped[str] = mapped_column(VARCHAR(120), nullable=False)
    # ISO-2, destinations only. NULL for exporters and for unresolved labels.
    country_code: Mapped[Optional[str]] = mapped_column(VARCHAR(2))
    # Config as data (decision #14) — replaces WatchAI's hardcoded 11-name list,
    # editable without a deploy.
    is_gepex_member: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    # False when the name exists in the extract but not in Entity_Mappings.xlsx.
    # Reported, never fatal — see the batch quality_report.
    in_entity_mappings: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("entity_type", "source_name", name="uq_origin_entity_source"),
        CheckConstraint(
            "entity_type IN ('exporter', 'destination')",
            name="ck_origin_entity_type",
        ),
        Index("ix_origin_entity_type_canonical", "entity_type", "canonical_name"),
        Index(
            "ix_origin_entity_gepex",
            "entity_type",
            postgresql_where=text("is_gepex_member"),
        ),
    )


class PlOriginExportDeclaration(Base):
    """Line-level customs export declarations — reduced projection, 9 columns.

    Deliberately carries **no unique constraint**: under snapshot semantics two
    identical lines in the same month are legitimate data, and the source has no
    stable line identifier we can trust. ``DECLARATION`` is populated on 101 113
    of 172 712 rows (58,5 %) on ``refonte-da-v2`` and on 0 % on ``main`` — a
    partially populated key is *less* usable than a uniformly empty one, so do
    not be tempted to key on it now that it is partly filled
    (business-rules §13).

    Weights are stored in **kg** exactly as the source ships them; the kg→tonne
    conversion happens once, in the cube (business-rules §1: convert at the edge,
    never inside a formula).
    """

    __tablename__ = "pl_origin_export_declaration"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    ingest_batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pl_origin_ingest_batch.id", ondelete="CASCADE"), nullable=False
    )
    declaration_date: Mapped[date] = mapped_column(DATE, nullable=False)
    season: Mapped[str] = mapped_column(VARCHAR(9), nullable=False)
    exporter_entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ref_origin_entity.id"), nullable=False
    )
    destination_entity_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("ref_origin_entity.id")
    )
    port: Mapped[str] = mapped_column(VARCHAR(20), nullable=False)
    postar: Mapped[str] = mapped_column(VARCHAR(20), nullable=False)
    product_code: Mapped[str] = mapped_column(VARCHAR(15), nullable=False)
    net_weight_kg: Mapped[int] = mapped_column(BIGINT, nullable=False)
    # FCFA, absolute. Nullable, but on ``refonte-da-v2`` the absent values are
    # encoded as 0 rather than NULL (they were NULL on ``main``): 131 573 of
    # 172 712 rows carry no real money data, essentially everything before the
    # 2023-2024 season. Sums are unaffected — 0 contributes nothing and NULL was
    # skipped — but any *average* must filter `valcaf > 1`, not `> 0`.
    valcaf: Mapped[Optional[float]] = mapped_column(NUMERIC(20, 4))
    duties_taxes: Mapped[Optional[float]] = mapped_column(NUMERIC(20, 4))

    __table_args__ = (
        CheckConstraint("net_weight_kg >= 0", name="ck_origin_declaration_weight"),
        CheckConstraint(
            f"product_code IN ({_PRODUCT_CODES_SQL})",
            name="ck_origin_declaration_product",
        ),
        Index(
            "ix_origin_declaration_batch_date", "ingest_batch_id", "declaration_date"
        ),
        Index("ix_origin_declaration_batch_season", "ingest_batch_id", "season"),
    )


class PlOriginPurchaseMonthly(Base):
    """Monthly purchases per exporter (Db_Master_Achats).

    Coarser grain than exports — exporter × month, no product/destination/port
    dimension. Kept in its own table and combined at query time; folding it into
    the export grain is the fan-out class [timeseries-uniqueness] exists to stop.

    The source ships up to 3 rows per (exporter, month) because distinct raw
    customs names collapse onto one ``EXPORTATEUR_SIMPLE`` (192 such keys on
    ``11336ef``); the writer sums them so this table holds exactly one row per
    natural key.
    """

    __tablename__ = "pl_origin_purchase_monthly"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    ingest_batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pl_origin_ingest_batch.id", ondelete="CASCADE"), nullable=False
    )
    period_date: Mapped[date] = mapped_column(DATE, nullable=False)
    season: Mapped[str] = mapped_column(VARCHAR(9), nullable=False)
    exporter_entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ref_origin_entity.id"), nullable=False
    )
    net_weight_kg: Mapped[float] = mapped_column(NUMERIC(20, 4), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "ingest_batch_id",
            "period_date",
            "exporter_entity_id",
            name="uq_origin_purchase_monthly",
        ),
        CheckConstraint("net_weight_kg >= 0", name="ck_origin_purchase_weight"),
        Index("ix_origin_purchase_batch_season", "ingest_batch_id", "season"),
    )


class PlOriginGrindingMonthly(Base):
    """GEPEX-aggregate grindings (Db_Master_Broyage, STATSER source).

    **No exporter dimension** — this series is always a GEPEX aggregate, so
    transformation is not attributable per operator (business-rules §7). Never
    join it onto per-exporter export rows.

    **It is no longer an input to the material balance.** business-rules §4-§5:
    the balance derives grinding from transformed exports
    (``transfo_exporte_t / RENDEMENT_BROYAGE``) and STATSER is *confronted*
    against that derived figure, the gap being published as a consistency signal.
    Two consequences: the GEPEX-perimeter bias now affects only that
    confrontation rather than the balance, and the balance recovers the 2-3
    months STATSER lags by — it stops at 2026-04 while the other two sources run
    to 2026-07.

    ``tons_ground`` is stored **in tonnes**: the source column is already in
    tonnes and must not be divided by 1000 (business-rules §1).
    """

    __tablename__ = "pl_origin_grinding_monthly"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    ingest_batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pl_origin_ingest_batch.id", ondelete="CASCADE"), nullable=False
    )
    period_date: Mapped[date] = mapped_column(DATE, nullable=False)
    season: Mapped[str] = mapped_column(VARCHAR(9), nullable=False)
    tons_ground: Mapped[float] = mapped_column(NUMERIC(18, 4), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "ingest_batch_id", "period_date", name="uq_origin_grinding_monthly"
        ),
        CheckConstraint("tons_ground >= 0", name="ck_origin_grinding_tons"),
    )


class PlOriginFlowMonthly(Base):
    """THE CUBE — monthly export flows. The only table the API reads.

    Exports only: purchases and grindings live at coarser grains and are carried
    separately (integration doc §5).

    ``export_tonnes`` is the kg→tonne conversion applied exactly once, here.
    ``is_bean_equivalent`` is a GENERATED column so the solde formulas can never
    re-list the product set and get it wrong.

    The unique key uses ``NULLS NOT DISTINCT``: ``destination_entity_id`` is
    nullable, and under default Postgres semantics NULLs never collide — which
    would silently let duplicate cells through the very guard this constraint
    exists to provide.
    """

    __tablename__ = "pl_origin_flow_monthly"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    ingest_batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pl_origin_ingest_batch.id", ondelete="CASCADE"), nullable=False
    )
    period_date: Mapped[date] = mapped_column(DATE, nullable=False)
    season: Mapped[str] = mapped_column(VARCHAR(9), nullable=False)
    exporter_entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ref_origin_entity.id"), nullable=False
    )
    product_code: Mapped[str] = mapped_column(VARCHAR(15), nullable=False)
    destination_entity_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("ref_origin_entity.id")
    )
    port: Mapped[str] = mapped_column(VARCHAR(20), nullable=False)
    export_tonnes: Mapped[float] = mapped_column(NUMERIC(18, 6), nullable=False)
    valcaf: Mapped[Optional[float]] = mapped_column(NUMERIC(20, 4))
    duties_taxes: Mapped[Optional[float]] = mapped_column(NUMERIC(20, 4))
    is_bean_equivalent: Mapped[bool] = mapped_column(
        Boolean,
        Computed(f"product_code IN ({_BEAN_CODES_SQL})", persisted=True),
    )

    __table_args__ = (
        UniqueConstraint(
            "ingest_batch_id",
            "period_date",
            "exporter_entity_id",
            "product_code",
            "destination_entity_id",
            "port",
            name="uq_origin_flow_monthly",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint("export_tonnes >= 0", name="ck_origin_flow_tonnes"),
        CheckConstraint(
            f"product_code IN ({_PRODUCT_CODES_SQL})", name="ck_origin_flow_product"
        ),
        Index("ix_origin_flow_batch_period", "ingest_batch_id", "period_date"),
        Index("ix_origin_flow_batch_season", "ingest_batch_id", "season"),
        Index("ix_origin_flow_exporter", "ingest_batch_id", "exporter_entity_id"),
    )
