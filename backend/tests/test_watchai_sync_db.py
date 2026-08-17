"""Database-backed tests for the WatchAI writer, cube and restatement diff.

The invariants under test are the ones that fail *silently* in production:
a cube fan-out (wrong ratios, clean-looking table), a restated month nobody
reported, and a truncated source file landing as a legitimate snapshot.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from scripts.watchai_sync import db_writer, reconciliation
from scripts.watchai_sync.acquire import (
    SOURCE_FILES,
    SOURCE_GIT,
    GitMetadata,
    SourceProvenance,
)
from scripts.watchai_sync.errors import (
    CubeUniquenessError,
    ReconciliationError,
    RowCountRegressionError,
)
from scripts.watchai_sync.transform import EntityRecord, TransformedBatch

KG = 1000


# ---------------------------------------------------------------------------
# builders
# ---------------------------------------------------------------------------
def _provenance(sha: str = "a" * 40, kind: str = SOURCE_GIT) -> SourceProvenance:
    """Provenance whose identity is the file hashes; git metadata is a bonus.

    ``sha`` doubles as the distinguishing token between batches in these tests,
    so it also seeds the hashes — mirroring reality, where a different dataset
    means different hashes whether or not anyone committed.
    """
    git = (
        GitMetadata(
            commit_sha=sha,
            committed_at=datetime(2026, 8, 14, 18, 3, tzinfo=timezone.utc),
            branch="refonte-da-v2",
            untracked_paths=(),
        )
        if kind == SOURCE_GIT
        else None
    )
    return SourceProvenance(
        root=Path("/tmp/watch-ai"),
        kind=kind,
        file_hashes={name: f"{sha}{name}" for name in ("tax", "achats", "broyage")},
        git=git,
    )


def _entities() -> tuple[EntityRecord, ...]:
    return (
        EntityRecord("exporter", "CARGILL", "CARGILL", True, True),
        EntityRecord("exporter", "BARRY", "BARRY", True, True),
        EntityRecord("exporter", "NEWCO", "NEWCO", False, False),
        EntityRecord("destination", "PAYS-BAS", "PAYS-BAS", False, True),
    )


def _batch(
    declarations: list[dict] | None = None,
    purchases: list[dict] | None = None,
    grindings: list[dict] | None = None,
) -> TransformedBatch:
    declaration_rows = (
        declarations
        if declarations is not None
        else [
            {
                "declaration_date": date(2026, 3, 10),
                "season": "2025-2026",
                "exporter_name": "CARGILL",
                "destination_name": "PAYS-BAS",
                "port": "ABIDJAN",
                "postar": "1801001100",
                "product_code": "FEVES",
                "net_weight_kg": 100_000,
                "valcaf": 200_000_000.0,
                "duties_taxes": 20_000_000.0,
            },
            {
                # Same cell as above — must collapse into one cube row.
                "declaration_date": date(2026, 3, 20),
                "season": "2025-2026",
                "exporter_name": "CARGILL",
                "destination_name": "PAYS-BAS",
                "port": "ABIDJAN",
                "postar": "1801001100",
                "product_code": "FEVES",
                "net_weight_kg": 50_000,
                "valcaf": 100_000_000.0,
                "duties_taxes": 10_000_000.0,
            },
            {
                "declaration_date": date(2026, 3, 12),
                "season": "2025-2026",
                "exporter_name": "BARRY",
                "destination_name": "",  # nullable destination
                "port": "SAN PEDRO",
                "postar": "1803100000",
                "product_code": "MASSE",
                "net_weight_kg": 25_000,
                "valcaf": None,
                "duties_taxes": None,
            },
        ]
    )
    purchase_rows = (
        purchases
        if purchases is not None
        else [
            {
                "period_date": date(2026, 3, 1),
                "season": "2025-2026",
                "exporter_name": "CARGILL",
                "net_weight_kg": 500_000.0,
            }
        ]
    )
    grinding_rows = (
        grindings
        if grindings is not None
        else [
            {
                "period_date": date(2026, 3, 1),
                "season": "2025-2026",
                "tons_ground": 55_000.0,
            }
        ]
    )

    declarations_frame = pd.DataFrame(declaration_rows)
    return TransformedBatch(
        entities=_entities(),
        declarations=declarations_frame,
        purchases=pd.DataFrame(purchase_rows),
        grindings=pd.DataFrame(grinding_rows),
        data_as_of=date(2026, 3, 31),
        row_counts={
            "declarations": len(declaration_rows),
            "purchases": len(purchase_rows),
            "grindings": len(grinding_rows),
            "entities": len(_entities()),
        },
        quality_report={},
    )


def _load(
    session: Session,
    batch: TransformedBatch | None = None,
    sha: str = "a" * 40,
    compute: bool = True,
) -> uuid.UUID:
    """Run the writer end to end, mirroring what main._load does."""
    payload = batch or _batch()
    entities = db_writer.upsert_entities(session, payload.entities)
    batch_id = db_writer.insert_batch(session, _provenance(sha), payload, "pytest")
    db_writer.write_observations(session, batch_id, payload, entities)
    if compute:
        db_writer.compute_cube(session, batch_id)
    return batch_id


@pytest.fixture(autouse=True)
def _clean_origin_tables(sync_db_session: Session):
    """Other suites share the database; start from an empty origin schema.

    The session fixture rolls back afterwards, so this only scopes the fixture's
    own transaction.
    """
    sync_db_session.execute(text("DELETE FROM pl_origin_ingest_batch"))
    sync_db_session.execute(text("DELETE FROM ref_origin_entity"))
    yield


# ---------------------------------------------------------------------------
# cube
# ---------------------------------------------------------------------------
def test_cube_collapses_lines_into_monthly_cells(sync_db_session: Session) -> None:
    batch_id = _load(sync_db_session)

    cells = sync_db_session.execute(
        text(
            """
            SELECT period_date, product_code, port, export_tonnes
              FROM pl_origin_flow_monthly
             WHERE ingest_batch_id = :b ORDER BY product_code
            """
        ),
        {"b": batch_id},
    ).all()

    assert len(cells) == 2  # two CARGILL/FEVES lines merged, BARRY/MASSE separate
    feves = next(c for c in cells if c.product_code == "FEVES")
    assert float(feves.export_tonnes) == pytest.approx(150.0)  # (100k + 50k) kg
    assert feves.period_date == date(2026, 3, 1)  # month grain


def test_cube_applies_the_kg_to_tonne_conversion_exactly_once(
    sync_db_session: Session,
) -> None:
    """business-rules §1 — convert at the edge, never inside a formula."""
    batch_id = _load(sync_db_session)

    source_kg, cube_tonnes = sync_db_session.execute(
        text(
            """
            SELECT (SELECT SUM(net_weight_kg) FROM pl_origin_export_declaration
                     WHERE ingest_batch_id = :b),
                   (SELECT SUM(export_tonnes) FROM pl_origin_flow_monthly
                     WHERE ingest_batch_id = :b)
            """
        ),
        {"b": batch_id},
    ).one()
    assert float(cube_tonnes) == pytest.approx(float(source_kg) / KG)


def test_cube_money_columns_skip_nulls(sync_db_session: Session) -> None:
    """77% of real declarations carry no money data; SUM ignoring NULLs is what
    the published golden totals were computed with."""
    batch_id = _load(sync_db_session)

    feves_valcaf, masse_valcaf = sync_db_session.execute(
        text(
            """
            SELECT
              (SELECT valcaf FROM pl_origin_flow_monthly
                WHERE ingest_batch_id = :b AND product_code = 'FEVES'),
              (SELECT valcaf FROM pl_origin_flow_monthly
                WHERE ingest_batch_id = :b AND product_code = 'MASSE')
            """
        ),
        {"b": batch_id},
    ).one()
    assert float(feves_valcaf) == pytest.approx(300_000_000.0)
    assert masse_valcaf is None


def test_is_bean_equivalent_is_generated_from_product_code(
    sync_db_session: Session,
) -> None:
    """A GENERATED column so no query can re-list the bean set and get it wrong."""
    batch_id = _load(sync_db_session)

    flags = dict(
        sync_db_session.execute(
            text(
                "SELECT product_code, is_bean_equivalent FROM pl_origin_flow_monthly "
                "WHERE ingest_batch_id = :b"
            ),
            {"b": batch_id},
        ).all()
    )
    assert flags == {"FEVES": True, "MASSE": False}


def test_cube_tolerates_a_null_destination(sync_db_session: Session) -> None:
    batch_id = _load(sync_db_session)
    null_destination = db_writer._scalar(
        sync_db_session,
        "SELECT COUNT(*) FROM pl_origin_flow_monthly "
        "WHERE ingest_batch_id = :b AND destination_entity_id IS NULL",
        {"b": batch_id},
    )
    assert int(null_destination) == 1


def test_duplicate_cube_cell_is_rejected_by_the_unique_key(
    sync_db_session: Session,
) -> None:
    """NULLS NOT DISTINCT — under default Postgres semantics two rows with a NULL
    destination would not collide, and the guard would be useless exactly where
    it matters."""
    batch_id = _load(sync_db_session)

    with pytest.raises(Exception) as excinfo:
        sync_db_session.execute(
            text(
                """
                INSERT INTO pl_origin_flow_monthly
                    (ingest_batch_id, period_date, season, exporter_entity_id,
                     product_code, destination_entity_id, port, export_tonnes)
                SELECT ingest_batch_id, period_date, season, exporter_entity_id,
                       product_code, destination_entity_id, port, export_tonnes
                  FROM pl_origin_flow_monthly
                 WHERE ingest_batch_id = :b AND destination_entity_id IS NULL
                """
            ),
            {"b": batch_id},
        )
    assert "uq_origin_flow_monthly" in str(excinfo.value)


def test_cube_integrity_detects_lost_mass(sync_db_session: Session) -> None:
    """The uniqueness check alone cannot catch an aggregation that drops rows —
    the mass-conservation half is what makes the guard complete."""
    batch_id = _load(sync_db_session)
    sync_db_session.execute(
        text(
            "DELETE FROM pl_origin_flow_monthly "
            "WHERE ingest_batch_id = :b AND product_code = 'MASSE'"
        ),
        {"b": batch_id},
    )

    with pytest.raises(CubeUniquenessError, match="mass mismatch"):
        db_writer.assert_cube_integrity(sync_db_session, batch_id)


def test_skip_compute_leaves_the_cube_empty(sync_db_session: Session) -> None:
    batch_id = _load(sync_db_session, compute=False)
    assert (
        int(
            db_writer._scalar(
                sync_db_session,
                "SELECT COUNT(*) FROM pl_origin_flow_monthly WHERE ingest_batch_id = :b",
                {"b": batch_id},
            )
        )
        == 0
    )


# ---------------------------------------------------------------------------
# grain separation (business-rules §4)
# ---------------------------------------------------------------------------
def test_grindings_carry_no_exporter_dimension(sync_db_session: Session) -> None:
    """STATSER grinding is always a GEPEX aggregate. An exporter column would
    invite the join that biases every transformation ratio by ~3×."""
    columns = {
        row[0]
        for row in sync_db_session.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'pl_origin_grinding_monthly'"
            )
        )
    }
    assert "exporter_entity_id" not in columns


def test_grindings_are_not_folded_into_the_cube(sync_db_session: Session) -> None:
    """The cube is exports only; grinding stays at its own grain and is combined
    at query time on the GEPEX perimeter."""
    batch_id = _load(sync_db_session)
    cube_total = db_writer._scalar(
        sync_db_session,
        "SELECT COALESCE(SUM(export_tonnes), 0) FROM pl_origin_flow_monthly "
        "WHERE ingest_batch_id = :b",
        {"b": batch_id},
    )
    assert float(cube_total) == pytest.approx(175.0)  # exports only, no 55 000 t


# ---------------------------------------------------------------------------
# entities
# ---------------------------------------------------------------------------
def test_entities_are_not_duplicated_across_batches(sync_db_session: Session) -> None:
    _load(sync_db_session, sha="a" * 40)
    _load(sync_db_session, sha="b" * 40)

    assert int(
        db_writer._scalar(sync_db_session, "SELECT COUNT(*) FROM ref_origin_entity", {})
    ) == len(_entities())


def test_operator_edited_gepex_flag_survives_a_reload(sync_db_session: Session) -> None:
    """is_gepex_member is config-as-data: seeded on insert, then authoritative.
    Re-seeding on every run would silently revert an operator's correction."""
    _load(sync_db_session, sha="a" * 40)
    sync_db_session.execute(
        text(
            "UPDATE ref_origin_entity SET is_gepex_member = true "
            "WHERE source_name = 'NEWCO'"
        )
    )

    _load(sync_db_session, sha="b" * 40)

    still_member = db_writer._scalar(
        sync_db_session,
        "SELECT COUNT(*) FROM ref_origin_entity "
        "WHERE source_name = 'NEWCO' AND is_gepex_member",
        {},
    )
    assert int(still_member) == 1


