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
from .schema import Brief, Direction, Drift, PriorJudgeRecord

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
- PRICE-VS-THESIS: you are given the recent price path. Before committing to a direction, \
reconcile it: if the market has ALREADY moved substantially in the direction your macro thesis \
implies, the story is likely PRICED IN — do NOT treat a persistent narrative as fresh news. \
Lower confidence and prefer MONITOR/keep over a fresh flip. A flip is justified only when the \
thesis is NOT yet reflected in price.
- YOUR OWN HISTORY: you are given your recent calls and how price moved since. If you have been \
calling the same direction and price has moved AGAINST you, treat that as strong evidence your \
thesis is stale/priced — be willing to unwind toward the base (or MONITOR) rather than double down.

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


def _price_block(drift: Drift) -> str:
    if drift.price_cum_move is None:
        return "PRICE ACTION over window: insufficient closes."
    steps = ", ".join(f"{m * 100:+.1f}%" for m in drift.price_step_moves)
    return (
        f"PRICE ACTION over window: cumulative {drift.price_cum_move * 100:+.1f}% "
        f"(session steps: {steps}). Has the market ALREADY moved in the direction your "
        f"macro thesis implies? If yes, the story is likely already priced."
    )


def _history_block(
    history: list[PriorJudgeRecord], today_close: float | None
) -> str:
    if not history:
        return "YOUR RECENT CALLS: none on record (first decision in the window)."
    lines = ["YOUR RECENT CALLS (reconcile against price since):"]
    for rec in reversed(history):  # most recent first
        move_txt, verdict = "n/a", ""
        if today_close is not None and rec.close:
            mv = (today_close - rec.close) / rec.close
            move_txt = f"{mv * 100:+.1f}%"
            if rec.suggested_direction is Direction.UP:
                verdict = " (WITH your call)" if mv > 0 else " (AGAINST your call)"
            elif rec.suggested_direction is Direction.DOWN:
                verdict = " (WITH your call)" if mv < 0 else " (AGAINST your call)"
        lines.append(
            f"- {rec.session_date}: you concluded {rec.final_decision.value} "
            f"(dir={rec.suggested_direction.value}, conf={rec.confidence}); "
            f"price since: {move_txt}{verdict}"
        )
    return "\n".join(lines)


def build_user_prompt(
    window: list[Brief],
    drift: Drift,
    history: list[PriorJudgeRecord] | None = None,
) -> str:
    """window is oldest-first; the last element is today's decision brief.

    ``history`` (oldest-first) is the judge's own prior decisions replayed so
    the LLM can reconcile against realised price moves. Backward-compatible:
    ``history=None`` renders the v0.1 prompt (no history block).
    """
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
        f"{_price_block(drift)}\n\n"
        f"{_history_block(history or [], today.close)}\n\n"
        f"{prior_blocks}\n{today_block}\n"
        "Judge the algorithm's call against this macro/press/weather picture. "
        "Return the JSON verdict."
    )


def render(
    window: list[Brief],
    drift: Drift,
    history: list[PriorJudgeRecord] | None = None,
) -> dict[str, str]:
    """Return {system, user, prompt_version} ready for an LLM call.

    ``history`` (oldest-first) is optional; when omitted the prompt renders
    without the YOUR RECENT CALLS block (v0.1-equivalent user text).
    """
    return {
        "system": SYSTEM_PROMPT,
        "user": build_user_prompt(window, drift, history=history),
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
