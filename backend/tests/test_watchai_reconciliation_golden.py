"""The Phase 1 gate: real watch-ai checkout → Postgres → published golden values.

Integration doc §9. This is the test the phase is defined by, so it runs against
the actual parquet masters rather than fixtures — a transform that only satisfies
hand-written frames proves nothing about a taxonomy or a unit.

Two things keep it honest as the upstream repo moves:

* It reads whatever the checkout holds and lets ``reconciliation`` decide which
  golden entries are computable. Nothing here is pinned to a month.
* Every golden entry the batch *can* cover must pass. A skip is reported, never
  swallowed — the test asserts that at least one real check actually ran, so the
  suite cannot silently degrade into "everything skipped, all green".

Skipped entirely when the checkout is absent (CI has no access to that private
repo). That is a genuine coverage gap and is stated as such in the runbook.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from scripts.watchai_sync import acquire, config, db_writer, reconciliation, transform

# ../../watch-ai relative to the backend package, overridable for a source folder
# kept elsewhere. A plain folder holding the four masters works — git is optional.
_DEFAULT_SOURCE = Path(__file__).resolve().parents[3] / "watch-ai"
SOURCE = Path(os.getenv("WATCHAI_SOURCE", str(_DEFAULT_SOURCE)))


def _source_identity() -> str | None:
    """Combined sha256 of the source file set, or None if the source is absent."""
    try:
        return acquire.read_provenance(SOURCE).combined_hash
    except Exception:
        return None


_IDENTITY = _source_identity()

# Two independent preconditions, and the distinction matters:
#   * no source folder            → nothing to test (CI: the repo is private)
#   * source is a DIFFERENT dataset → the fixtures do not describe it, so a
#     mismatch would be a restatement rather than a bug in our transform. On
#     `main` (frozen at May 2026 data) the 2024-2025 mix differs by 2 t for
#     exactly that reason.
# Skipping on the second is what stops this gate from reporting someone else's
# data drift as our failure — and the reason string names both hashes so it is
# never mistaken for "the test is broken".
pytestmark = [
    pytest.mark.skipif(
        _IDENTITY is None,
        reason=f"no WatchAI source at {SOURCE}; set WATCHAI_SOURCE to run",
    ),
    pytest.mark.skipif(
        _IDENTITY is not None and _IDENTITY != config.SPEC_SOURCE_FILE_SET_SHA256,
        reason=(
            f"source dataset {(_IDENTITY or '')[:12]} is not the one the golden "
            f"fixtures were verified against "
            f"({config.SPEC_SOURCE_FILE_SET_SHA256[:12]} = "
            f"{config.SPEC_SOURCE_BRANCH}@{config.SPEC_SOURCE_COMMIT[:12]}, "
            f"{config.SPEC_VERIFIED_ON}). Point WATCHAI_SOURCE at that dataset."
        ),
    ),
]


@pytest.fixture(scope="module")
def snapshot() -> acquire.SourceSnapshot:
    """Read the checkout once — parsing 170k rows per test would be wasteful."""
    return acquire.acquire(SOURCE)


@pytest.fixture(scope="module")
def batch(snapshot: acquire.SourceSnapshot) -> transform.TransformedBatch:
    return transform.transform(
        declarations=snapshot.declarations,
        purchases=snapshot.purchases,
        grindings=snapshot.grindings,
        mapping_names=snapshot.mapping_names,
    )


@pytest.fixture
def loaded(
    sync_db_session: Session,
    snapshot: acquire.SourceSnapshot,
    batch: transform.TransformedBatch,
):
    """Full load into the test database. Rolled back by the session fixture."""
    from sqlalchemy import text

    sync_db_session.execute(text("DELETE FROM pl_origin_ingest_batch"))
    sync_db_session.execute(text("DELETE FROM ref_origin_entity"))

    entities = db_writer.upsert_entities(sync_db_session, batch.entities)
    batch_id = db_writer.insert_batch(
        sync_db_session, snapshot.provenance, batch, "pytest"
    )
    db_writer.write_observations(sync_db_session, batch_id, batch, entities)
    db_writer.compute_cube(sync_db_session, batch_id)
    return batch_id


# ---------------------------------------------------------------------------
# the gate
# ---------------------------------------------------------------------------
def test_no_golden_value_diverges(loaded, sync_db_session: Session) -> None:
    report = reconciliation.reconcile(sync_db_session, loaded)

    detail = "\n".join(f"  [{r.status}] {r.name}: {r.detail}" for r in report.results)
    assert not report.failures, f"golden divergence:\n{detail}"
    reconciliation.raise_on_failure(report)


def test_at_least_one_golden_check_actually_ran(
    loaded, sync_db_session: Session
) -> None:
    """Guards against the suite degrading into 'everything skipped, all green'
    if the checkout ever regresses to a period before any golden entry."""
    report = reconciliation.reconcile(sync_db_session, loaded)
    assert report.passed, (
        "no golden check was computable — the checkout covers no published "
        f"period. Skipped: {[r.name for r in report.skipped]}"
    )


def test_published_n1_season_totals_reproduce_exactly(
    loaded, sync_db_session: Session
) -> None:
    """The N-1 comparison line of the July 2026 report:
    1 428 071 t exports · 1 622 077 t achats · 532 611 M FCFA taxes.

    Reproducing all three to the tonne is what establishes that the season
    convention (Oct→Sep), the YTD month-set and the kg→tonne conversion are all
    correct — independently of whether the current season's data has landed yet.
    """
    golden = next(
        entry
        for entry in reconciliation.GOLDEN_SEASON_YTD
        if entry.season == "2024-2025"
    )
    coverage = reconciliation._coverage(sync_db_session, loaded)
    results = reconciliation._check_season_ytd(
        sync_db_session, loaded, golden, coverage
    )

    assert [r.status for r in results] == ["passed", "passed", "passed"], [
        f"{r.name}: {r.detail}" for r in results
    ]


def test_skipped_checks_name_the_months_they_are_waiting_for(
    loaded, sync_db_session: Session
) -> None:
    """A skip has to be actionable: it must say what is missing, so the operator
    knows the gate is waiting on data rather than broken."""
    report = reconciliation.reconcile(sync_db_session, loaded)
    for result in report.skipped:
        assert "does not cover" in result.detail


# ---------------------------------------------------------------------------
# properties of the real batch
# ---------------------------------------------------------------------------
def test_every_declaration_resolves_to_the_canonical_taxonomy(
    batch: transform.TransformedBatch,
) -> None:
    """No row reached a silent default — the whole extract is explicitly mapped."""
    from app.models.origin import PRODUCT_CODES

    assert set(batch.declarations["product_code"]) <= set(PRODUCT_CODES)


def test_cube_conserves_mass_on_the_real_extract(loaded, sync_db_session) -> None:
    db_writer.assert_cube_integrity(sync_db_session, loaded)


def test_cube_is_materially_smaller_than_the_line_table(
    loaded, sync_db_session: Session
) -> None:
    """The collapse is the point: ~170k lines become ~37k monthly cells."""
    lines = int(
        db_writer._scalar(
            sync_db_session,
            "SELECT COUNT(*) FROM pl_origin_export_declaration WHERE ingest_batch_id = :b",
            {"b": loaded},
        )
    )
    cells = int(
        db_writer._scalar(
            sync_db_session,
            "SELECT COUNT(*) FROM pl_origin_flow_monthly WHERE ingest_batch_id = :b",
            {"b": loaded},
        )
    )
    assert 0 < cells < lines


def test_the_eleven_gepex_members_are_all_present(
    loaded, sync_db_session: Session
) -> None:
    """The transformation ratios are computed on the GEPEX perimeter; a member
    that failed to seed would silently shrink the denominator."""
    from scripts.watchai_sync.config import GEPEX_MEMBER_SEED

    count = int(
        db_writer._scalar(
            sync_db_session,
            "SELECT COUNT(*) FROM ref_origin_entity "
            "WHERE entity_type = 'exporter' AND is_gepex_member",
            {},
        )
    )
    assert count == len(GEPEX_MEMBER_SEED)


def test_quality_report_records_the_known_source_defects(
    batch: transform.TransformedBatch,
) -> None:
    """These are permanent properties of the upstream extract. Recording them
    means a number that looks odd later has a documented cause, and stops anyone
    turning them into an abort that would block every run."""
    report = batch.quality_report

    # On `main` the absent money values were NULL; on `refonte-da-v2` they are 0.
    # Either way the sentinel counter is the one that always carries the signal.
    sentinel = report["declarations_sentinel_valcaf"]
    assert isinstance(sentinel, int) and sentinel > 0
    absent = report["entities_absent_from_mappings"]
    assert isinstance(absent, dict)
    assert absent["exporters"], "expected exporters absent from Entity_Mappings.xlsx"