# ---------------------------------------------------------------------------
# restatement diff (integration doc §4 step 5)
# ---------------------------------------------------------------------------
def test_first_batch_has_no_restatement(sync_db_session: Session) -> None:
    batch_id = _load(sync_db_session)
    assert db_writer.diff_restatement(sync_db_session, batch_id, None) is None


def test_identical_reload_reports_no_restatement(sync_db_session: Session) -> None:
    first = _load(sync_db_session, sha="a" * 40)
    db_writer.promote_batch(sync_db_session, first, None)
    second = _load(sync_db_session, sha="b" * 40)

    assert db_writer.diff_restatement(sync_db_session, second, first) == {}


def test_moved_month_is_detected_and_quantified(sync_db_session: Session) -> None:
    """History moves between batches by design (business-rules §12). A silently
    restated figure a client has already read is worse than a visibly late one."""
    first = _load(sync_db_session, sha="a" * 40)
    db_writer.promote_batch(sync_db_session, first, None)

    restated = _batch()
    restated.declarations.loc[0, "net_weight_kg"] = 900_000  # was 100 000
    second = _load(sync_db_session, restated, sha="b" * 40)

    diff = db_writer.diff_restatement(sync_db_session, second, first)

    assert diff is not None
    changes = diff["exports_tonnes"]
    assert len(changes) == 1
    assert changes[0]["period"] == "2026-03-01"
    assert changes[0]["delta"] == pytest.approx(800.0)


