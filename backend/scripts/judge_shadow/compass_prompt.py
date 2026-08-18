"""Compass judge prompt v0.3 — event detection, not sentiment summarisation.

Owned by Compass. ``vendor/judge_v0.1/`` stays untouched (read-only delivery,
same convention as the ensemble pack); this module overrides the two ends of the
vendor seam — what we ask, and how we fuse — while reusing its ``Brief`` /
``Drift`` / ``JudgeVerdict`` types so everything downstream is unchanged.

### Why a v0.3 at all

Measured over 20 replayed sessions, the v0.2 judge's direction was right 40 % of
the time — worse than a coin flip — and informative only at confidence 4 (3/4).
Two causes, both visible in what it wrote:

1. **It graded continuations like events.** "L'abondance des arrivages ivoiriens
   continue de peser" appeared on 07-30, 07-31, 08-03 and 08-04, and it kept
   citing it as fresh evidence. That is the chase: a persistent narrative read as
   new information, four days running.
2. **It ignored horizon.** A brief mixes tomorrow's flows with next season's crop
   ("contraction de plus de 10 % de la récolte 2026/27"). The decision is for the
   NEXT session; a 2027 crop forecast cannot move tomorrow's close, yet it was
   weighed as if it could.

The 2026-07-31 anchor case shows the shape of a real trigger. The 30th and the
31st repeat each other almost word for word — slow Ivorian arrivals, Ghanaian
farmgate price unchanged, 400 000 Afarinick seedlings for the third day — except
for one line that appears on the 31st and nowhere before:

    "d'après Confectionery News Cocoa, Barry Callebaut alerte sur une
     intensification des risques climatiques dans les zones clés"

A named actor, a dated alert, absent from the baseline. The market moved +9,75 %
the next session. That is what the judge exists to catch, and it is the ONLY
thing it is asked to look for here.

### What changed in the contract

The 1-5 confidence is gone. It was asked to carry two incompatible jobs — how
strong is the macro signal, and should we act — and the v0.2 prompt made it worse
by instructing the model to *lower* it when the story looked priced in, which
silently destroyed the signal (07-31 scored 2 instead of 4). The output is now
three states: OPEN, HEDGE, or NO_READ. Either there is an event worth trading, or
there is not.

Confidence is still written to ``pl_judge_shadow`` because the column is NOT NULL
and the diagnostics endpoint reads it — mapped from the verdict, not asked of the
model. See ``compass_judge.to_verdict``.
"""

from __future__ import annotations

import json
from typing import Any

from judge.schema import Brief, Direction, Drift, Stance  # type: ignore

PROMPT_VERSION = "compass_judge_v0.3"

SYSTEM_PROMPT = """You are a senior cocoa market analyst. You are handed three \
consecutive daily press briefs. A purely technical algorithm has already made a \
directional call for the NEXT trading session; it is blind to news, weather and \
fundamentals.

Your ONLY job: decide whether TODAY's brief contains a NEW EVENT that would make \
a cocoa desk position differently tomorrow than the algorithm does. You are not \
summarising sentiment. You are looking for one thing.

WHAT COUNTS AS A NEW EVENT — all three must hold:
  1. A NAMED actor says or does something on a dated occasion: an alert, a \
revision, an official decision, a disclosure, a print, a disruption. \
("Barry Callebaut warns…", "COCOBOD sets…", "StoneX revises…", "GEPEX reports…")
  2. It is ABSENT from the two prior briefs. If the same fact is already in the \
baseline, it is not new — however loudly today restates it.
  3. It can plausibly move a price WITHIN DAYS: physical flows, logistics, port \
or shipping disruption, immediate weather, an official price or policy decision \
taking effect, a demand/grindings print, a major operator's warning.

WHAT IS NOT AN EVENT — these can never justify overriding the algorithm:
  - A fact restated from a prior brief, even in stronger words. Watch the \
continuation markers: "continue", "reste", "persiste", "toujours", "confirme", \
"comme la veille", "still", "remains", "ongoing".
  - Commentary about the PRICE itself ("les cours s'envolent", "prices soar", \
"a sharp rally"). The algorithm already sees price; repeating it back is circular.
  - STRUCTURAL or NEXT-SEASON items: crop forecasts for a future campaign, \
replanting or seedling programmes, multi-year trade policy, long-run balance \
estimates. They matter, but they cannot move tomorrow's close. Put them in \
key_risk — never in the verdict.
  - Absence of news, a calm market, or general balance commentary.

YOUR VERDICT:
  - NO_READ is the normal answer. Most days carry no event. Say NO_READ and the \
algorithm keeps its call — that is the correct, common outcome, not a failure.
  - If and only if there is a new event, give the side a desk would lean to for \
tomorrow: OPEN (long / price up) or HEDGE (protect / price down).
  - An event only counts if you can state in ONE sentence why someone repositions \
tomorrow morning because of it. If you cannot, it is not actionable → NO_READ.

GROUNDING: quote the event VERBATIM from today's brief. If you cannot quote it \
from today's brief, it does not exist → NO_READ.

ANTI-HINDSIGHT: you do not know where prices actually went. Reason only from the \
briefs below.

OUTPUT: a single valid JSON object, no markdown fences, EXACTLY these keys:
  "new_event": true | false
  "event_quote": string | null      (verbatim from TODAY's brief; null if none)
  "event_actor": string | null      (who announced it; null if none)
  "verdict": "OPEN" | "HEDGE" | "NO_READ"
  "why_tomorrow": string | null     (one sentence: why a desk repositions tomorrow)
  "drift_summary": string           (one sentence on how the picture moved)
  "disconfirming_case": string      (one sentence: what would make the algo right)
  "key_risk": string                (one sentence; park structural items here)
Output ONLY the JSON object."""


