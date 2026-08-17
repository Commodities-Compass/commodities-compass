"""Acquisition guards and CLI wiring for ``watchai-sync``.

Builds a throwaway git checkout shaped like watch-ai, so the dirty-tree refusal
and the schema-drift failures are exercised against real ``git status`` output
rather than a hand-typed string.
"""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

import pandas as pd
import pytest

from scripts.watchai_sync import acquire, config, main
from scripts.watchai_sync.errors import (
    DirtyWorkingTreeError,
    ProdOperatorRequiredError,
    ProdTargetNotConfiguredError,
    SourceNotFoundError,
    SourceSchemaError,
)


# ---------------------------------------------------------------------------
# a miniature watch-ai checkout
# ---------------------------------------------------------------------------
# conftest points this at commodities_compass_test, whose tables are built by
# Base.metadata.create_all — so this suite also proves the models produce the
# same schema the Alembic migration does.
_TEST_DB_URL = os.environ["DATABASE_SYNC_URL"]


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _write_masters(master_dir: Path) -> None:
    pd.DataFrame(
        {
            "DATE_SIMPLE": [pd.Timestamp("2026-03-10")],
            "EXPORTATEUR_SIMPLE": ["CARGILL"],
            "DESTINATION_SIMPLE": ["PAYS-BAS"],
            "PORT": ["ABIDJAN"],
            "POSTAR": ["1801001100"],
            "PRODUIT SIMPLE": ["FEVES"],
            "PDS_NET": [100_000],
            "VALCAF": [1.0],
            "DROITS_TAXES": [2.0],
        }
    ).to_parquet(master_dir / config.DECLARATIONS_FILE)
    pd.DataFrame(
        {
            "EXPORTATEUR_SIMPLE": ["CARGILL"],
            "DATE": [pd.Timestamp("2026-03-01")],
            "POIDS_NET_KG": [1_000.0],
        }
    ).to_parquet(master_dir / config.PURCHASES_FILE)
    pd.DataFrame(
        {"DATE": [pd.Timestamp("2026-03-01")], "TONS_BROYES": [55_000.0]}
    ).to_parquet(master_dir / config.GRINDINGS_FILE)

    with pd.ExcelWriter(master_dir / config.ENTITY_MAPPINGS_FILE) as writer:
        pd.DataFrame(
            {"EXPORTATEUR": ["CARGILL WEST AFRICA"], "EXPORTATEUR_SIMPLE": ["CARGILL"]}
        ).to_excel(writer, sheet_name="Exportateurs", index=False)
        pd.DataFrame(
            {"DESTINATION": ["NL"], "DESTINATION_SIMPLE": ["PAYS-BAS"]}
        ).to_excel(writer, sheet_name="Destinations", index=False)


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    root = tmp_path / "watch-ai"
    (root / config.MASTER_DATA_DIR).mkdir(parents=True)
    _write_masters(root / config.MASTER_DATA_DIR)

    _git(root.parent, "init", root.name)
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "masters")
    return root


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------
def test_acquire_identity_is_the_file_hashes(checkout: Path) -> None:
    """Batch identity is content, not a commit (decision #5).

    Pushing the data is an optional step in Julien's monthly procedure, so a
    commit SHA can describe a different dataset than the one on disk.
    """
    snapshot = acquire.acquire(checkout)
    provenance = snapshot.provenance

    assert set(provenance.file_hashes) == set(config.REQUIRED_SOURCE_FILES)
    assert all(len(h) == 64 for h in provenance.file_hashes.values())
    assert len(provenance.combined_hash) == 64
    assert len(snapshot.declarations) == 1
    assert snapshot.mapping_names["exporter"] == frozenset({"CARGILL"})
    assert snapshot.mapping_names["destination"] == frozenset({"PAYS-BAS"})


def test_identical_bytes_give_an_identical_identity(
    checkout: Path, tmp_path: Path
) -> None:
    """Content-addressing in one assertion: the same four files copied to a plain
    folder with no git at all yield the same identity."""
    import shutil

    plain = tmp_path / "delivered-by-email"
    shutil.copytree(checkout / config.MASTER_DATA_DIR, plain / config.MASTER_DATA_DIR)

    from_git = acquire.acquire(checkout).provenance
    from_folder = acquire.acquire(plain).provenance

    assert from_folder.kind == acquire.SOURCE_FILES
    assert from_folder.git is None
    assert from_git.kind == acquire.SOURCE_GIT
    assert from_folder.combined_hash == from_git.combined_hash


def test_git_metadata_is_recorded_when_available(checkout: Path) -> None:
    """Bonus provenance — never a requirement."""
    provenance = acquire.acquire(checkout).provenance

    assert provenance.kind == acquire.SOURCE_GIT
    assert provenance.git is not None
    assert len(provenance.git.commit_sha) == 40
    assert provenance.git.untracked_paths == ()


