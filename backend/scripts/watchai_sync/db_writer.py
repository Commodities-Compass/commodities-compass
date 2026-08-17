"""Write one batch: entities, observations, cube, promotion, pruning.

Batch semantics are **full snapshot replace** (decision #8), not append. The
three upstream masters are rebuilt from scratch on each monthly run — Achats
re-reads every source workbook, Broyage regenerates 2012→present from one file —
so prior months legitimately change between loads. An append-per-month design
would be silently wrong on the first correction.

The consequence that matters commercially: history moves under clients who have
already seen it. Every load therefore diffs the new batch against the current
one and reports every month whose total shifted, before the flip.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

import pandas as pd
from psycopg2.extras import execute_values
from sqlalchemy import text
from sqlalchemy.orm import Session

from scripts.watchai_sync import config
from scripts.watchai_sync.acquire import SourceProvenance
from scripts.watchai_sync.errors import (
    CubeUniquenessError,
    RowCountRegressionError,
)
from scripts.watchai_sync.transform import EntityRecord, TransformedBatch

logger = logging.getLogger(__name__)

EntityIndex = dict[tuple[str, str], uuid.UUID]

# One month whose total moved: {"period": "2026-03-01", "previous": …,
# "current": …, "delta": …}. Typed as a mapping to object because it is a JSON
# blob, but the *shape* around it is precise so consumers can index it.
RestatementChange = dict[str, object]
# dataset label ("exports_tonnes" | "purchases_tonnes" | "grindings_tonnes")
# → the months that moved.
Restatement = dict[str, list[RestatementChange]]

# The natural key of one cube cell. Kept as a module constant so the INSERT, the
# uniqueness assert and the table constraint cannot drift apart.
_CUBE_KEY = (
    "period_date",
    "exporter_entity_id",
    "product_code",
    "destination_entity_id",
    "port",
)


@dataclass(frozen=True)
class BatchSummary:
    """What a completed load did — printed, and mirrored onto the batch row."""

    batch_id: uuid.UUID
    row_counts: dict[str, int]
    cube_rows: int
    restatement: Restatement | None
    previous_batch_id: uuid.UUID | None
    source_changes: dict[str, list[str]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# entities
# ---------------------------------------------------------------------------
def upsert_entities(session: Session, entities: Sequence[EntityRecord]) -> EntityIndex:
    """Upsert ``ref_origin_entity`` and return the (type, source_name) → id index.

    Entities are **not** batch-scoped: they are reference data that accumulates
    across loads. An exporter that disappears from the extract keeps its row (and
    its id), so historical batches retain valid foreign keys and a client's saved
    figures keep resolving.

    ``is_gepex_member`` is seeded on INSERT only. After the first load the column
    is authoritative and editable in-place (config as data), so re-seeding it on
    every run would silently revert an operator's correction.
    """
    if not entities:
        return {}

    rows = [
        (
            entity.entity_type,
            entity.source_name,
            entity.canonical_name,
            entity.country_code,
            entity.is_gepex_member,
            entity.in_entity_mappings,
        )
        for entity in entities
    ]
    connection = session.connection().connection
    with connection.cursor() as cursor:  # type: ignore[union-attr]
        execute_values(
            cursor,
            """
            INSERT INTO ref_origin_entity
                (entity_type, source_name, canonical_name, country_code,
                 is_gepex_member, in_entity_mappings)
            VALUES %s
            ON CONFLICT (entity_type, source_name) DO UPDATE
            SET canonical_name     = EXCLUDED.canonical_name,
                country_code       = COALESCE(EXCLUDED.country_code,
                                              ref_origin_entity.country_code),
                in_entity_mappings = EXCLUDED.in_entity_mappings
            """,
            rows,
            page_size=1000,
        )

    index: EntityIndex = {}
    for entity_type, source_name, entity_id in session.execute(
        text("SELECT entity_type, source_name, id FROM ref_origin_entity")
    ):
        index[(entity_type, source_name)] = entity_id
    logger.info("ref_origin_entity: %d rows upserted, %d total", len(rows), len(index))
    return index


# ---------------------------------------------------------------------------
# batch + observations
# ---------------------------------------------------------------------------
def insert_batch(
    session: Session,
    provenance: SourceProvenance,
    batch: TransformedBatch,
    ingested_by: str,
) -> uuid.UUID:
    """Create the provenance row. Written first so a crash mid-load is traceable."""
    quality = dict(batch.quality_report)
    git = provenance.git
    if git is not None and git.untracked_paths:
        quality["source_untracked_paths"] = list(git.untracked_paths)

    batch_id = session.execute(
        text(
            """
            INSERT INTO pl_origin_ingest_batch
                (source, source_hashes, source_ref, source_branch,
                 source_committed_at, ingested_by, row_counts, data_as_of,
                 quality_report, is_current)
            VALUES
                (:source, CAST(:source_hashes AS jsonb), :source_ref,
                 :source_branch, :committed_at, :ingested_by,
                 CAST(:row_counts AS jsonb), :data_as_of,
                 CAST(:quality AS jsonb), false)
            RETURNING id
            """
        ),
        {
            "source": provenance.kind,
            "source_hashes": json.dumps(provenance.file_hashes),
            "source_ref": git.commit_sha if git else None,
            "source_branch": git.branch if git else None,
            "committed_at": git.committed_at if git else None,
            "ingested_by": ingested_by,
            "row_counts": json.dumps(batch.row_counts),
            "data_as_of": batch.data_as_of,
            "quality": json.dumps(quality, default=str),
        },
    ).scalar_one()
    logger.info(
        "batch %s created (%s %s, data_as_of %s)",
        batch_id,
        provenance.kind,
        provenance.short_identity,
        batch.data_as_of.isoformat(),
    )
    return batch_id


def report_source_changes(
    session: Session,
    provenance: SourceProvenance,
    previous_batch_id: uuid.UUID | None,
) -> dict[str, list[str]]:
    """Compare source file hashes against the current batch's.

    This is the content-addressed replacement for pinning a commit: it answers
    "which of the four files actually changed since the last load?" without
    caring whether anyone committed. A file that changed is expected when a new
    month lands; a file that changed when you believed nothing had is the signal.

    Reported, never fatal — an unchanged set of hashes is a legitimate re-run, and
    a changed set is the normal monthly case. The restatement diff is what says
    whether the change moved any published figure.
    """
    if previous_batch_id is None:
        return {}
    previous = session.execute(
        text("SELECT source_hashes FROM pl_origin_ingest_batch WHERE id = :id"),
        {"id": previous_batch_id},
    ).scalar_one_or_none()
    if not previous:
        return {}

    changed = sorted(
        name
        for name, digest in provenance.file_hashes.items()
        if previous.get(name) not in (None, digest)
    )
    added = sorted(set(provenance.file_hashes) - set(previous))
    if changed:
        logger.info(
            "source file(s) changed since the current batch: %s", ", ".join(changed)
        )
    else:
        logger.info("source files are byte-identical to the current batch")
    return {"changed": changed, "added": added}


def write_observations(
    session: Session,
    batch_id: uuid.UUID,
    batch: TransformedBatch,
    entities: EntityIndex,
) -> None:
    """Insert the three observation tables for this batch."""
    _write_declarations(session, batch_id, batch.declarations, entities)
    _write_purchases(session, batch_id, batch.purchases, entities)
    _write_grindings(session, batch_id, batch.grindings)


def _write_declarations(
    session: Session,
    batch_id: uuid.UUID,
    frame: pd.DataFrame,
    entities: EntityIndex,
) -> None:
    rows = [
        (
            batch_id,
            declaration_date,
            season,
            entities[("exporter", exporter_name)],
            entities.get(("destination", destination_name))
            if destination_name
            else None,
            port,
            postar,
            product_code,
            int(net_weight_kg),
            _nullable_float(valcaf),
            _nullable_float(duties_taxes),
        )
        for (
            declaration_date,
            season,
            exporter_name,
            destination_name,
            port,
            postar,
            product_code,
            net_weight_kg,
            valcaf,
            duties_taxes,
        ) in _iter_columns(
            frame,
            "declaration_date",
            "season",
            "exporter_name",
            "destination_name",
            "port",
            "postar",
            "product_code",
            "net_weight_kg",
            "valcaf",
            "duties_taxes",
        )
    ]
    _bulk_insert(
        session,
        "pl_origin_export_declaration",
        (
            "ingest_batch_id",
            "declaration_date",
            "season",
            "exporter_entity_id",
            "destination_entity_id",
            "port",
            "postar",
            "product_code",
            "net_weight_kg",
            "valcaf",
            "duties_taxes",
        ),
        rows,
    )


def _write_purchases(
    session: Session,
    batch_id: uuid.UUID,
    frame: pd.DataFrame,
    entities: EntityIndex,
) -> None:
    rows = [
        (
            batch_id,
            period_date,
            season,
            entities[("exporter", exporter_name)],
            float(net_weight_kg),
        )
        for period_date, season, exporter_name, net_weight_kg in _iter_columns(
            frame, "period_date", "season", "exporter_name", "net_weight_kg"
        )
    ]
    _bulk_insert(
        session,
        "pl_origin_purchase_monthly",
        (
            "ingest_batch_id",
            "period_date",
            "season",
            "exporter_entity_id",
            "net_weight_kg",
        ),
        rows,
    )


def _write_grindings(
    session: Session, batch_id: uuid.UUID, frame: pd.DataFrame
) -> None:
    rows = [
        (batch_id, period_date, season, float(tons_ground))
        for period_date, season, tons_ground in _iter_columns(
            frame, "period_date", "season", "tons_ground"
        )
    ]
    _bulk_insert(
        session,
        "pl_origin_grinding_monthly",
        ("ingest_batch_id", "period_date", "season", "tons_ground"),
        rows,
    )


def _iter_columns(frame: pd.DataFrame, *names: str):
    """Iterate rows as tuples of the named columns, in the order given.

    Preferred over ``itertuples`` here because the column order of the SELECT is
    then written out at the call site next to the INSERT's column list — the two
    can be read against each other, which is exactly the drift
    .claude/rules/pipeline-continuity.md is about.
    """
    return zip(*(frame[name].tolist() for name in names), strict=True)


def _bulk_insert(
    session: Session,
    table: str,
    columns: tuple[str, ...],
    rows: list[tuple],
) -> None:
    """Multi-row INSERT via psycopg2 ``execute_values``.

    SQLAlchemy's executemany issues one statement per row against psycopg2, which
    turns 170k declarations into 170k round trips. ``execute_values`` batches
    them into a handful.
    """
    if not rows:
        logger.warning("%s: nothing to insert", table)
        return
    connection = session.connection().connection
    with connection.cursor() as cursor:  # type: ignore[union-attr]
        execute_values(
            cursor,
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES %s",
            rows,
            page_size=5000,
        )
    logger.info("%s: %d rows inserted", table, len(rows))


def _nullable_float(value: object) -> float | None:
    if value is None or pd.isna(value):  # type: ignore[arg-type]
        return None
    return float(value)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# cube
# ---------------------------------------------------------------------------
def compute_cube(session: Session, batch_id: uuid.UUID) -> int:
    """Collapse the line table into ``pl_origin_flow_monthly`` for this batch.

    Exports only. Purchases (exporter × month) and grindings (GEPEX aggregate ×
    month) live at coarser grains and are deliberately **not** joined in here —
    they are combined at query time (integration doc §5). The material balance
    that consumes them is bean-equivalent arithmetic, not a subtraction of raw
    tonnages: transformed exports are converted back via
    ``/ config.RENDEMENT_BROYAGE`` first (business-rules §4). Folding either
    series into the export grain would make that impossible to express correctly.

    ``SUM`` over ``valcaf`` / ``duties_taxes`` skips NULLs, which matches what
    WatchAI does and is what the published golden totals were computed with. On
    ``refonte-da-v2`` the absent money values are 0 rather than NULL, so the sums
    are identical either way — but 131 573 of 172 712 rows still carry no real
    money data, and an *average* over them must filter `> 1`, not `> 0`.
    """
    session.execute(
        text(
            f"""
            INSERT INTO pl_origin_flow_monthly
                (ingest_batch_id, period_date, season, exporter_entity_id,
                 product_code, destination_entity_id, port,
                 export_tonnes, valcaf, duties_taxes)
            SELECT
                :batch_id,
                DATE_TRUNC('month', declaration_date)::date,
                season,
                exporter_entity_id,
                product_code,
                destination_entity_id,
                port,
                SUM(net_weight_kg)::numeric / {config.KG_PER_TONNE},
                SUM(valcaf),
                SUM(duties_taxes)
            FROM pl_origin_export_declaration
            WHERE ingest_batch_id = :batch_id
            GROUP BY
                DATE_TRUNC('month', declaration_date),
                season,
                exporter_entity_id,
                product_code,
                destination_entity_id,
                port
            """
        ),
        {"batch_id": batch_id},
    )
    cube_rows = _scalar(
        session,
        "SELECT COUNT(*) FROM pl_origin_flow_monthly WHERE ingest_batch_id = :batch_id",
        {"batch_id": batch_id},
    )
    logger.info("cube: %d cells", int(cube_rows))
    assert_cube_integrity(session, batch_id)
    return int(cube_rows)


def assert_cube_integrity(session: Session, batch_id: uuid.UUID) -> None:
    """One row per natural key, and no mass created or lost.

    The UNIQUE constraint already blocks a duplicate at write time, but it is
    checked with ``NULLS NOT DISTINCT`` semantics that a future schema edit could
    weaken. This check re-states the invariant in the job itself, and the mass
    conservation half catches something the constraint cannot: an aggregation
    that silently drops or double-counts rows (cf .claude/rules/
    timeseries-uniqueness.md — a cube that looks clean while holding wrong
    numbers is exactly how the macroeco fan-out survived for months).
    """
    duplicate_keys = int(
        _scalar(
            session,
            f"""
            SELECT COUNT(*) FROM (
                SELECT 1
                FROM pl_origin_flow_monthly
                WHERE ingest_batch_id = :batch_id
                GROUP BY {", ".join(_CUBE_KEY)}
                HAVING COUNT(*) > 1
            ) AS duplicated
            """,
            {"batch_id": batch_id},
        )
    )
    if duplicate_keys:
        raise CubeUniquenessError(
            f"cube has {duplicate_keys} natural key(s) with more than one row. "
            "Every cross-series ratio built on this batch would be wrong."
        )

    source_kg, cube_tonnes = session.execute(
        text(
            """
            SELECT
                (SELECT COALESCE(SUM(net_weight_kg), 0)
                   FROM pl_origin_export_declaration
                  WHERE ingest_batch_id = :batch_id),
                (SELECT COALESCE(SUM(export_tonnes), 0)
                   FROM pl_origin_flow_monthly
                  WHERE ingest_batch_id = :batch_id)
            """
        ),
        {"batch_id": batch_id},
    ).one()
    expected = float(source_kg) / config.KG_PER_TONNE
    actual = float(cube_tonnes)
    if abs(expected - actual) > 1e-6:
        raise CubeUniquenessError(
            f"cube mass mismatch: declarations hold {expected:,.6f} t but the "
            f"cube holds {actual:,.6f} t (delta {actual - expected:+,.6f} t). "
            "The aggregation dropped or duplicated rows."
        )
    logger.info(
        "cube integrity OK — one row per natural key, %.3f t conserved from the "
        "line table",
        actual,
    )


# ---------------------------------------------------------------------------
# restatement diff
# ---------------------------------------------------------------------------
def diff_restatement(
    session: Session,
    new_batch_id: uuid.UUID,
    previous_batch_id: uuid.UUID | None,
) -> Restatement | None:
    """Report every month whose totals moved against the current batch.

    Returns ``None`` on the first-ever load (nothing to compare) and ``{}`` when
    nothing moved. A silent restatement of a season a client has already read is
    worse than a visibly late one, so this runs before the flip and is both
    printed and persisted.

    Diffing the observation tables rather than the cube keeps this meaningful
    under ``--skip-compute``, and covers purchases and grindings, which never
    reach the cube at all.
    """
    if previous_batch_id is None:
        return None

    moved: Restatement = {}
    for label, sql in _RESTATEMENT_QUERIES.items():
        rows = session.execute(
            text(sql),
            {"new_id": new_batch_id, "old_id": previous_batch_id},
        ).all()
        changes = [
            {
                "period": period.isoformat(),
                "previous": round(float(previous or 0), 3),
                "current": round(float(current or 0), 3),
                "delta": round(float(current or 0) - float(previous or 0), 3),
            }
            for period, previous, current in rows
            if abs(float(current or 0) - float(previous or 0))
            > config.RESTATEMENT_TOLERANCE_TONNES
        ]
        if changes:
            moved[label] = changes
    return moved


def _monthly_totals_diff(table: str, period_column: str, value_expression: str) -> str:
    """FULL OUTER JOIN of two batches' monthly totals — a month present in only
    one side shows up with the other side NULL, which is itself a restatement."""
    return f"""
        WITH old_totals AS (
            SELECT DATE_TRUNC('month', {period_column})::date AS period,
                   SUM({value_expression}) AS total
              FROM {table} WHERE ingest_batch_id = :old_id
             GROUP BY 1
        ), new_totals AS (
            SELECT DATE_TRUNC('month', {period_column})::date AS period,
                   SUM({value_expression}) AS total
              FROM {table} WHERE ingest_batch_id = :new_id
             GROUP BY 1
        )
        SELECT COALESCE(n.period, o.period) AS period, o.total, n.total
          FROM old_totals o
          FULL OUTER JOIN new_totals n ON n.period = o.period
         ORDER BY 1
    """


_RESTATEMENT_QUERIES: dict[str, str] = {
    "exports_tonnes": _monthly_totals_diff(
        "pl_origin_export_declaration",
        "declaration_date",
        f"net_weight_kg::numeric / {config.KG_PER_TONNE}",
    ),
    "purchases_tonnes": _monthly_totals_diff(
        "pl_origin_purchase_monthly",
        "period_date",
        f"net_weight_kg / {config.KG_PER_TONNE}",
    ),
    "grindings_tonnes": _monthly_totals_diff(
        "pl_origin_grinding_monthly", "period_date", "tons_ground"
    ),
}


def assert_no_row_count_regression(
    session: Session,
    new_counts: dict[str, int],
    previous_batch_id: uuid.UUID | None,
) -> None:
    """Refuse a batch that is materially smaller than the current one.

    Upstream restates history freely, so a small shrink is normal. A large one
    means a truncated or half-written source file — which would otherwise land
    as a perfectly legitimate-looking "everything moved" restatement.
    """
    if previous_batch_id is None:
        return
    previous = session.execute(
        text("SELECT row_counts FROM pl_origin_ingest_batch WHERE id = :id"),
        {"id": previous_batch_id},
    ).scalar_one_or_none()
    if not previous:
        return

    for dataset in ("declarations", "purchases", "grindings"):
        before = int(previous.get(dataset, 0))
        after = int(new_counts.get(dataset, 0))
        if before == 0:
            continue
        floor = before * (1 - config.ROW_COUNT_REGRESSION_TOLERANCE)
        if after < floor:
            raise RowCountRegressionError(
                f"{dataset}: {after:,} rows vs {before:,} in the current batch "
                f"({(after / before - 1) * 100:.1f}%). Beyond the "
                f"{config.ROW_COUNT_REGRESSION_TOLERANCE:.0%} tolerance — this "
                "looks like a truncated source file, not a restatement."
            )


# ---------------------------------------------------------------------------
# promotion + pruning
# ---------------------------------------------------------------------------
def current_batch_id(session: Session) -> uuid.UUID | None:
    return session.execute(
        text("SELECT id FROM pl_origin_ingest_batch WHERE is_current LIMIT 1")
    ).scalar_one_or_none()


def promote_batch(
    session: Session,
    batch_id: uuid.UUID,
    restatement: Restatement | None,
) -> None:
    """Make this batch the served one, recording the restatement alongside.

    Demote-then-promote order is required: a partial unique index enforces at
    most one current batch, so promoting first would collide.
    """
    session.execute(
        text("UPDATE pl_origin_ingest_batch SET is_current = false WHERE is_current")
    )
    session.execute(
        text(
            """
            UPDATE pl_origin_ingest_batch
               SET is_current = true,
                   restatement_summary = CAST(:restatement AS jsonb)
             WHERE id = :id
            """
        ),
        {
            "id": batch_id,
            "restatement": None if restatement is None else json.dumps(restatement),
        },
    )
    logger.info("batch %s promoted to current", batch_id)


def prune_batches(session: Session, keep: int = config.DEFAULT_KEEP_BATCHES) -> int:
    """Drop all but the newest ``keep`` batches. Children cascade.

    Keeping two is the minimum that lets the next run diff; the current batch is
    always among the newest so it can never be pruned.
    """
    deleted = int(
        _scalar(
            session,
            """
            WITH pruned AS (
                DELETE FROM pl_origin_ingest_batch
                 WHERE id NOT IN (
                    SELECT id FROM pl_origin_ingest_batch
                     ORDER BY ingested_at DESC, id DESC
                     LIMIT :keep
                 )
                RETURNING id
            )
            SELECT COUNT(*) FROM pruned
            """,
            {"keep": keep},
        )
    )
    if deleted:
        logger.info("pruned %d old batch(es), keeping %d", deleted, keep)
    return deleted


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _scalar(session: Session, sql: str, params: dict) -> float:
    return session.execute(text(sql), params).scalar_one()


def monthly_export_tonnes(session: Session, batch_id: uuid.UUID) -> dict[date, float]:
    """Per-month export tonnes from the cube — used by the reconciliation pass."""
    return {
        period: float(total)
        for period, total in session.execute(
            text(
                """
                SELECT period_date, SUM(export_tonnes)
                  FROM pl_origin_flow_monthly
                 WHERE ingest_batch_id = :batch_id
                 GROUP BY period_date
                 ORDER BY period_date
                """
            ),
            {"batch_id": batch_id},
        )
    }