def test_new_month_appears_as_a_restatement(sync_db_session: Session) -> None:
    """A month present in only one batch shows up with the other side at zero."""
    first = _load(sync_db_session, sha="a" * 40)
    db_writer.promote_batch(sync_db_session, first, None)

    extended = _batch()
    extra = extended.declarations.iloc[[0]].copy()
    extra["declaration_date"] = date(2026, 4, 5)
    extended = TransformedBatch(
        entities=extended.entities,
        declarations=pd.concat([extended.declarations, extra], ignore_index=True),
        purchases=extended.purchases,
        grindings=extended.grindings,
        data_as_of=date(2026, 4, 30),
        row_counts={**extended.row_counts, "declarations": 4},
        quality_report={},
    )
    second = _load(sync_db_session, extended, sha="b" * 40)

    diff = db_writer.diff_restatement(sync_db_session, second, first)
    assert diff is not None
    periods = {c["period"] for c in diff["exports_tonnes"]}
    assert "2026-04-01" in periods


def test_purchases_and_grindings_are_diffed_too(sync_db_session: Session) -> None:
    """They never reach the cube, so diffing the observation tables rather than
    the cube is what keeps them covered."""
    first = _load(sync_db_session, sha="a" * 40)
    db_writer.promote_batch(sync_db_session, first, None)

    moved = _batch(
        grindings=[
            {
                "period_date": date(2026, 3, 1),
                "season": "2025-2026",
                "tons_ground": 61_000.0,
            }
        ]
    )
    second = _load(sync_db_session, moved, sha="b" * 40)

    diff = db_writer.diff_restatement(sync_db_session, second, first)
    assert diff is not None
    assert diff["grindings_tonnes"][0]["delta"] == pytest.approx(6_000.0)


