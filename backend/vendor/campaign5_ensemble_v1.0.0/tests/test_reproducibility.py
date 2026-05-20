"""Two-run bit-identical reproducibility — the binding determinism gate.

Runs ``tools/freeze_artifacts.py`` twice against the same TRAINING_CUTOFF and
diffs the resulting ``manifest.json``. Every artifact's SHA-256 must match.
If they don't, some non-determinism has crept in (un-seeded RNG, hash-order
iteration, threading races, dependency drift). Block the delivery.

Marked ``integration`` because it's a 5-10 min run requiring R&D's local
Parquet snapshot at ``data/db_snapshots/latest/``. CI skips it by default;
run locally with ``pytest -m integration``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.integration
def test_freezer_is_bit_identical_across_two_runs(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    freezer = repo_root / "deliverables" / "campaign5_ensemble_v1.0.0" / "tools" / "freeze_artifacts.py"
    assert freezer.exists(), f"freezer script missing at {freezer}"

    out_a = tmp_path / "run_a"
    out_b = tmp_path / "run_b"
    env = os.environ.copy()
    env.update({
        "TRAINING_CUTOFF": "2026-04-30",
        "DATA_SOURCE": "rd_local",
    })

    for out_dir in (out_a, out_b):
        env["OUTPUT_DIR"] = str(out_dir)
        # Sanitize PYTHONPATH so the freezer can see the ensemble package +
        # the R&D methodology.data_loader module (used as the data source).
        env["PYTHONPATH"] = f"{repo_root / 'deliverables' / 'campaign5_ensemble_v1.0.0'}:{repo_root}"
        result = subprocess.run(
            [sys.executable, str(freezer)],
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            pytest.fail(f"freezer exit {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")

    manifest_a = json.loads((out_a / "manifest.json").read_text())
    manifest_b = json.loads((out_b / "manifest.json").read_text())

    # Drop fields that legitimately vary (timestamps, fit times).
    def _normalize(m: dict) -> list[dict]:
        rows = []
        for r in m["artifacts"]:
            rows.append({
                "artifact_kind": r["artifact_kind"],
                "artifact_name": r["artifact_name"],
                "training_month": r.get("training_month"),
                "sha256": r["sha256"],
                "n_bytes": r["n_bytes"],
            })
        return sorted(rows, key=lambda d: (d["artifact_kind"], d["artifact_name"], d.get("training_month") or ""))

    a_rows = _normalize(manifest_a)
    b_rows = _normalize(manifest_b)
    assert a_rows == b_rows, "manifest SHA-256 set drifted between runs — non-determinism detected"

    # Defensive: clean tmp_path early (freezer outputs are large).
    shutil.rmtree(out_a, ignore_errors=True)
    shutil.rmtree(out_b, ignore_errors=True)
