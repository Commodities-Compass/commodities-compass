"""Production-side ensemble config (no R&D paths).

Mirrors the SUBSET of methodology.config that the ensemble package actually
references. All R&D-specific paths (DEFAULT_DATASET_CSV, OUTPUT_ROOT,
experiment_dir, DatasetPin) are excluded — production callers pass paths
explicitly via the data_loader_protocol or load artifacts via ArtifactLoader.
"""

from __future__ import annotations

from pathlib import Path


# Determinism constants (mandated by CLAUDE.md and the C5 reproducibility gate).
SEED: int = 42
DEFAULT_HORIZON: int = 6

# Optional fallback path — only consulted when stratification.load_regime_tags
# is called without an explicit `path` argument. In prod, the regime_tags CSV
# is loaded from `pl_model_artifact` (artifact_kind='canonical_snapshot',
# artifact_name='regime_tags_rd_2026-04-30'). The path below is a R&D-side
# fallback used by the freezer and tests; production code should never rely on it.
DEFAULT_REGIME_TAGS_CSV: Path = Path(__file__).resolve().parents[1] / "frozen" / "canonical_snapshot" / "regime_tags.csv"