# ---------------------------------------------------------------------------
# regression guard
# ---------------------------------------------------------------------------
def test_truncated_source_is_refused(sync_db_session: Session) -> None:
    """A half-written source file would otherwise land as a perfectly
    legitimate-looking 'everything shrank' restatement."""
    first = _load(sync_db_session, sha="a" * 40)
    db_writer.promote_batch(sync_db_session, first, None)

    with pytest.raises(RowCountRegressionError, match="truncated"):
        db_writer.assert_no_row_count_regression(
            sync_db_session,
            {"declarations": 1, "purchases": 1, "grindings": 1},
            first,
        )


def test_small_shrink_is_allowed(sync_db_session: Session) -> None:
    """Upstream restates history freely; a tiny shrink is normal, not a failure."""
    first = _load(sync_db_session, sha="a" * 40)
    db_writer.promote_batch(sync_db_session, first, None)

    db_writer.assert_no_row_count_regression(
        sync_db_session, {"declarations": 3, "purchases": 1, "grindings": 1}, first
    )


def test_no_previous_batch_means_no_regression_check(sync_db_session: Session) -> None:
    db_writer.assert_no_row_count_regression(sync_db_session, {"declarations": 0}, None)


# ---------------------------------------------------------------------------
# promotion + pruning
# ---------------------------------------------------------------------------
def test_exactly_one_batch_is_ever_current(sync_db_session: Session) -> None:
    first = _load(sync_db_session, sha="a" * 40)
    db_writer.promote_batch(sync_db_session, first, None)
    second = _load(sync_db_session, sha="b" * 40)
    db_writer.promote_batch(sync_db_session, second, {})

    current = sync_db_session.execute(
        text("SELECT id FROM pl_origin_ingest_batch WHERE is_current")
    ).all()
    assert len(current) == 1
    assert current[0].id == second
    assert db_writer.current_batch_id(sync_db_session) == second


