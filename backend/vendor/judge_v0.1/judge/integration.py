"""Full-system wiring: `regime` (shadow) -> `judge` overlay -> shadow log.

This is the seam the product plugs into. Everything the prod system must supply
is marked with a ``# PROD:`` comment and expressed as a small Protocol so there
is no hard dependency on the prod codebase from this R&D package.

Data flow per session:

    regime.decide(...)  ─┐
                         ├─▶ run_shadow(...) ─▶ JudgeOutcome ─▶ ShadowSink.write(log)
    brief store (last N) ┘

The overlay reuses the press/weather content of the daily brief but takes its
*base decision* from regime's live shadow call, not from the brief's own SIGNAL
block. regime already runs in shadow, so the whole regime->judge pipeline can be
observed end-to-end with zero production risk.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from . import config
from .llm import JudgeLLM
from .runner import decide
from .schema import BaseCall, Brief, Decision, JudgeOutcome


# --- Seams the product implements --------------------------------------------

class BriefStore(Protocol):
    """Source of the daily Compass briefs, oldest-first."""

    def load_recent(self, session_date: str, n: int) -> list[Brief]:
        """Return the ``n`` briefs up to and including ``session_date``.

        PROD: implement this against the brief store. Parse each stored brief
        with ``judge.brief_parser.parse_brief`` (accepts the raw brief text) or
        construct :class:`Brief` directly from the structured press/weather rows
        (``theme_sentiments`` etc.) if you prefer to skip the text parse.
        """
        ...


class ShadowSink(Protocol):
    """Where the overlay's per-session decision + reasoning is logged."""

    def write(self, log_fields: dict[str, object]) -> None:
        """PROD: persist to the shadow table (never to pl_indicator_daily)."""
        ...


@runtime_checkable
class RegimeDecisionLike(Protocol):
    """Duck-typed shape of `regime`'s RegimeDecision (see regime/pipeline.py)."""

    decision: str      # "OPEN" | "HEDGE" | "MONITOR"
    prob_up: float     # P(up) in [0, 1]
    regime: str
    specialist: str


# --- Mapping regime's call into a BaseCall ------------------------------------

def prob_up_to_confidence(prob_up: float) -> float:
    """Map regime P(up) to a 0-5 conviction for display/drift (not the policy).

    0.5 -> 0 (coin-flip), 0.0/1.0 -> 5 (max conviction). Linear in |p-0.5|.
    This value is informational context in the prompt; the policy gates on the
    *judge's* confidence, never on this.
    """
    return round(min(5.0, abs(prob_up - 0.5) * 10.0), 2)


def regime_base_call(rd: RegimeDecisionLike) -> BaseCall:
    """Build the overlay's base call from a regime decision."""
    decision = Decision(rd.decision)
    direction = {
        Decision.OPEN: "UP",
        Decision.HEDGE: "DOWN",
        Decision.MONITOR: "NEUTRAL",
    }[decision]
    return BaseCall(
        decision=decision,
        confidence=prob_up_to_confidence(rd.prob_up),
        direction_label=direction,
        source="regime/1.0.0",
    )


# --- Full-system entry point --------------------------------------------------

def run_shadow(
    *,
    session_date: str,
    regime_decision: RegimeDecisionLike,
    store: BriefStore,
    llm: JudgeLLM,
    sink: ShadowSink | None = None,
    window: int = config.BRIEF_WINDOW,
) -> JudgeOutcome:
    """Run regime -> judge for one session and log the outcome.

    PROD: call this once per session, after regime has produced its shadow
    decision and the day's brief has been generated/stored.
    """
    briefs = store.load_recent(session_date, window)
    if not briefs:
        raise ValueError(f"no briefs available up to {session_date}")

    base = regime_base_call(regime_decision)
    outcome = decide(briefs, llm, base_override=base)

    # Enrich the log with regime provenance for the pipeline analysis.
    outcome.log_fields.update(
        {
            "regime": regime_decision.regime,
            "specialist": regime_decision.specialist,
            "prob_up": regime_decision.prob_up,
        }
    )

    if sink is not None:
        sink.write(outcome.log_fields)  # PROD: shadow table write
    return outcome
