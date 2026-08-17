"""Read the WatchAI masters from a folder on disk.

**A folder is the contract, not a git checkout.** Compass has no relationship
with WatchAI's repository: this job copies four files into our Postgres once a
month and, after that, Postgres is the source of truth. The folder is transport.

Batch identity is therefore the **sha256 of each source file** (decision #5), not
a commit SHA. That matters because pushing the data is an *optional* step in
Julien's monthly procedure — it ends at `scp` to his VPS, not at `git push` — so
a commit SHA can silently describe a different dataset than the one on disk. A
content hash cannot: same bytes, same hash, always.

When the folder happens to be a git checkout we record branch / SHA / commit date
as **bonus metadata** and additionally refuse a dirty working tree, because in
that case the extra provenance is free and worth having. Nothing requires it.
"""

from __future__ import annotations

import hashlib
import logging
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from scripts.watchai_sync import config
from scripts.watchai_sync.errors import (
    DirtyWorkingTreeError,
    SourceNotFoundError,
    SourceSchemaError,
)

logger = logging.getLogger(__name__)

SOURCE_GIT = "git"
SOURCE_FILES = "files"

# Untracked files elsewhere in a checkout (a stray .env.example, an editor
# scratch file) cannot change what we read, so they are recorded rather than
# blocking. Anything under Master_Data can, so it is fatal.
_DATA_SENSITIVE_PREFIX = config.MASTER_DATA_DIR

_HASH_CHUNK_BYTES = 1 << 20


@dataclass(frozen=True)
class GitMetadata:
    """Optional provenance, present only when the source folder is a checkout."""

    commit_sha: str
    committed_at: datetime
    branch: str | None
    untracked_paths: tuple[str, ...]


@dataclass(frozen=True)
class SourceProvenance:
    """Immutable identity of one set of source files."""

    root: Path
    kind: str  # SOURCE_GIT | SOURCE_FILES
    # filename → sha256. THE batch identity — content-addressed, so it is
    # unaffected by whether anyone remembered to commit.
    file_hashes: dict[str, str]
    git: GitMetadata | None = None

    @property
    def short_identity(self) -> str:
        """A human-readable stand-in for the batch, for logs and summaries."""
        digest = self.combined_hash[:12]
        if self.git is not None:
            return f"{digest} (git {self.git.commit_sha[:12]})"
        return digest

    @property
    def combined_hash(self) -> str:
        """One digest over all source hashes — the batch fingerprint."""
        joined = "\n".join(
            f"{name}:{h}" for name, h in sorted(self.file_hashes.items())
        )
        return hashlib.sha256(joined.encode()).hexdigest()


@dataclass(frozen=True)
class SourceSnapshot:
    """The three masters plus the entity mapping sheets, as read from disk."""

    provenance: SourceProvenance
    declarations: pd.DataFrame
    purchases: pd.DataFrame
    grindings: pd.DataFrame
    # entity_type ("exporter" | "destination") → canonical *_SIMPLE names known
    # to Entity_Mappings.xlsx.
    mapping_names: dict[str, frozenset[str]]


def acquire(source: str | Path) -> SourceSnapshot:
    """Load everything the transform needs, or raise.

    Provenance is established *before* the data is parsed, so a dirty checkout
    fails in under a second rather than after 172k rows.
    """
    root = Path(source).expanduser().resolve()
    provenance = read_provenance(root)
    logger.info(
        "source %s [%s] %s",
        root,
        provenance.kind,
        provenance.short_identity,
    )

    master_dir = root / config.MASTER_DATA_DIR
    declarations = _read_parquet(
        master_dir / config.DECLARATIONS_FILE, config.DECLARATION_COLUMNS
    )
    purchases = _read_parquet(
        master_dir / config.PURCHASES_FILE, config.PURCHASE_COLUMNS
    )
    grindings = _read_parquet(
        master_dir / config.GRINDINGS_FILE, config.GRINDING_COLUMNS
    )
    mapping_names = _read_entity_mappings(master_dir / config.ENTITY_MAPPINGS_FILE)

    logger.info(
        "loaded %d declarations, %d purchases, %d grindings",
        len(declarations),
        len(purchases),
        len(grindings),
    )
    return SourceSnapshot(
        provenance=provenance,
        declarations=declarations,
        purchases=purchases,
        grindings=grindings,
        mapping_names=mapping_names,
    )


# ---------------------------------------------------------------------------
# provenance
# ---------------------------------------------------------------------------
def read_provenance(root: Path) -> SourceProvenance:
    """Hash the source files; add git metadata when the folder is a checkout."""
    if not root.is_dir():
        raise SourceNotFoundError(f"--source is not a directory: {root}")
    master_dir = root / config.MASTER_DATA_DIR
    if not master_dir.is_dir():
        raise SourceNotFoundError(
            f"--source has no {config.MASTER_DATA_DIR}/ directory: {root}"
        )

    git_metadata = _read_git_metadata(root) if (root / ".git").exists() else None
    if git_metadata is None:
        logger.info(
            "source is a plain folder (no git) — identity is the file hashes alone"
        )

    file_hashes = {
        name: _sha256(master_dir / name) for name in config.REQUIRED_SOURCE_FILES
    }
    for name, digest in file_hashes.items():
        logger.debug("sha256 %s %s", digest[:16], name)

    return SourceProvenance(
        root=root,
        kind=SOURCE_GIT if git_metadata else SOURCE_FILES,
        file_hashes=file_hashes,
        git=git_metadata,
    )