def _brief_block(b: Brief, *, label: str) -> str:
    """One brief, without the algo's own call on the priors.

    The vendor block prints ALGO CALL on every brief. Here only today's call is
    shown (in the header): a prior day's technical stance is not evidence about
    tomorrow, and printing it invited the model to reason about the algorithm's
    consistency instead of about the news.
    """
    return (
        f"--- {label} (session {b.session_date}) ---\n"
        f"WEATHER: {b.weather.summary or 'n/a'}\n"
        f"PRESS REVIEW:\n{b.press.full_text()}\n"
    )


def build_user_prompt(window: list[Brief], drift: Drift) -> str:
    """Render the decision prompt. ``window`` is oldest-first, today last.

    Deliberately omits the price-path and own-history blocks the v0.2 prompt
    added. Both were attempts to damp the chase by making the model second-guess
    its own conviction; the chase is now handled where it belongs — by refusing
    to treat a continuation as an event — and leaving them in would re-introduce
    the confidence-vetoing that lost the 07-31 case.
    """
    if not window:
        raise ValueError("empty brief window")

    today = window[-1]
    priors = window[:-1]
    labels = [f"BASELINE T-{len(priors) - i}" for i in range(len(priors))]
    prior_blocks = "\n".join(
        _brief_block(b, label=lbl) for b, lbl in zip(priors, labels)
    )
    weather_series = ", ".join(f"{x:.0f}" for x in drift.weather_impact_series) or "n/a"
    algo_dir = today.base_direction_label or today.base_decision.value

    return (
        f"The algorithm's call for the session after {today.session_date} is "
        f"{today.base_decision.value} (direction: {algo_dir}).\n\n"
        f"Weather-impact series over the window (oldest->newest): "
        f"{weather_series}/10.\n\n"
        f"The two BASELINE briefs are what the market already knew. Read them "
        f"first, then read TODAY and ask: what is in today that is not in them?\n\n"
        f"{prior_blocks}\n"
        f"{_brief_block(today, label='TODAY (decide on this one)')}\n"
        "Is there a NEW EVENT in today's brief? Return the JSON verdict."
    )


def render(window: list[Brief], drift: Drift) -> dict[str, str]:
    """Return ``{system, user, prompt_version}`` ready for the LLM adapter."""
    return {
        "system": SYSTEM_PROMPT,
        "user": build_user_prompt(window, drift),
        "prompt_version": PROMPT_VERSION,
    }


class CompassVerdictError(ValueError):
    """The model returned something that is not a usable v0.3 verdict."""


def parse(raw: str | dict[str, Any]) -> dict[str, Any]:
    """Validate the model's JSON into a normalised dict — fail loud.

    A malformed verdict is not degraded into NO_READ: silently turning a parse
    failure into "no event today" is indistinguishable from a real quiet day,
    and it would hide a broken prompt for weeks.
    """
    data = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(data, dict):
        raise CompassVerdictError(f"expected a JSON object, got {type(data).__name__}")

    verdict = str(data.get("verdict", "")).upper()
    if verdict not in {"OPEN", "HEDGE", "NO_READ"}:
        raise CompassVerdictError(f"verdict={verdict!r} not in OPEN|HEDGE|NO_READ")

    new_event = bool(data.get("new_event"))
    quote = data.get("event_quote") or None

    # The model must not claim an event it cannot quote. Downgrading here rather
    # than raising: an unquoted event is exactly the hallucination the grounding
    # rule targets, and the safe reading of it is "no event".
    if new_event and not quote:
        new_event, verdict = False, "NO_READ"

    # A direction without an event cannot override — the whole point of v0.3.
    if verdict != "NO_READ" and not new_event:
        verdict = "NO_READ"

    return {
        "new_event": new_event,
        "event_quote": quote,
        "event_actor": data.get("event_actor") or None,
        "verdict": verdict,
        "why_tomorrow": data.get("why_tomorrow") or None,
        "drift_summary": str(data.get("drift_summary") or ""),
        "disconfirming_case": str(data.get("disconfirming_case") or ""),
        "key_risk": str(data.get("key_risk") or ""),
    }


VERDICT_DIRECTION = {
    "OPEN": Direction.UP,
    "HEDGE": Direction.DOWN,
    "NO_READ": Direction.NONE,
}


def stance_for(verdict: str, base_direction: Direction) -> Stance:
    """How the verdict reads against the algorithm's own direction."""
    direction = VERDICT_DIRECTION[verdict]
    if direction is Direction.NONE:
        return Stance.NEUTRAL
    if direction is base_direction:
        return Stance.CONFIRM
    return Stance.CONTRADICT
