"""Runtime artifact loader for the production ensemble.

The pipeline reads 14 specialist models, 3 long-run artifacts, 2 tuned configs,
and 5 canonical snapshot rows from ``pl_model_artifact``. Two loader
implementations are shipped:

    - ``DBArtifactLoader`` — production path, reads rows from
      ``pl_model_artifact`` via a SQLAlchemy-style session. Verifies SHA-256 on
      every load (rule §0 — fail loud on corruption).
    - ``FrozenDirLoader`` — R&D / test path, reads from a ``frozen/`` directory
      laid out by ``tools/freeze_artifacts.py``. Used by ``verify_delivery.py``
      and the bit-identical reproducibility test.

Both implement ``ArtifactLoader``. Higher-level helpers (``load_pickle``,
``load_json``) handle deserialization based on the manifest's
``payload_encoding`` field. The pipeline caches deserialized objects for the
job lifetime — re-running ``EnsemblePipeline.from_loader`` reuses them
without re-reading from the DB.
"""

from __future__ import annotations

import hashlib
import json
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


class ArtifactNotFoundError(LookupError):
    """Raised when a requested artifact_kind/name/training_month is missing."""


class ArtifactCorruptionError(RuntimeError):
    """Raised when a payload's recomputed SHA-256 does not match the stored digest.

    This is a fail-loud condition (rule §0): there is no scenario where a
    SHA-256 mismatch is recoverable. The job aborts, prod gets paged, the
    underlying corruption is investigated before any decision is written.
    """


@dataclass(frozen=True)
class ArtifactRecord:
    """Materialized payload + metadata for one row of pl_model_artifact."""

    artifact_kind: str
    artifact_name: str
    training_month: str | None
    payload: bytes
    payload_encoding: str   # 'pickle' | 'json-utf8' | 'parquet' | 'csv-utf8'
    sha256: str


class ArtifactLoader(Protocol):
    """Anything that can yield an ``ArtifactRecord`` by (kind, name, month)."""

    def load(
        self,
        artifact_kind: str,
        artifact_name: str,
        training_month: str | None,
    ) -> ArtifactRecord:
        ...


# ---------------------------------------------------------------------------
# DB-backed loader (production)
# ---------------------------------------------------------------------------
class DBArtifactLoader:
    """Reads artifacts from ``pl_model_artifact`` via a SQLAlchemy-style session.

    The session is expected to expose ``.execute(sql, params).first()`` with
    keyword-argument binding (``:aid`` style) — matches SQLAlchemy 1.4+ and
    SQLAlchemy 2.0. The class itself does not import sqlalchemy so it stays
    light when tests use a fake.
    """

    _SQL = (
        "SELECT artifact_kind, artifact_name, training_month, payload, "
        "payload_encoding, sha256 "
        "FROM pl_model_artifact "
        "WHERE algorithm_version_id = :aid "
        "AND artifact_kind = :k "
        "AND artifact_name = :n "
        "AND COALESCE(training_month, '') = :tm "
        "LIMIT 1"
    )

    def __init__(self, session: Any, algorithm_version_id: str) -> None:
        self._session = session
        self._aid = algorithm_version_id
        self._cache: dict[tuple[str, str, str], ArtifactRecord] = {}

    def load(
        self,
        artifact_kind: str,
        artifact_name: str,
        training_month: str | None,
    ) -> ArtifactRecord:
        key = (artifact_kind, artifact_name, training_month or "")
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        row = self._session.execute(
            self._SQL,
            {"aid": self._aid, "k": artifact_kind, "n": artifact_name, "tm": training_month or ""},
        ).first()
        if row is None:
            raise ArtifactNotFoundError(
                f"{artifact_kind}/{artifact_name}@{training_month} not in pl_model_artifact "
                f"for algorithm_version_id={self._aid}"
            )
        payload = bytes(row.payload)
        observed = hashlib.sha256(payload).hexdigest()
        if observed != row.sha256:
            raise ArtifactCorruptionError(
                f"sha256 mismatch on {artifact_kind}/{artifact_name}@{training_month}: "
                f"expected {row.sha256}, observed {observed}"
            )
        record = ArtifactRecord(
            artifact_kind=row.artifact_kind,
            artifact_name=row.artifact_name,
            training_month=row.training_month,
            payload=payload,
            payload_encoding=row.payload_encoding,
            sha256=row.sha256,
        )
        self._cache[key] = record
        return record


# ---------------------------------------------------------------------------
# Filesystem-backed loader (R&D / tests)
# ---------------------------------------------------------------------------
class FrozenDirLoader:
    """Reads artifacts from a ``frozen/`` directory produced by ``freeze_artifacts.py``.

    The manifest is the source of truth: every artifact must appear there with
    its SHA-256, encoding, and filename. Files on disk that are not in the
    manifest are ignored; manifest rows whose file is missing raise
    ``ArtifactNotFoundError`` at first access.
    """

    def __init__(self, frozen_dir: Path) -> None:
        self._dir = Path(frozen_dir)
        manifest_path = self._dir / "manifest.json"
        if not manifest_path.exists():
            raise ArtifactNotFoundError(f"manifest.json missing in {self._dir}")
        manifest = json.loads(manifest_path.read_text())
        self._index: dict[tuple[str, str, str], dict[str, Any]] = {}
        for row in manifest.get("artifacts", []):
            tm = row.get("training_month") or ""
            self._index[(row["artifact_kind"], row["artifact_name"], tm)] = row
        self._cache: dict[tuple[str, str, str], ArtifactRecord] = {}

    def load(
        self,
        artifact_kind: str,
        artifact_name: str,
        training_month: str | None,
    ) -> ArtifactRecord:
        key = (artifact_kind, artifact_name, training_month or "")
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        row = self._index.get(key)
        if row is None:
            raise ArtifactNotFoundError(
                f"{artifact_kind}/{artifact_name}@{training_month} not in manifest at {self._dir}"
            )
        filename = row.get("filename")
        if not filename:
            raise ArtifactNotFoundError(f"manifest row missing 'filename' for {key}")
        path = self._dir / filename
        if not path.exists():
            raise ArtifactNotFoundError(f"manifest references missing file: {path}")
        payload = path.read_bytes()
        observed = hashlib.sha256(payload).hexdigest()
        if observed != row["sha256"]:
            raise ArtifactCorruptionError(
                f"sha256 mismatch on {key}: expected {row['sha256']}, observed {observed}"
            )
        record = ArtifactRecord(
            artifact_kind=artifact_kind,
            artifact_name=artifact_name,
            training_month=training_month,
            payload=payload,
            payload_encoding=row["payload_encoding"],
            sha256=row["sha256"],
        )
        self._cache[key] = record
        return record


# ---------------------------------------------------------------------------
# Typed convenience wrappers
# ---------------------------------------------------------------------------
def load_pickle(loader: ArtifactLoader, kind: str, name: str, training_month: str | None) -> Any:
    rec = loader.load(kind, name, training_month)
    if rec.payload_encoding != "pickle":
        raise ValueError(f"{kind}/{name} has encoding {rec.payload_encoding!r}, expected 'pickle'")
    return pickle.loads(rec.payload)


def load_json(loader: ArtifactLoader, kind: str, name: str, training_month: str | None) -> Any:
    rec = loader.load(kind, name, training_month)
    if rec.payload_encoding not in ("json-utf8", "csv-utf8"):
        raise ValueError(f"{kind}/{name} has encoding {rec.payload_encoding!r}, expected JSON")
    return json.loads(rec.payload.decode("utf-8"))