def test_restatement_summary_is_persisted_on_the_batch(
    sync_db_session: Session,
) -> None:
    """With no Cloud Run execution to point at, the batch row is the only record
    the operation happened — and the only trace of what moved."""
    batch_id = _load(sync_db_session)
    db_writer.promote_batch(
        sync_db_session, batch_id, {"exports_tonnes": [{"period": "2026-03-01"}]}
    )

    stored = sync_db_session.execute(
        text("SELECT restatement_summary FROM pl_origin_ingest_batch WHERE id = :b"),
        {"b": batch_id},
    ).scalar_one()
    assert stored["exports_tonnes"][0]["period"] == "2026-03-01"


def test_pruning_keeps_the_newest_batches_and_cascades(
    sync_db_session: Session,
) -> None:
    for index, sha in enumerate("abc"):
        batch_id = _load(sync_db_session, sha=sha * 40)
        sync_db_session.execute(
            text("UPDATE pl_origin_ingest_batch SET ingested_at = :t WHERE id = :b"),
            {"t": datetime(2026, 3, 1 + index, tzinfo=timezone.utc), "b": batch_id},
        )

    db_writer.prune_batches(sync_db_session, keep=2)

    assert (
        int(
            db_writer._scalar(
                sync_db_session, "SELECT COUNT(*) FROM pl_origin_ingest_batch", {}
            )
        )
        == 2
    )
    # Children of the pruned batch went with it.
    orphans = db_writer._scalar(
        sync_db_session,
        "SELECT COUNT(*) FROM pl_origin_export_declaration d "
        "WHERE NOT EXISTS (SELECT 1 FROM pl_origin_ingest_batch b WHERE b.id = d.ingest_batch_id)",
        {},
    )
    assert int(orphans) == 0


def test_untracked_source_paths_are_recorded_on_the_batch(
    sync_db_session: Session,
) -> None:
    payload = _batch()
    entities = db_writer.upsert_entities(sync_db_session, payload.entities)
    provenance = SourceProvenance(
        root=Path("/tmp/watch-ai"),
        kind=SOURCE_GIT,
        file_hashes={"tax": "c" * 64},
        git=GitMetadata(
            commit_sha="c" * 40,
            committed_at=datetime(2026, 8, 14, tzinfo=timezone.utc),
            branch="refonte-da-v2",
            untracked_paths=(".env.example",),
        ),
    )
    batch_id = db_writer.insert_batch(sync_db_session, provenance, payload, "pytest")
    db_writer.write_observations(sync_db_session, batch_id, payload, entities)

    quality = sync_db_session.execute(
        text("SELECT quality_report FROM pl_origin_ingest_batch WHERE id = :b"),
        {"b": batch_id},
    ).scalar_one()
    assert quality["source_untracked_paths"] == [".env.example"]


