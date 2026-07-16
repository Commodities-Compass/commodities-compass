"""Accuracy gate: the LLM voice must never introduce an ungrounded number.

The deterministic renderer injects every fact number straight from the DB, so
the conclusion body is correct by construction. The LLM only writes the
qualitative headline (+ confiance_rationale / eco). This gate extracts every
*substantive* numeric token from that voice text and asserts each matches a
payload number within a rounding tolerance. A mismatch is a hallucinated or
mistyped figure — fail loud, never ship it (pipeline-error-handling rule).

Contextual small integers (session horizon "4 à 5", confiance "3") are ignored:
only numbers with a fractional part, or integers >= ``min_significant``, are
checked — those are the price / volume / indicator magnitudes that matter.
"""

from __future__ import annotations

import re

from scripts.daily_analysis.facts import FactsPayload

_NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


class AccuracyGateError(ValueError):
    """A number in the LLM voice is not grounded in the FactsPayload."""


def _extract_numbers(text: str) -> list[float]:
    out: list[float] = []
    for token in _NUMBER_RE.findall(text or ""):
        try:
            out.append(float(token.replace(",", "")))
        except ValueError:
            continue
    return out


def _is_checkable(n: float, min_significant: float) -> bool:
    """A fractional number is fact-like; a bare small integer is contextual."""
    if n != int(n):
        return True
    return abs(n) >= min_significant


def _is_grounded(n: float, grounded: list[float], tolerance: float) -> bool:
    for g in grounded:
        if g == 0:
            if abs(n) <= tolerance:
                return True
        elif abs(n - g) <= tolerance * max(1.0, abs(g)):
            return True
    return False


def assert_no_hallucinated_numbers(
    voice_text: str,
    facts: FactsPayload,
    *,
    tolerance: float = 0.01,
    min_significant: float = 10.0,
    ignore: frozenset[float] = frozenset(),
) -> None:
    """Raise :class:`AccuracyGateError` if the LLM voice cites an ungrounded number.

    ``tolerance`` is relative (default 1%) to absorb the renderer's ``:g``
    rounding. ``ignore`` is an explicit allowlist for known-safe magnitudes.
    """
    grounded = facts.all_numbers()
    for n in _extract_numbers(voice_text):
        if n in ignore or not _is_checkable(n, min_significant):
            continue
        if not _is_grounded(n, grounded, tolerance):
            raise AccuracyGateError(
                f"Number {n} in the LLM voice is not grounded in the facts "
                f"payload for {facts.session_date}. Grounded: {sorted(set(grounded))}"
            )
