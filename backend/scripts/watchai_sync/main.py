"""CLI entry point — ``poetry run watchai-sync``.

    poetry run watchai-sync --source ../watch-ai --dry-run     # inspect, no write
    poetry run watchai-sync --source ../watch-ai               # local DB
    poetry run watchai-sync --source ../watch-ai --skip-compute  # land only, no cube

Manual by design (decision #6). Everything happens in **one transaction**: a
failure at any step — an unknown product, a cube fan-out, a diverged golden
value — rolls the whole batch back, so the database never holds a half-loaded
snapshot. That is the concrete meaning of "no partial write" in
.claude/rules/pipeline-error-handling.md.
"""

from __future__ import annotations

import argparse
import getpass
import logging
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from scripts.watchai_sync import acquire as acquire_module
from scripts.watchai_sync import config, db_writer, reconciliation, transform
from scripts.watchai_sync.errors import ProdTargetRefusedError, WatchAiSyncError

logger = logging.getLogger("watchai_sync")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="watchai-sync",
        description="Load WatchAI origin data (exports, purchases, grindings) "
        "into Compass Postgres from a local watch-ai checkout.",
    )
    parser.add_argument(
        "--source",
        required=True,
        help="Path to the watch-ai git checkout (e.g. ../watch-ai). Resolved "
        "against the current working directory.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Acquire and transform, print the summary, roll back. No row survives.",
    )
    parser.add_argument(
        "--skip-compute",
        action="store_true",
        help="Land the observation tables but do not build the cube. "
        "Reconciliation is skipped too — it reads the cube.",
    )
    parser.add_argument(
        "--target",
        choices=("local", "prod"),
        default="local",
        help="Destination database. Phase 1 is local-only; 'prod' is refused.",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Override the connection string (defaults to DATABASE_SYNC_URL, "
        "then the local docker-compose URL).",
    )
    parser.add_argument(
        "--ingested-by",
        default=None,
        help="Operator handle recorded on the batch. Defaults to the OS user.",
    )
    parser.add_argument(
        "--keep-batches",
        type=int,
        default=config.DEFAULT_KEEP_BATCHES,
        help=f"Batches to retain after the load (default {config.DEFAULT_KEEP_BATCHES}; "
        "the previous one is what the next run diffs against).",
    )
    parser.add_argument("--verbose", action="store_true", help="Debug logging.")
    return parser


def resolve_database_url(target: str, override: str | None) -> str:
    """Pick the connection string, refusing prod outright in Phase 1.

    Prod is not merely defaulted away from: a manual CLI writing 170k rows into
    Cloud SQL through the bastion needs the runbook and the explicit decision
    that Phase 2 covers (integration doc §4, "Governance of the prod write").
    Until then the flag exists so the refusal is explicit rather than implied.
    """
    if target == "prod":
        raise ProdTargetRefusedError(
            "--target prod is refused in Phase 1: this phase is local-only by "
            "scope, and a prod load needs docs/runbooks/watchai-ingestion.md "
            "plus the bastion tunnel (integration doc §4)."
        )
    if override:
        return override
    import os

    return os.getenv("DATABASE_SYNC_URL") or config.LOCAL_DATABASE_URL


def run(args: argparse.Namespace) -> int:
    database_url = resolve_database_url(args.target, args.database_url)
    ingested_by = args.ingested_by or _default_operator()

    snapshot = acquire_module.acquire(args.source)
    batch = transform.transform(
        declarations=snapshot.declarations,
        purchases=snapshot.purchases,
        grindings=snapshot.grindings,
        mapping_names=snapshot.mapping_names,
    )
    # Printed before anything is written (integration doc §4 step 1): a source
    # lagging the app is the normal case, not the exception, so the operator sees
    # what they are about to load while they can still abort.
    _print_source(snapshot.provenance, batch)

    engine = create_engine(database_url, pool_pre_ping=True)
    with Session(engine) as session:
        try:
            summary = _load(session, snapshot.provenance, batch, ingested_by, args)
            if args.dry_run:
                session.rollback()
                logger.info("--dry-run: transaction rolled back, nothing persisted")
            else:
                session.commit()
        except Exception:
            session.rollback()
            raise

    _print_summary(summary, dry_run=args.dry_run)
    return 0


def _load(
    session: Session,
    provenance: acquire_module.SourceProvenance,
    batch: transform.TransformedBatch,
    ingested_by: str,
    args: argparse.Namespace,
) -> db_writer.BatchSummary:
    """The whole load, inside the caller's transaction."""
    previous_batch_id = db_writer.current_batch_id(session)
    db_writer.assert_no_row_count_regression(
        session, batch.row_counts, previous_batch_id
    )
    # Which of the four files actually changed since the last load — the
    # content-addressed answer to "is this the same data?", which needs no commit.
    source_changes = db_writer.report_source_changes(
        session, provenance, previous_batch_id
    )

    entities = db_writer.upsert_entities(session, batch.entities)
    batch_id = db_writer.insert_batch(session, provenance, batch, ingested_by)
    db_writer.write_observations(session, batch_id, batch, entities)

    cube_rows = 0
    if args.skip_compute:
        logger.warning("--skip-compute: cube not built, reconciliation skipped")
    else:
        cube_rows = db_writer.compute_cube(session, batch_id)
        report = reconciliation.reconcile(session, batch_id)
        _print_reconciliation(report)
        reconciliation.raise_on_failure(report)

    # Diff before the flip: a restatement must be visible at the moment the
    # served figures change, not discovered afterwards by a client.
    restatement = db_writer.diff_restatement(session, batch_id, previous_batch_id)
    db_writer.promote_batch(session, batch_id, restatement)
    db_writer.prune_batches(session, keep=args.keep_batches)

    return db_writer.BatchSummary(
        batch_id=batch_id,
        row_counts=batch.row_counts,
        cube_rows=cube_rows,
        restatement=restatement,
        previous_batch_id=previous_batch_id,
        source_changes=source_changes,
    )


# ---------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------
def _print_source(
    provenance: acquire_module.SourceProvenance, batch: transform.TransformedBatch
) -> None:
    """Show what is about to be loaded, and how fresh each source is."""
    print("\n── Source ──")
    print(f"  folder       : {provenance.root}")
    print(f"  kind         : {provenance.kind}")
    print(f"  identity     : {provenance.combined_hash[:16]} (sha256 of the file set)")
    for name, digest in sorted(provenance.file_hashes.items()):
        print(f"    {digest[:12]}  {name}")
    if provenance.git is not None:
        git = provenance.git
        print(
            f"  git          : {git.branch or 'detached'} @ {git.commit_sha[:12]} "
            f"({git.committed_at.date().isoformat()})"
        )
        if git.branch and git.branch != config.SPEC_SOURCE_BRANCH:
            print(
                f"  ⚠ the spec was reconciled against '{config.SPEC_SOURCE_BRANCH}' "
                f"@ {config.SPEC_SOURCE_COMMIT[:12]} ({config.SPEC_VERIFIED_ON})"
            )
    print("  freshness    : newest period per source")
    for name, period in sorted(batch.source_max_periods.items()):
        print(f"    {name:<13}: {period.isoformat()}")
    print(f"  data_as_of   : {batch.data_as_of.isoformat()}  ← what the UI will stamp")


def _print_reconciliation(report: reconciliation.ReconciliationReport) -> None:
    print("\n── Reconciliation vs published golden values ──")
    for result in report.results:
        marker = {"passed": "PASS", "skipped": "SKIP", "failed": "FAIL"}[result.status]
        print(f"  [{marker}] {result.name}: {result.detail}")
    if report.skipped:
        print(
            f"  ({len(report.skipped)} check(s) skipped — the loaded batch does "
            "not cover those periods yet; they activate on their own once it does)"
        )


def _print_summary(summary: db_writer.BatchSummary, dry_run: bool) -> None:
    print("\n── Batch summary ──")
    print(f"  batch id     : {summary.batch_id}{' (rolled back)' if dry_run else ''}")
    for dataset, count in summary.row_counts.items():
        print(f"  {dataset:<13}: {count:,}")
    print(f"  cube cells   : {summary.cube_rows:,}")

    changed = summary.source_changes.get("changed") or []
    if summary.previous_batch_id is not None:
        print(
            f"  source files : {', '.join(changed) if changed else 'byte-identical to the previous batch'}"
        )

    if summary.restatement is None:
        print("  restatement  : n/a (first batch — nothing to diff against)")
        return
    if not summary.restatement:
        print("  restatement  : none — every month matches the previous batch")
        return

    print("  restatement  : HISTORY MOVED vs the previous batch")
    for dataset, rows in summary.restatement.items():
        print(f"    {dataset}: {len(rows)} month(s) changed")
        for change in rows[:12]:
            print(
                f"      {change['period']}  "
                f"{change['previous']:>14,.1f} → {change['current']:>14,.1f} t  "
                f"({change['delta']:+,.1f})"
            )
        if len(rows) > 12:
            print(f"      … {len(rows) - 12} more")


def _default_operator() -> str:
    try:
        return getpass.getuser()
    except Exception:  # pragma: no cover - no OS user (container without passwd)
        return "unknown"


def main() -> None:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    try:
        sys.exit(run(args))
    except WatchAiSyncError as exc:
        # Fail loud, exit non-zero, no partial write. Recovery is: diagnose, fix
        # the root cause, re-run. Never a retry, never a fallback.
        logger.error("%s: %s", type(exc).__name__, exc)
        sys.exit(1)
    except KeyboardInterrupt:  # pragma: no cover
        logger.error("interrupted")
        sys.exit(130)


if __name__ == "__main__":  # pragma: no cover
    main()


# Kept importable for the runbook: resolving --source is the single most common
# operator mistake (poetry runs from backend/, so "../watch-ai" is one level off).
def describe_source(source: str) -> str:  # pragma: no cover - diagnostic helper
    return str(Path(source).expanduser().resolve())