def test_only_the_two_ingested_mapping_sheets_are_read(checkout: Path) -> None:
    """Destinataires and Declarant map columns the reduced projection drops
    (decision #7) — reading them would import 54k rows we can never use."""
    snapshot = acquire.acquire(checkout)
    assert set(snapshot.mapping_names) == {"exporter", "destination"}


# ---------------------------------------------------------------------------
# dirty tree (integration doc §4 step 1)
# ---------------------------------------------------------------------------
def test_modified_master_refuses_to_load(checkout: Path) -> None:
    """The whole point of the refusal: the parquet no longer matches the SHA the
    batch would claim as its provenance."""
    _write_masters(checkout / config.MASTER_DATA_DIR)
    path = checkout / config.MASTER_DATA_DIR / config.GRINDINGS_FILE
    pd.DataFrame(
        {"DATE": [pd.Timestamp("2026-04-01")], "TONS_BROYES": [1.0]}
    ).to_parquet(path)

    with pytest.raises(DirtyWorkingTreeError, match=config.GRINDINGS_FILE):
        acquire.acquire(checkout)


def test_untracked_file_under_master_data_refuses_to_load(checkout: Path) -> None:
    (checkout / config.MASTER_DATA_DIR / "Db_Master_Tax_v2.parquet").write_bytes(b"x")

    with pytest.raises(DirtyWorkingTreeError, match="Master_Data"):
        acquire.acquire(checkout)


def test_unrelated_untracked_file_is_recorded_not_blocking(checkout: Path) -> None:
    """The real checkout carries exactly this today (an untracked .env.example);
    it cannot change what we read, so it must not block ingestion."""
    (checkout / ".env.example").write_text("EXAMPLE=1\n")

    snapshot = acquire.acquire(checkout)

    assert snapshot.provenance.git is not None
    assert snapshot.provenance.git.untracked_paths == (".env.example",)


# ---------------------------------------------------------------------------
# source validation
# ---------------------------------------------------------------------------
def test_missing_directory_fails_loud(tmp_path: Path) -> None:
    with pytest.raises(SourceNotFoundError, match="not a directory"):
        acquire.acquire(tmp_path / "nope")


def test_plain_folder_is_supported(tmp_path: Path) -> None:
    """A folder is the contract; git is not required (decision #5).

    This is what lets Compass stay entirely decoupled from WatchAI's repository:
    Julien can send the four files by any channel.
    """
    (tmp_path / config.MASTER_DATA_DIR).mkdir(parents=True)
    _write_masters(tmp_path / config.MASTER_DATA_DIR)

    snapshot = acquire.acquire(tmp_path)

    assert snapshot.provenance.kind == acquire.SOURCE_FILES
    assert snapshot.provenance.git is None
    assert len(snapshot.declarations) == 1


def test_plain_folder_has_no_dirty_tree_notion(tmp_path: Path) -> None:
    """The dirty-tree refusal exists so a recorded SHA cannot contradict the
    bytes read. With no SHA there is nothing to contradict, so a stray file in a
    plain folder must not block the load."""
    (tmp_path / config.MASTER_DATA_DIR).mkdir(parents=True)
    _write_masters(tmp_path / config.MASTER_DATA_DIR)
    (tmp_path / "notes.txt").write_text("whatever\n")

    assert acquire.acquire(tmp_path).provenance.kind == acquire.SOURCE_FILES


def test_missing_master_data_directory_fails_loud(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root.parent, "init", root.name)
    with pytest.raises(SourceNotFoundError, match=config.MASTER_DATA_DIR):
        acquire.acquire(root)


def test_missing_master_file_fails_loud(checkout: Path) -> None:
    path = checkout / config.MASTER_DATA_DIR / config.GRINDINGS_FILE
    path.unlink()
    _git(checkout, "add", "-A")
    _git(checkout, "commit", "-m", "drop grindings")

    with pytest.raises(SourceNotFoundError, match=config.GRINDINGS_FILE):
        acquire.acquire(checkout)


def test_dropped_column_fails_loud(checkout: Path) -> None:
    """A shape change upstream means the extract itself changed; reindexing
    around it would silently reinterpret the data."""
    path = checkout / config.MASTER_DATA_DIR / config.DECLARATIONS_FILE
    frame = pd.read_parquet(path).drop(columns=["POSTAR"])
    frame.to_parquet(path)
    _git(checkout, "add", "-A")
    _git(checkout, "commit", "-m", "drop postar")

    with pytest.raises(SourceSchemaError, match="POSTAR"):
        acquire.acquire(checkout)


