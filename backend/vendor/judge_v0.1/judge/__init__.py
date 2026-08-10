"""`judge` — macro/press/weather overlay (Layer 3) for the cocoa algorithms.

Reads the last N Compass daily briefs, detects drift vs the technical call, and
via a deterministic symmetric policy may confirm, abstain (MONITOR) or flip the
base decision. v0.1 — shadow/prototype; the LLM judgment is not reproducible by
design and is validated forward, not by backtest.
"""

from __future__ import annotations

from .brief_parser import parse_brief, parse_brief_file
from .drift import compute_drift
from .integration import (
    BriefStore,
    ShadowSink,
    prob_up_to_confidence,
    regime_base_call,
    run_shadow,
)
from .policy import derive_stance, explain, fuse
from .runner import decide
from .schema import (
    BaseCall,
    Brief,
    Decision,
    Direction,
    Drift,
    JudgeOutcome,
    JudgeVerdict,
    Stance,
)
from .scoring import score_decision, ytd

__all__ = [
    "BaseCall", "Brief", "Decision", "Direction", "Drift", "JudgeOutcome",
    "JudgeVerdict", "Stance", "parse_brief", "parse_brief_file", "compute_drift",
    "derive_stance", "explain", "fuse", "decide", "score_decision", "ytd",
    "BriefStore", "ShadowSink", "run_shadow", "regime_base_call",
    "prob_up_to_confidence",
]
