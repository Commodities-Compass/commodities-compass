"""End-to-end: brief window -> drift -> judge -> policy -> logged outcome."""

from __future__ import annotations

import dataclasses

from . import policy, prompt
from .drift import compute_drift
from .llm import JudgeLLM
from .schema import BaseCall, Brief, JudgeOutcome


def decide(
    window: list[Brief],
    llm: JudgeLLM,
    base_override: BaseCall | None = None,
) -> JudgeOutcome:
    """Run the overlay for the last brief in ``window`` (oldest-first).

    ``base_override`` swaps today's base call for one supplied by an external
    algorithm (the full system passes `regime`'s shadow decision here). The
    brief's press/weather content is kept; only the decision + conviction move.
    """
    if not window:
        raise ValueError("empty brief window")

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
    rendered = prompt.render(window, drift)
    verdict = llm.judge(rendered, session_date=today.session_date)

    final = policy.fuse(today.base_decision, verdict)
    rationale = policy.explain(today.base_decision, verdict, final)

    log_fields: dict[str, object] = {
        "session_date": today.session_date,
        "base_source": (base_override.source if base_override else "brief_signal"),
        "base_decision": today.base_decision.value,
        "base_confidence": today.base_confidence,
        "final_decision": final.value,
        "changed": final is not today.base_decision,
        "judge_direction": verdict.suggested_direction.value,
        "judge_stance": verdict.stance.value,
        "judge_confidence": verdict.confidence,
        "is_anomaly": verdict.is_anomaly,
        "weather_series": list(drift.weather_impact_series),
        "prompt_version": verdict.prompt_version,
        "model_id": verdict.model_id,
        "rationale": rationale,
    }

    return JudgeOutcome(
        session_date=today.session_date,
        base_decision=today.base_decision,
        final_decision=final,
        changed=final is not today.base_decision,
        verdict=verdict,
        drift=drift,
        rationale=rationale,
        log_fields=log_fields,
    )
