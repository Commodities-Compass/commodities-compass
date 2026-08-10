"""Assemble the calibrated judge prompt from a window of briefs + drift.

The prompt is versioned (config.PROMPT_VERSION). Design choices baked in:
- Rubric-anchored 1-5 confidence (not vibes).
- Grounding: cite >=2 concrete brief facts or be forced to NEUTRAL.
- Anti-hindsight: reason ONLY from the provided briefs, no outside price memory.
- Anti-confirmation: a mandatory disconfirming-case field.
The judge outputs a direction + confidence; the *policy* (code) decides.
"""

from __future__ import annotations

import json

from . import config
from .schema import Brief, Drift

SYSTEM_PROMPT = """You are the macro/press overlay ("judge") sitting on top of a purely technical \
cocoa trading algorithm. The algorithm is blind to news, weather and fundamentals; you are its \
eyes on the world. Your job is NOT to predict the market. It is to answer one question: does the \
macro/press/weather picture in the provided daily briefs CONFIRM, CONTRADICT, or stay NEUTRAL on \
the algorithm's directional call — and how strongly.

You detect DRIFT: the two older briefs are the baseline (what the market already knew); today's \
brief is the new information. A confirmation is the ~90% calm case. A real, escalating anomaly \
that cuts against the technical call is the rare, valuable case.

HARD RULES:
- Reason ONLY from the briefs and numbers provided below. Do NOT use any outside knowledge of \
where cocoa prices actually went. You are standing at the decision, blind to the outcome.
- Ground every claim: cite at least TWO concrete facts quoted from the briefs. If you cannot \
cite two, your stance MUST be NEUTRAL with confidence 1.
- Before concluding, state the disconfirming case (what would make the algorithm's call right).

CONFIDENCE RUBRIC (confidence in your stance, 1-5):
  5 = multiple independent briefs point the same way + a concrete named driver (weather event, \
crop number, stocks print, sharp repricing).
  4 = a clear directional signal, escalating across days, with a named driver and no strong \
counter-signal.
  3 = one clear signal but hedged/moderate, or a real signal partly offset by a counter-signal.
  2 = mixed/ambiguous; a weak lean at best.
  1 = noise; no discernible directional driver.

OUTPUT: a single valid JSON object, no markdown fences, with EXACTLY these keys:
  "suggested_direction": "UP" | "DOWN" | "NONE"   (the macro-implied price direction; NONE if none)
  "confidence": integer 1-5
  "stance": "CONFIRM" | "CONTRADICT" | "NEUTRAL"  (vs the algorithm's direction stated below)
  "is_anomaly": true | false                       (is today a real break from the baseline?)
  "evidence": [ "quoted fact 1", "quoted fact 2", ... ]
  "drift_summary": "one sentence on how the picture moved across the window"
  "disconfirming_case": "one sentence: what would make the algo's call correct"
  "key_risk": "one sentence"
Output ONLY the JSON object."""


def _brief_block(b: Brief, *, label: str) -> str:
    return (
        f"--- {label} (session {b.session_date}, off close {b.last_close_date}) ---\n"
        f"ALGO CALL: {b.base_decision.value} | direction={b.base_direction_label} "
        f"| algo_confidence={b.base_confidence:.1f}/5\n"
        f"TECHNICAL: close={b.close} volume={b.volume} rsi={b.rsi}\n"
        f"WEATHER: {b.weather.summary or 'n/a'}\n"
        f"PRESS REVIEW:\n{b.press.full_text()}\n"
    )


def build_user_prompt(window: list[Brief], drift: Drift) -> str:
    """window is oldest-first; the last element is today's decision brief."""
    if not window:
        raise ValueError("empty brief window")

    today = window[-1]
    priors = window[:-1]

    labels = [f"BASELINE T-{len(priors) - i}" for i in range(len(priors))]
    prior_blocks = "\n".join(_brief_block(b, label=lbl) for b, lbl in zip(priors, labels))
    today_block = _brief_block(today, label="TODAY (decide this)")

    drift_line = "; ".join(drift.notes) if drift.notes else "no strong numeric drift"
    weather_series = ", ".join(f"{x:.0f}" for x in drift.weather_impact_series) or "n/a"

    algo_dir = today.base_direction_label or today.base_decision.value

    return (
        f"The algorithm's call for session {today.session_date} is "
        f"{today.base_decision.value} (direction: {algo_dir}, its own confidence "
        f"{today.base_confidence:.1f}/5).\n\n"
        f"PRE-COMPUTED DRIFT over the window: {drift_line}. "
        f"Weather-impact series (oldest->newest): {weather_series}/10.\n\n"
        f"{prior_blocks}\n{today_block}\n"
        "Judge the algorithm's call against this macro/press/weather picture. "
        "Return the JSON verdict."
    )


def render(window: list[Brief], drift: Drift) -> dict[str, str]:
    """Return {system, user, prompt_version} ready for an LLM call."""
    return {
        "system": SYSTEM_PROMPT,
        "user": build_user_prompt(window, drift),
        "prompt_version": config.PROMPT_VERSION,
    }


def verdict_json_schema() -> dict:
    """JSON schema for structured-output enforcement on the prod path."""
    return {
        "type": "object",
        "properties": {
            "suggested_direction": {"enum": ["UP", "DOWN", "NONE"]},
            "confidence": {"type": "integer", "minimum": 1, "maximum": 5},
            "stance": {"enum": ["CONFIRM", "CONTRADICT", "NEUTRAL"]},
            "is_anomaly": {"type": "boolean"},
            "evidence": {"type": "array", "items": {"type": "string"}},
            "drift_summary": {"type": "string"},
            "disconfirming_case": {"type": "string"},
            "key_risk": {"type": "string"},
        },
        "required": [
            "suggested_direction", "confidence", "stance", "is_anomaly",
            "evidence", "drift_summary", "disconfirming_case", "key_risk",
        ],
        "additionalProperties": False,
    }


def dumps_schema() -> str:
    return json.dumps(verdict_json_schema(), indent=2)
