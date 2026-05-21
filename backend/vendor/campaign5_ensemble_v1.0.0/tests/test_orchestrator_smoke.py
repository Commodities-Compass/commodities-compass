"""5-day spot-check vs R&D's wrapped_decisions.csv (BIT-FOR-BIT).

For 5 trailing days from ``output/exp_optim_025/wrapped_decisions.csv``, load
the shipped artifacts via ``FrozenDirLoader``, assemble the pipeline, and
verify the produced ``wrapped_decision`` matches the R&D CSV. Any mismatch is
a porting bug that blocks delivery.

Marked ``integration`` because it requires:
    1. ``frozen/`` to be populated (freezer must have run).
    2. R&D's canonical Parquet snapshot for context assembly.

Run via ``pytest -m integration`` after Phase 8 freezer execution.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest

from ensemble.artifact_io import FrozenDirLoader
from ensemble.data_loader_protocol import DecideRequest, MacroSignal
from ensemble.ensemble_pipeline import EnsemblePipeline


REPO_ROOT = Path(__file__).resolve().parents[3]
WRAPPED_DECISIONS = REPO_ROOT / "output" / "exp_optim_025" / "wrapped_decisions.csv"


@pytest.fixture(scope="module")
def frozen_dir() -> Path:
    path = Path(os.environ.get(
        "FROZEN_DIR",
        REPO_ROOT / "deliverables" / "campaign5_ensemble_v1.0.0" / "frozen",
    ))
    if not (path / "manifest.json").exists():
        pytest.skip(f"frozen/ not populated at {path}; run tools/freeze_artifacts.py first")
    return path


@pytest.fixture(scope="module")
def reference_table() -> pd.DataFrame:
    if not WRAPPED_DECISIONS.exists():
        pytest.skip(f"reference wrapped_decisions.csv missing at {WRAPPED_DECISIONS}")
    df = pd.read_csv(WRAPPED_DECISIONS)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


@pytest.fixture(scope="module")
def pipeline(frozen_dir: Path) -> EnsemblePipeline:
    loader = FrozenDirLoader(frozen_dir)
    return EnsemblePipeline.from_loader(loader, training_month="2026-04")


@pytest.mark.integration
def test_last_five_days_match_reference(
    pipeline: EnsemblePipeline,
    reference_table: pd.DataFrame,
) -> None:
    """For 5 randomly chosen days near the cutoff, check the pipeline's wrapped
    decision matches R&D's wrapped_decisions.csv.

    A bit-for-bit match requires identical specialist predictions AND identical
    wrapper inputs. Any mismatch points to a porting bug — failing this test
    blocks the delivery handoff.
    """
    # Pick 5 last consecutive days where the wrapper had a complete trailing window.
    target_days = reference_table.tail(5).copy()
    if len(target_days) < 5:
        pytest.skip("reference table too short for 5-day check")

    # Load the canonical market panel from the frozen snapshot so we exercise
    # the same data the R&D run consumed. The reference table itself encodes
    # the per-day decisions; we just need to be able to assemble a
    # DecideRequest for each day.
    # NOTE: This test is intentionally a SHELL — concrete data assembly
    # depends on prod's loader. CI runs this once the freezer has populated
    # frozen/canonical_snapshot/.
    pytest.skip(
        "shell test: concrete day-by-day reproduction needs the prod-side "
        "DecideRequest builder (or an equivalent fixture); will be wired up "
        "during Phase 8 after the first freezer run."
    )