def test_empty_master_fails_loud(checkout: Path) -> None:
    path = checkout / config.MASTER_DATA_DIR / config.PURCHASES_FILE
    pd.read_parquet(path).iloc[0:0].to_parquet(path)
    _git(checkout, "add", "-A")
    _git(checkout, "commit", "-m", "empty purchases")

    with pytest.raises(SourceSchemaError, match="empty"):
        acquire.acquire(checkout)


def test_missing_mapping_sheet_fails_loud(checkout: Path) -> None:
    path = checkout / config.MASTER_DATA_DIR / config.ENTITY_MAPPINGS_FILE
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame({"EXPORTATEUR_SIMPLE": ["CARGILL"]}).to_excel(
            writer, sheet_name="Exportateurs", index=False
        )
    _git(checkout, "add", "-A")
    _git(checkout, "commit", "-m", "drop destinations sheet")

    with pytest.raises(SourceSchemaError, match="Destinations"):
        acquire.acquire(checkout)


def test_missing_mapping_column_fails_loud(checkout: Path) -> None:
    path = checkout / config.MASTER_DATA_DIR / config.ENTITY_MAPPINGS_FILE
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame({"WRONG": ["CARGILL"]}).to_excel(
            writer, sheet_name="Exportateurs", index=False
        )
        pd.DataFrame({"DESTINATION_SIMPLE": ["PAYS-BAS"]}).to_excel(
            writer, sheet_name="Destinations", index=False
        )
    _git(checkout, "add", "-A")
    _git(checkout, "commit", "-m", "rename column")

    with pytest.raises(SourceSchemaError, match="EXPORTATEUR_SIMPLE"):
        acquire.acquire(checkout)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def test_prod_target_without_env_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    """A forgotten tunnel must not silently fall back to the local database.

    The prod URL only exists while the bastion is up, so its absence is the
    normal signal that the operator has not opened one — and writing 172k rows
    into the local DB instead would look like a successful prod load.
    """
    monkeypatch.delenv("WATCHAI_PROD_DATABASE_URL", raising=False)
    with pytest.raises(ProdTargetNotConfiguredError, match="db-prod.sh up"):
        main.resolve_database_url("prod", None)


def test_prod_target_reads_the_tunnel_url_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Never from the repo: the string carries a password."""
    monkeypatch.setenv(
        "WATCHAI_PROD_DATABASE_URL", "postgresql://cc_app@127.0.0.1:5434/db"
    )
    assert (
        main.resolve_database_url("prod", None)
        == "postgresql://cc_app@127.0.0.1:5434/db"
    )


def test_prod_write_demands_a_named_operator() -> None:
    """`pl_origin_ingest_batch` is the only record a manual prod load happened,
    so the OS user of whoever held the tunnel is not an accountable answer."""
    args = argparse.Namespace(
        target="prod", dry_run=False, ingested_by=None, database_url="postgresql://x/y"
    )
    with pytest.raises(ProdOperatorRequiredError, match="audit trail"):
        main.run(args)


def test_prod_dry_run_does_not_demand_an_operator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The runbook makes a prod dry-run mandatory before the real load; requiring
    a name to *look* would push operators to skip the rehearsal."""
    monkeypatch.setenv(
        "WATCHAI_PROD_DATABASE_URL", "postgresql://cc_app@127.0.0.1:5434/db"
    )
    args = argparse.Namespace(
        target="prod",
        dry_run=True,
        ingested_by=None,
        database_url=None,
        source="/nonexistent",
    )
    # Fails later, on the source — not on the operator guard.
    with pytest.raises(SourceNotFoundError):
        main.run(args)


def test_explicit_database_url_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_SYNC_URL", "postgresql://env/db")
    assert (
        main.resolve_database_url("local", "postgresql://cli/db")
        == "postgresql://cli/db"
    )


def test_database_sync_url_is_used_when_no_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_SYNC_URL", "postgresql://env/db")
    assert main.resolve_database_url("local", None) == "postgresql://env/db"


