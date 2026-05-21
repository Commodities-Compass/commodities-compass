"""R&D self-check before tarballing the deliverable.

Six gates, all must pass:

    1. ``frozen/`` exists and contains a manifest.json.
    2. Every artifact in the manifest exists on disk.
    3. Every file's SHA-256 matches the manifest.
    4. The expected artifact inventory is complete:
         - 14 specialist_model + 14 specialist_hp rows
         - 3 long-run rows (anomaly, priors, regime_clusters)
         - 2 tuned_config rows (soft_gate, wrapper)
         - 5 canonical_snapshot rows
       Total: 38 rows.
    5. The ``ensemble`` package imports cleanly (no broken renames, missing
       module dependencies, etc.).
    6. ``EnsemblePipeline.from_loader(FrozenDirLoader(frozen_dir), ...)``
       reconstructs without error (smoke test of the artifact_io round-trip).

Exit code 0 on full pass, 1 on any failure. Prints a per-gate verdict so the
operator can see exactly which gate failed.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import sys
from collections import Counter
from pathlib import Path


EXPECTED_KIND_COUNTS = {
    "specialist_model": 14,
    "specialist_hp": 14,
    "long_run_anomaly": 1,
    "long_run_priors": 1,
    "long_run_regime_clusters": 1,
    "soft_gate_config": 1,
    "wrapper_config": 1,
    "canonical_snapshot": 5,
}
EXPECTED_TOTAL = sum(EXPECTED_KIND_COUNTS.values())


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def gate_1_manifest_present(frozen_dir: Path) -> tuple[bool, str]:
    manifest = frozen_dir / "manifest.json"
    if not manifest.exists():
        return False, f"manifest.json missing in {frozen_dir}"
    try:
        json.loads(manifest.read_text())
    except json.JSONDecodeError as exc:
        return False, f"manifest.json is not valid JSON: {exc}"
    return True, f"manifest.json present at {manifest}"


def gate_2_files_present(frozen_dir: Path, manifest: dict) -> tuple[bool, str]:
    missing = []
    for row in manifest["artifacts"]:
        f = row.get("filename")
        if not f or not (frozen_dir / f).exists():
            missing.append(row.get("filename") or f"{row['artifact_kind']}/{row['artifact_name']}")
    if missing:
        return False, f"{len(missing)} files missing on disk: {missing[:3]}{'...' if len(missing) > 3 else ''}"
    return True, f"all {len(manifest['artifacts'])} files present on disk"


def gate_3_sha_matches(frozen_dir: Path, manifest: dict) -> tuple[bool, str]:
    mismatches = []
    for row in manifest["artifacts"]:
        observed = _sha256(frozen_dir / row["filename"])
        if observed != row["sha256"]:
            mismatches.append(f"{row['artifact_kind']}/{row['artifact_name']}")
    if mismatches:
        return False, f"{len(mismatches)} SHA mismatches: {mismatches[:3]}"
    return True, f"all {len(manifest['artifacts'])} SHA-256 hashes match manifest"


def gate_4_inventory(manifest: dict) -> tuple[bool, str]:
    counts = Counter(row["artifact_kind"] for row in manifest["artifacts"])
    diffs = []
    for kind, expected in EXPECTED_KIND_COUNTS.items():
        actual = counts.get(kind, 0)
        if actual != expected:
            diffs.append(f"{kind}: expected {expected}, got {actual}")
    extra = set(counts) - set(EXPECTED_KIND_COUNTS)
    if extra:
        diffs.append(f"unexpected kinds present: {sorted(extra)}")
    if diffs:
        return False, " | ".join(diffs)
    return True, f"inventory complete: {EXPECTED_TOTAL} artifacts across {len(EXPECTED_KIND_COUNTS)} kinds"


def gate_5_imports() -> tuple[bool, str]:
    targets = [
        "ensemble.orchestrator.soft_gate",
        "ensemble.orchestrator.transition_wrapper",
        "ensemble.long_run.anomaly_veto",
        "ensemble.long_run.structural_priors",
        "ensemble.long_run.regime_similarity",
        "ensemble.optimizer.specialists",
        "ensemble.retrain.monthly_retrainer",
        "ensemble.macro_events.pipeline",
        "ensemble.artifact_io",
        "ensemble.ensemble_pipeline",
        "ensemble.data_loader_protocol",
    ]
    for m in targets:
        try:
            importlib.import_module(m)
        except Exception as exc:  # noqa: BLE001
            return False, f"failed to import {m}: {exc!r}"
    return True, f"{len(targets)} core ensemble modules import OK"


def gate_6_pipeline_roundtrip(frozen_dir: Path, training_month: str) -> tuple[bool, str]:
    """Construct the pipeline from the frozen dir loader. Catches any artifact
    deserialization bug end-to-end."""
    try:
        from ensemble.artifact_io import FrozenDirLoader  # noqa: WPS433
        from ensemble.ensemble_pipeline import EnsemblePipeline  # noqa: WPS433

        loader = FrozenDirLoader(frozen_dir)
        EnsemblePipeline.from_loader(loader, training_month=training_month)
    except Exception as exc:  # noqa: BLE001
        return False, f"EnsemblePipeline.from_loader raised {type(exc).__name__}: {exc}"
    return True, f"EnsemblePipeline.from_loader OK against {frozen_dir} @ {training_month}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen-dir", default=os.environ.get("FROZEN_DIR"),
                        help="path to frozen/ (default: $FROZEN_DIR or ./frozen)")
    parser.add_argument("--training-month", default=os.environ.get("TRAINING_MONTH", "2026-04"),
                        help="training_month label to use for the gate-6 round-trip")
    args = parser.parse_args()

    frozen_dir = Path(args.frozen_dir or "./frozen").resolve()
    if not frozen_dir.exists():
        print(f"FATAL: frozen dir does not exist: {frozen_dir}", file=sys.stderr)
        return 1

    print(f"[verify] frozen_dir = {frozen_dir}")
    print(f"[verify] training_month = {args.training_month}")
    print()

    failed = False

    ok, msg = gate_1_manifest_present(frozen_dir)
    print(f"[gate 1 manifest_present]    {'PASS' if ok else 'FAIL'}  {msg}")
    failed = failed or not ok
    if not ok:
        return 1

    manifest = json.loads((frozen_dir / "manifest.json").read_text())

    for label, runner in (
        ("gate 2 files_present", lambda: gate_2_files_present(frozen_dir, manifest)),
        ("gate 3 sha_matches", lambda: gate_3_sha_matches(frozen_dir, manifest)),
        ("gate 4 inventory", lambda: gate_4_inventory(manifest)),
        ("gate 5 imports", gate_5_imports),
        ("gate 6 pipeline_roundtrip", lambda: gate_6_pipeline_roundtrip(frozen_dir, args.training_month)),
    ):
        ok, msg = runner()
        print(f"[{label}] {'PASS' if ok else 'FAIL'}  {msg}")
        failed = failed or not ok

    print()
    if failed:
        print("[verify] one or more gates FAILED — delivery is NOT ready")
        return 1
    print(f"[verify] all 6 gates PASS — delivery {frozen_dir.parent.name} is ready to tarball")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
