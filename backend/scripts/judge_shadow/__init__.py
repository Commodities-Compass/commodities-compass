"""cc-regime-shadow (layer-3) — judge macro overlay, shadow-compute (INERT).

The ``judge`` v0.1 overlay reads the last N Compass daily brief facts (press +
weather + technicals) from the DB, receives the base call from regime's shadow
decision, and via a deterministic policy fused with an LLM verdict, may
confirm, MONITOR, or flip the call. Writes to ``pl_judge_shadow`` — NEVER to
``pl_indicator_daily``. Advises, never controls, until >=30 sessions clear the
shadow-eval go/no-go.

Modules:
  - ``brief_builder``  DB rows -> ``judge.schema.Brief`` (bypasses text parsing)
  - ``regime_reader``  ``pl_regime_shadow`` -> ``RegimeDecisionLike`` adapter
  - ``llm_openai``     ``judge.llm.JudgeLLM`` impl backed by OpenAI o4-mini
  - ``db_writer``      ``JudgeOutcome`` -> ``pl_judge_shadow`` (idempotent UPSERT)
  - ``runner``         wire-up called from both the CLI and cc-regime-shadow
  - ``main``           the shadow-compute CLI
"""

import sys as _sys
from pathlib import Path as _Path

# The `judge` pack is VENDORED (backend/vendor/judge_v0.1/) but deliberately
# not a poetry dependency: the pack ships without a pyproject and the frozen
# fixtures + prompt are meant to be read-only. Mirrors the pattern used for
# vendored `regime` — see backend/scripts/regime_shadow/__init__.py for the
# APPEND-vs-insert-0 rationale (avoid shadowing backend's top-level `tests/`).
_VENDOR_JUDGE = _Path(__file__).resolve().parents[2] / "vendor" / "judge_v0.1"
if str(_VENDOR_JUDGE) not in _sys.path:
    _sys.path.append(str(_VENDOR_JUDGE))