def test_local_default_when_nothing_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mirror image of scripts/db.py: that module refuses a default so a scraper
    can never write locally by accident; this one is local-only by scope."""
    monkeypatch.delenv("DATABASE_SYNC_URL", raising=False)
    assert main.resolve_database_url("local", None) == config.LOCAL_DATABASE_URL


def test_parser_defaults() -> None:
    args = main.build_parser().parse_args(["--source", "../watch-ai"])

    assert args.target == "local"
    assert args.dry_run is False
    assert args.skip_compute is False
    assert args.keep_batches == config.DEFAULT_KEEP_BATCHES


def test_parser_accepts_the_documented_flags() -> None:
    args = main.build_parser().parse_args(
        ["--source", "../watch-ai", "--dry-run", "--skip-compute", "--verbose"]
    )
    assert args.dry_run and args.skip_compute and args.verbose


def test_source_is_required() -> None:
    with pytest.raises(SystemExit):
        main.build_parser().parse_args([])


def test_describe_source_resolves_relative_paths() -> None:
    """``poetry run`` executes from backend/, so "../watch-ai" is one level off —
    the single most common operator mistake, worth being able to print."""
    assert Path(main.describe_source("../watch-ai")).is_absolute()


# ---------------------------------------------------------------------------
# end-to-end orchestration
# ---------------------------------------------------------------------------
@pytest.fixture
def clean_origin_schema():
    """Truncate the origin tables around a committing run.

    ``run()`` manages its own session and commits, so it cannot use the
    rollback-scoped ``sync_db_session`` fixture.
    """
    from sqlalchemy import create_engine, text

    engine = create_engine(_TEST_DB_URL)

    def _truncate() -> None:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM pl_origin_ingest_batch"))
            connection.execute(text("DELETE FROM ref_origin_entity"))

    _truncate()
    yield engine
    _truncate()
    engine.dispose()


def _run(checkout: Path, **flags) -> int:
    argv = ["--source", str(checkout), "--database-url", _TEST_DB_URL]
    for flag, enabled in flags.items():
        if enabled:
            argv.append(f"--{flag.replace('_', '-')}")
    return main.run(main.build_parser().parse_args(argv))


def test_dry_run_persists_nothing(checkout: Path, clean_origin_schema, capsys) -> None:
    """The rollback is what makes --dry-run safe to point at any database."""
    from sqlalchemy import text

    assert _run(checkout, dry_run=True) == 0

    with clean_origin_schema.connect() as connection:
        batches = connection.execute(
            text("SELECT COUNT(*) FROM pl_origin_ingest_batch")
        ).scalar_one()
    assert batches == 0
    assert "rolled back" in capsys.readouterr().out


def test_run_writes_promotes_and_reports(
    checkout: Path, clean_origin_schema, capsys
) -> None:
    from sqlalchemy import text

    assert _run(checkout) == 0

    with clean_origin_schema.connect() as connection:
        current, declarations, cells = connection.execute(
            text(
                """
                SELECT (SELECT COUNT(*) FROM pl_origin_ingest_batch WHERE is_current),
                       (SELECT COUNT(*) FROM pl_origin_export_declaration),
                       (SELECT COUNT(*) FROM pl_origin_flow_monthly)
                """
            )
        ).one()
    assert (current, declarations, cells) == (1, 1, 1)

    output = capsys.readouterr().out
    assert "Batch summary" in output
    assert "first batch" in output  # nothing to diff against


def test_second_run_reports_no_restatement(
    checkout: Path, clean_origin_schema, capsys
) -> None:
    _run(checkout)
    capsys.readouterr()
    _run(checkout)

    assert "restatement  : none" in capsys.readouterr().out


def test_skip_compute_skips_the_cube_and_reconciliation(
    checkout: Path, clean_origin_schema, capsys
) -> None:
    from sqlalchemy import text

    assert _run(checkout, skip_compute=True) == 0

    with clean_origin_schema.connect() as connection:
        cells = connection.execute(
            text("SELECT COUNT(*) FROM pl_origin_flow_monthly")
        ).scalar_one()
    assert cells == 0
    assert "Reconciliation" not in capsys.readouterr().out


def test_main_exits_non_zero_and_writes_nothing_on_failure(
    tmp_path: Path, clean_origin_schema, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail loud, non-zero exit, no partial write
    (.claude/rules/pipeline-error-handling.md)."""
    from sqlalchemy import text

    monkeypatch.setattr(
        "sys.argv",
        [
            "watchai-sync",
            "--source",
            str(tmp_path / "absent"),
            "--database-url",
            _TEST_DB_URL,
        ],
    )
    with pytest.raises(SystemExit) as excinfo:
        main.main()

    assert excinfo.value.code == 1
    with clean_origin_schema.connect() as connection:
        assert (
            connection.execute(
                text("SELECT COUNT(*) FROM pl_origin_ingest_batch")
            ).scalar_one()
            == 0
        )


def test_restatement_is_printed_when_history_moves(
    checkout: Path, clean_origin_schema, capsys
) -> None:
    """A restated figure a client has already read must be visible at the moment
    the served numbers change, not discovered afterwards."""
    _run(checkout)
    capsys.readouterr()

    path = checkout / config.MASTER_DATA_DIR / config.DECLARATIONS_FILE
    frame = pd.read_parquet(path)
    frame.loc[0, "PDS_NET"] = 900_000
    frame.to_parquet(path)
    _git(checkout, "add", "-A")
    _git(checkout, "commit", "-m", "restate march")

    _run(checkout)

    output = capsys.readouterr().out
    assert "HISTORY MOVED" in output
    assert "+800.0" in output
