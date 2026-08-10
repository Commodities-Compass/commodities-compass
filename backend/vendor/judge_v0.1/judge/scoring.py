"""Production scoring rule (Hedi-mandated), for shadow evaluation.

Horizon: J+4 in production; the harness passes whatever realized move applies.
Reward is capped, penalty is unbounded, MONITOR is rewarded — the asymmetry is
what makes abstention a first-class outcome.

    correct OPEN/HEDGE : +1.25 if |move| > 1%, else +1.0
    wrong   OPEN/HEDGE : -2 * |move|
    MONITOR            : +1.0 if |move| > 1%, else +0.75

YTD = mean(scores) * 100.
"""

from __future__ import annotations

from .schema import Decision

BIG_MOVE: float = 0.01  # 1%


def score_decision(decision: Decision, move_pct: float) -> float:
    """Score one decision against a signed realized return (e.g. +0.0975).

    Args:
        decision: the committed stance.
        move_pct: signed fractional return over the horizon (0.0975 == +9.75%).
    """
    big = abs(move_pct) > BIG_MOVE

    if decision is Decision.MONITOR:
        return 1.0 if big else 0.75

    correct = (decision is Decision.OPEN and move_pct > 0) or (
        decision is Decision.HEDGE and move_pct < 0
    )
    if correct:
        return 1.25 if big else 1.0
    return -2.0 * abs(move_pct)


def ytd(scores: list[float]) -> float:
    """YTD performance = mean(scores) * 100. Empty -> 0.0."""
    return (sum(scores) / len(scores) * 100.0) if scores else 0.0
