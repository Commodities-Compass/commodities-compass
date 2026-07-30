"""cc-regime-shadow — Campaign 6 regime algorithm, shadow-compute (INERT).

The regime algo (`regime` v1.0.0, two-layer causal router + 6 condition
specialists) ships INERT: it computes a decision every session and logs it to
``pl_regime_shadow`` for the §6 shadow-eval, but NEVER writes
``pl_indicator_daily.decision`` and is NEVER served to users. Promotion is a
Compass-side flag flip AFTER shadow clears the 0.50 hit-rate floor over >=30
sessions.

Modules:
  - ``bootstrap``       frozen/ payload -> pl_model_artifact (idempotent UPSERT)
  - ``pipeline_loader`` pl_model_artifact -> RegimePipeline (SHA-verified)
  - ``panel_loader``    v_contract_data_chained ⨝ pl_derived_indicators -> panel
  - ``db_writer``       RegimeDecision -> pl_regime_shadow (UPSERT)
  - ``main``            the shadow-compute CLI
"""

import sys as _sys
from pathlib import Path as _Path

# The `regime` pack is VENDORED but deliberately NOT a poetry dependency: its
# pyproject pins scikit-learn==1.6.1, which conflicts with the backend's 1.5.2.
# The frozen HGB models deserialize + predict identically on 1.5.2 (verified), so
# regime ships on the current image; we just make its package importable here
# without installing it (mirrors how the pack's tools/verify_regime.py resolves it).
#
# APPEND (not insert-0): the pack dir also contains tests/ tools/ sql/ frozen/ —
# prepending it would shadow the backend's own top-level `tests` package and break
# pytest collection. Appending keeps backend packages first; only the unique
# `regime` package resolves into the vendored dir.
_VENDOR_REGIME = _Path(__file__).resolve().parents[2] / "vendor" / "regime_v1.0.0"
if str(_VENDOR_REGIME) not in _sys.path:
    _sys.path.append(str(_VENDOR_REGIME))
