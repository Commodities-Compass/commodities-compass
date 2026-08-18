"""Compass judge v0.3 — the decide seam, owned by Compass.

Mirrors ``judge.runner.decide`` but swaps the two ends: our prompt
(``compass_prompt``) and our fusion rule. The vendor's ``Brief`` / ``Drift`` /
``compute_drift`` / ``JudgeOutcome`` are reused as-is, so the writer, the
diagnostics endpoint and the brief see exactly the same shapes they always did.

Same pattern as ``ensemble_compute/compass_wrapper.py``: the R&D delivery stays
read-only and a Compass module carries the override.

### The fusion rule

    no event                      -> the algorithm keeps its call
    event, same side as the algo  -> the algorithm keeps its call (confirmation)
    event, opposite side          -> OVERRIDE

There is no confidence threshold, and no MONITOR path. Both were measured and
both were the problem:

* the 1-5 confidence was only informative at 4 (3/4 right; 0,25-0,33 below), and
  the v0.2 prompt actively corrupted it by asking the model to lower it when a
  story looked priced in — which is how the 2026-07-31 case scored 2 and was
  ignored;
* routing a contradiction to MONITOR looked like a cheap hedge but the three
  MONITOR downgrades in the forward window were all on contradictions that were
  wrong, each costing -0,25 against a regime call that was right.

What replaces them is a qualifier the model can actually answer: is there a new,
named, dated, quotable event in today's brief that is absent from the two prior
ones? An override now requires an identifiable cause, which is also what makes
it auditable after the fact — ``event_quote`` is in the row.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from judge.drift import compute_drift  # type: ignore
from judge.schema import (  # type: ignore
    Brief,
    Decision,
    Direction,
    JudgeOutcome,
    JudgeVerdict,
)

from scripts.judge_shadow import compass_prompt

logger = logging.getLogger(__name__)

# Written to pl_judge_shadow.judge_confidence, which is NOT NULL and read by
# /dashboard/judge-diagnostics. v0.3 does not ask the model for a 1-5 score, so
# these are a projection of the verdict, not an opinion: an actionable event is
# the only thing that moves a decision, and NO_READ is the quiet default.
CONFIDENCE_EVENT = 4
CONFIDENCE_NO_READ = 1

_BASE_DIRECTION = {
    Decision.OPEN: Direction.UP,
    Decision.HEDGE: Direction.DOWN,
    Decision.MONITOR: Direction.NONE,
}


class RawJudgeLLM(Protocol):
    """An adapter that returns the model's raw JSON string for a rendered prompt."""

    def judge_raw(self, rendered: dict[str, str], *, session_date: str) -> str: ...


def to_verdict(
    parsed: dict[str, Any], *, base: Decision, model_id: str
) -> JudgeVerdict:
    """Project a v0.3 parse onto the vendor's ``JudgeVerdict`` shape.

    ``evidence`` carries the single quoted event rather than the two-or-more
    quotes v0.1 required: under v0.3 one *quotable, attributable* event is worth
    more than two paraphrases, and the "cite at least two" rule is what pushed
    the model to pad with price commentary.
    """
    verdict = parsed["verdict"]
    evidence: list[str] = []
    if parsed["event_quote"]:
        actor = parsed["event_actor"]
        evidence.append(
            f"{actor}: {parsed['event_quote']}" if actor else parsed["event_quote"]
        )
    if parsed["why_tomorrow"]:
        evidence.append(parsed["why_tomorrow"])

    return JudgeVerdict(
        suggested_direction=compass_prompt.VERDICT_DIRECTION[verdict],
        confidence=CONFIDENCE_EVENT if verdict != "NO_READ" else CONFIDENCE_NO_READ,
        stance=compass_prompt.stance_for(verdict, _BASE_DIRECTION[base]),
        is_anomaly=parsed["new_event"],
        evidence=tuple(evidence),
        drift_summary=parsed["drift_summary"],
        disconfirming_case=parsed["disconfirming_case"],
        key_risk=parsed["key_risk"],
        prompt_version=compass_prompt.PROMPT_VERSION,
        model_id=model_id,
    )


def fuse(base: Decision, parsed: dict[str, Any]) -> Decision:
    """Event-gated override. Returns the decision actually served."""
    verdict = parsed["verdict"]
    if verdict == "NO_READ" or not parsed["new_event"]:
        return base
    side = Decision.OPEN if verdict == "OPEN" else Decision.HEDGE
    return base if side == base else side


def explain(base: Decision, parsed: dict[str, Any], final: Decision) -> str:
    """One-line audit trace. Never leaves the database — judge-only, by decision."""
    if final != base:
        actor = parsed["event_actor"] or "unattributed"
        return (
            f"OVERRIDE {base.value}->{final.value}: new event ({actor}) "
            f"reads {parsed['verdict']}"
        )
    if parsed["new_event"]:
        return f"KEEP {base.value}: event confirms the algorithm's side"
    return f"KEEP {base.value}: no new event in today's brief"


def decide(
    window: list[Brief],
    llm: RawJudgeLLM,
    base_override: Any = None,
    model_id: str = "",
) -> JudgeOutcome:
    """Run the v0.3 overlay on the last brief of ``window`` (oldest-first).

    ``base_override`` swaps today's call for the one regime actually made — the
    same seam the vendor exposes, kept so the caller does not change.
    """
    if not window:
        raise ValueError("empty brief window")

    import dataclasses

    today = window[-1]
    if base_override is not None:
        today = dataclasses.replace(
            today,
            base_decision=base_override.decision,
            base_confidence=base_override.confidence,
            base_direction_label=base_override.direction_label
            or today.base_direction_label,
        )
        window = [*window[:-1], today]

    drift = compute_drift(window)
    rendered = compass_prompt.render(window, drift)
    parsed = compass_prompt.parse(
        llm.judge_raw(rendered, session_date=today.session_date)
    )

    final = fuse(today.base_decision, parsed)
    verdict = to_verdict(parsed, base=today.base_decision, model_id=model_id)
    rationale = explain(today.base_decision, parsed, final)

    if final != today.base_decision:
        logger.info(
            "judge(%s): OVERRIDE %s -> %s on event by %s",
            today.session_date,
            today.base_decision.value,
            final.value,
            parsed["event_actor"] or "?",
        )

    return JudgeOutcome(
        session_date=today.session_date,
        base_decision=today.base_decision,
        final_decision=final,
        changed=final != today.base_decision,
        verdict=verdict,
        drift=drift,
        rationale=rationale,
        log_fields={
            "base_source": (base_override.source if base_override else "brief_signal"),
            "prompt_version": compass_prompt.PROMPT_VERSION,
            "model_id": model_id,
        },
    )