# ---------------------------------------------------------------------------
# source identity (decision #5)
# ---------------------------------------------------------------------------
def test_batch_records_the_file_hashes_as_its_identity(
    sync_db_session: Session,
) -> None:
    batch_id = _load(sync_db_session)

    row = sync_db_session.execute(
        text(
            "SELECT source, source_hashes, source_ref, source_branch "
            "FROM pl_origin_ingest_batch WHERE id = :b"
        ),
        {"b": batch_id},
    ).one()
    assert row.source == "git"
    assert row.source_hashes  # the identity
    assert row.source_branch == "refonte-da-v2"
    assert row.source_ref == "a" * 40  # bonus metadata


def test_a_plain_folder_batch_records_no_git_metadata(sync_db_session: Session) -> None:
    """Compass has no relationship with WatchAI's repository: a load from a plain
    folder is a first-class case, not a degraded one."""
    payload = _batch()
    entities = db_writer.upsert_entities(sync_db_session, payload.entities)
    batch_id = db_writer.insert_batch(
        sync_db_session, _provenance(kind=SOURCE_FILES), payload, "pytest"
    )
    db_writer.write_observations(sync_db_session, batch_id, payload, entities)

    row = sync_db_session.execute(
        text(
            "SELECT source, source_ref, source_branch, source_committed_at, "
            "source_hashes FROM pl_origin_ingest_batch WHERE id = :b"
        ),
        {"b": batch_id},
    ).one()
    assert row.source == "files"
    assert (row.source_ref, row.source_branch, row.source_committed_at) == (
        None,
        None,
        None,
    )
    assert row.source_hashes


def test_unchanged_source_files_are_reported_as_identical(
    sync_db_session: Session,
) -> None:
    first = _load(sync_db_session, sha="a" * 40)
    db_writer.promote_batch(sync_db_session, first, None)

    changes = db_writer.report_source_changes(
        sync_db_session, _provenance(sha="a" * 40), first
    )
    assert changes == {"changed": [], "added": []}


def test_changed_source_files_are_named(sync_db_session: Session) -> None:
    """The content-addressed answer to 'is this the same data?' — no commit needed."""
    first = _load(sync_db_session, sha="a" * 40)
    db_writer.promote_batch(sync_db_session, first, None)

    changes = db_writer.report_source_changes(
        sync_db_session, _provenance(sha="b" * 40), first
    )
    assert changes["changed"] == ["achats", "broyage", "tax"]


def test_source_change_report_is_empty_on_the_first_batch(
    sync_db_session: Session,
) -> None:
    assert db_writer.report_source_changes(sync_db_session, _provenance(), None) == {}


# ---------------------------------------------------------------------------
# reconciliation — period-driven gating
# ---------------------------------------------------------------------------
def test_golden_checks_skip_when_the_batch_lacks_the_months(
    sync_db_session: Session,
) -> None:
    """The gate is driven by what the data covers, not by a date in the test.
    Every published golden entry is a target the moment its months land."""
    batch_id = _load(sync_db_session)  # March 2026 only

    report = reconciliation.reconcile(sync_db_session, batch_id)

    assert report.results
    assert not report.passed
    assert not report.failures
    assert all("does not cover" in r.detail for r in report.skipped)
    reconciliation.raise_on_failure(report)  # skipped is not failed


def test_golden_check_passes_when_the_computed_total_matches(
    sync_db_session: Session,
) -> None:
    batch_id = _load(sync_db_session)
    golden = reconciliation.GoldenSeasonYtd(
        season="2025-2026",
        through_month=3,
        exports_tonnes=175,
        purchases_tonnes=500,
        taxes_fcfa_millions=30,
    )
    # Coverage is per source now (business-rules §6): exports and achats are
    # gated independently because the two publications stop at different months.
    coverage = {
        reconciliation.EXPORTS: {"2025-2026": reconciliation._ytd_month_set(3)},
        reconciliation.PURCHASES: {"2025-2026": reconciliation._ytd_month_set(3)},
    }

    results = reconciliation._check_season_ytd(
        sync_db_session, batch_id, golden, coverage
    )
    assert [r.status for r in results] == ["passed", "passed", "passed"]


