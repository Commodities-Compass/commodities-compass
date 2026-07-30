"""Load + SHA-256-verify the frozen regime payload.

Works against a ``FrozenDirLoader`` (a local ``frozen/`` directory). Prod may
implement its own loader backed by ``pl_model_artifact`` BYTEA rows; the contract
is: return the deserialized specialist models + the router config, having verified
every SHA-256 against the manifest (fail-loud).
"""
from __future__ import annotations

import hashlib
import json
import pickle
from pathlib import Path
from typing import Any


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class FrozenDirLoader:
    def __init__(self, frozen_dir: str | Path) -> None:
        self.dir = Path(frozen_dir)
        manifest_path = self.dir / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"manifest.json not found in {self.dir}")
        self.manifest = json.loads(manifest_path.read_text())

    def _read_verified(self, entry: dict) -> bytes:
        blob = (self.dir / entry["file"]).read_bytes()
        actual = _sha(blob)
        if actual != entry["sha256"]:
            raise RuntimeError(
                f"SHA-256 mismatch for {entry['artifact_name']} ({entry['file']}): "
                f"manifest {entry['sha256']}, disk {actual}"
            )
        return blob

    def load_specialists(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for e in self.manifest["artifacts"]:
            if e["artifact_kind"] == "regime_specialist_model":
                out[e["artifact_name"]] = pickle.loads(self._read_verified(e))
        if not out:
            raise RuntimeError("no regime_specialist_model artifacts in manifest")
        return out

    def load_router(self) -> dict[str, Any]:
        for e in self.manifest["artifacts"]:
            if e["artifact_kind"] == "regime_router":
                return json.loads(self._read_verified(e).decode())
        raise RuntimeError("no regime_router artifact in manifest")
