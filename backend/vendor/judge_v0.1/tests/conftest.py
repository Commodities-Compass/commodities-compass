"""Shared fixtures + import path for the judge test suite."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BRIEFS_DIR = ROOT / "fixtures" / "briefs"
GOLDEN = ROOT / "fixtures" / "golden_verdicts.json"


@pytest.fixture
def briefs_dir() -> Path:
    return BRIEFS_DIR


@pytest.fixture
def golden_path() -> Path:
    return GOLDEN