def test_divergence_raises_and_names_the_expected_value(
    sync_db_session: Session,
) -> None:
    """§9: a divergence is a taxonomy or unit bug, never a reason to move the
    target — so the failure has to be loud and quantified."""
    batch_id = _load(sync_db_session)
    golden = reconciliation.GoldenSeasonYtd(
        season="2025-2026",
        through_month=3,
        exports_tonnes=999_999,
        purchases_tonnes=500,
        taxes_fcfa_millions=30,
    )
    coverage = {
        reconciliation.EXPORTS: {"2025-2026": reconciliation._ytd_month_set(3)},
        reconciliation.PURCHASES: {"2025-2026": reconciliation._ytd_month_set(3)},
    }

    results = reconciliation._check_season_ytd(
        sync_db_session, batch_id, golden, coverage
    )
    report = reconciliation.ReconciliationReport(results=tuple(results))

    assert len(report.failures) == 1
    with pytest.raises(ReconciliationError, match="999,999"):
        reconciliation.raise_on_failure(report)


def test_monthly_golden_check_reads_exports_and_achats_independently(
    sync_db_session: Session,
) -> None:
    """The July 2026 synthèse is four figures from two sources; each is gated on
    its own coverage (business-rules §6)."""
    batch_id = _load(sync_db_session)
    golden = reconciliation.GoldenMonth(
        year=2026,
        month=3,
        exports_tonnes=175,
        purchases_tonnes=500,
        valcaf_fcfa_millions=300,
        taxes_fcfa_millions=30,
    )
    coverage = reconciliation._coverage(sync_db_session, batch_id)

    results = reconciliation._check_month(sync_db_session, batch_id, golden, coverage)

    assert [r.status for r in results] == ["passed", "passed", "passed", "passed"]
    assert any("VALCAF" in r.name for r in results)


def test_a_lagging_source_skips_only_its_own_checks(sync_db_session: Session) -> None:
    """§6 forbids comparing a source's YTD against a window it does not cover.
    Exports present + achats absent must skip the achats check alone, never fail
    it and never suppress the exports one."""
    batch_id = _load(sync_db_session)
    sync_db_session.execute(
        text("DELETE FROM pl_origin_purchase_monthly WHERE ingest_batch_id = :b"),
        {"b": batch_id},
    )
    golden = reconciliation.GoldenSeasonYtd(
        season="2025-2026",
        through_month=3,
        exports_tonnes=175,
        purchases_tonnes=500,
    )
    coverage = reconciliation._coverage(sync_db_session, batch_id)
    coverage[reconciliation.EXPORTS]["2025-2026"] = reconciliation._ytd_month_set(3)

    results = reconciliation._check_season_ytd(
        sync_db_session, batch_id, golden, coverage
    )
    by_status = {r.status for r in results}
    assert by_status == {"passed", "skipped"}
    skipped = next(r for r in results if r.status == "skipped")
    assert "achats" in skipped.name and reconciliation.PURCHASES in skipped.detail


def test_ytd_month_set_is_season_ordered_not_calendar() -> None:
    """business-rules §5 picks the month-set intersection over a date cutoff: it
    handles gaps and needs no leap-year guard."""
    assert reconciliation._ytd_month_set(7) == {10, 11, 12, 1, 2, 3, 4, 5, 6, 7}
    assert reconciliation._ytd_month_set(12) == set(range(1, 13))


def test_published_transforme_total_is_documented_as_a_non_target() -> None:
    """§9 prints TOTAL TRANSFORMÉ 473 907, which counts HORS GRADE as
    transformed. §2 wins; the figure is recorded so nobody later 'fixes' the
    taxonomy to chase it."""
    mix = reconciliation.GOLDEN_PRODUCT_MIX[0].tonnes_by_product
    strictly_transformed = sum(
        tonnes
        for product, tonnes in mix.items()
        if product not in {"FEVES", "HORS_GRADE"}
    )
    assert strictly_transformed == reconciliation.COMPASS_TOTAL_TRANSFORME
    # Integration doc §9: pin the delta to its single known cause (the HORS GRADE
    # line) rather than tolerate an approximate match. The +1 is the report's own
    # rounding of the six product lines.
    assert (
        strictly_transformed + mix["HORS_GRADE"]
        == reconciliation.WATCHAI_TOTAL_TRANSFORME_INCLUDES_HORS_GRADE + 1
    )