def _read_git_metadata(root: Path) -> GitMetadata | None:
    """Best-effort git provenance. Returns None when the folder is not usable
    as a checkout — a broken or bare .git must not block a load whose identity
    does not depend on git in the first place."""
    try:
        sha = _git(root, "rev-parse", "HEAD").strip()
    except SourceNotFoundError as exc:
        logger.warning(
            "folder has .git but is not a usable checkout (%s) — "
            "continuing on file hashes alone",
            exc,
        )
        return None

    # The dirty-tree refusal applies only in git mode: the point is that the
    # recorded SHA must describe the bytes we read. With no SHA to contradict,
    # there is nothing to be inconsistent with.
    blocking, untracked = _classify_working_tree(_git(root, "status", "--porcelain"))
    if blocking:
        raise DirtyWorkingTreeError(
            "watch-ai working tree is dirty; refusing to load.\n"
            "The batch would record a commit SHA that does not describe these "
            "files. Commit, clean, or copy the four masters into a plain folder "
            "and point --source at that instead.\n"
            "Offending paths:\n  " + "\n  ".join(blocking)
        )
    if untracked:
        logger.warning(
            "%d untracked path(s) outside %s/ — recorded on the batch, not "
            "blocking: %s",
            len(untracked),
            config.MASTER_DATA_DIR,
            ", ".join(untracked[:5]),
        )

    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD").strip() or None
    if branch == "HEAD":  # detached
        branch = None
    committed_at = datetime.fromisoformat(
        _git(root, "show", "-s", "--format=%cI", sha).strip()
    )
    return GitMetadata(
        commit_sha=sha,
        committed_at=committed_at,
        branch=branch,
        untracked_paths=tuple(untracked),
    )


def _classify_working_tree(porcelain: str) -> tuple[list[str], list[str]]:
    """Split ``git status --porcelain`` into blocking vs merely-noted paths.

    Blocking: any modification to a tracked file, and any untracked file under
    Master_Data/ (which could shadow or accompany the files we read).
    Noted: untracked files elsewhere — they cannot alter what this job reads.
    """
    blocking: list[str] = []
    untracked: list[str] = []
    for raw in porcelain.splitlines():
        if not raw.strip():
            continue
        status, path = raw[:2], raw[3:].strip().strip('"')
        # Rename entries read "old -> new"; the destination is what matters.
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if status == "??":
            if path.startswith(_DATA_SENSITIVE_PREFIX):
                blocking.append(f"{path} (untracked, under {_DATA_SENSITIVE_PREFIX}/)")
            else:
                untracked.append(path)
        else:
            blocking.append(f"{path} ({status.strip()})")
    return blocking, untracked


def _git(root: Path, *args: str) -> str:
    """Run a read-only git command in the folder, failing loud on error."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
    except FileNotFoundError as exc:  # pragma: no cover - git absent
        raise SourceNotFoundError("git executable not found on PATH") from exc
    except subprocess.CalledProcessError as exc:
        raise SourceNotFoundError(
            f"git {' '.join(args)} failed in {root}: {exc.stderr.strip()}"
        ) from exc
    except subprocess.TimeoutExpired as exc:  # pragma: no cover - pathological
        raise SourceNotFoundError(f"git {' '.join(args)} timed out in {root}") from exc
    return completed.stdout


def _sha256(path: Path) -> str:
    """Content hash of one source file — a component of the batch identity."""
    if not path.is_file():
        raise SourceNotFoundError(f"source file not found: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# file reads
# ---------------------------------------------------------------------------
def _read_parquet(path: Path, required: tuple[str, ...]) -> pd.DataFrame:
    """Read one master, asserting the columns the transform depends on exist."""
    if not path.is_file():
        raise SourceNotFoundError(f"master file not found: {path}")
    try:
        frame = pd.read_parquet(path)
    except Exception as exc:
        raise SourceSchemaError(f"could not read {path.name}: {exc}") from exc

    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise SourceSchemaError(
            f"{path.name} is missing required column(s): {', '.join(missing)}. "
            f"Present: {', '.join(map(str, frame.columns))}"
        )
    if frame.empty:
        raise SourceSchemaError(f"{path.name} is empty")
    return frame


def _read_entity_mappings(path: Path) -> dict[str, frozenset[str]]:
    """Read the canonical-name universe from Entity_Mappings.xlsx.

    The sheets map *raw customs name → \\*_SIMPLE*, but the parquet already
    carries the ``*_SIMPLE`` columns (the mapping is applied upstream at
    integration time) and the raw ``EXPORTATEUR`` column is a literal ``0``. So
    the only thing this file can tell us is which canonical names WatchAI knows
    about — used to flag, not to gate: on ``11336ef``, 46 exporters and 7
    destinations present in the extract appear nowhere in it.
    """
    if not path.is_file():
        raise SourceNotFoundError(f"entity mappings not found: {path}")
    try:
        workbook = pd.ExcelFile(path)
    except Exception as exc:
        raise SourceSchemaError(f"could not read {path.name}: {exc}") from exc

    names: dict[str, frozenset[str]] = {}
    for entity_type, sheet in config.ENTITY_MAPPING_SHEETS.items():
        if sheet not in workbook.sheet_names:
            raise SourceSchemaError(
                f"{path.name} is missing sheet '{sheet}'. "
                f"Present: {', '.join(workbook.sheet_names)}"
            )
        column = config.ENTITY_MAPPING_SIMPLE_COLUMN[entity_type]
        frame: pd.DataFrame = workbook.parse(sheet)  # type: ignore[assignment]
        if column not in frame.columns:
            raise SourceSchemaError(
                f"{path.name}[{sheet}] is missing column '{column}'. "
                f"Present: {', '.join(map(str, frame.columns))}"
            )
        names[entity_type] = frozenset(
            value
            for value in (
                str(raw).strip().upper() for raw in frame[column].dropna().tolist()
            )
            if value
        )
        logger.debug(
            "%s mapping universe: %d names", entity_type, len(names[entity_type])
        )
    return names
