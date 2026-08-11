"""Deterministic fusion policy: (base decision, judge verdict) -> final decision.

This is the auditable core. The LLM only *judges* (direction + confidence); the
*policy* — encoded here as a pure function — decides. All thresholds come from
config, so tuning never touches the prompt.

Principle (symmetric, big-weight-to-base):
- Judge weak (conf <= IGNORE) or no direction        -> keep base.
- Judge agrees with base direction                   -> keep base (confirm).
- Judge opposes a committed base, conf >= FLIP        -> flip to judge's side.
- Judge opposes a committed base, conf == CONFLICT    -> abstain (MONITOR).
- Base is MONITOR and judge has a direction, conf>=FLIP -> commit that direction.
- Base is MONITOR and judge has a direction, weaker    -> stay MONITOR.

MONITOR is triggered by genuine CONFLICT, never by quiet (see config).
"""

from __future__ import annotations

from . import config
from .schema import DECISION_DIRECTION, Decision, Direction, JudgeVerdict, Stance


def _commit_for(direction: Direction) -> Decision:
    return Decision.OPEN if direction is Direction.UP else Decision.HEDGE


def derive_stance(base: Decision, judge_dir: Direction) -> Stance:
    """Judge direction vs the base's direction, as a labelled stance."""
    base_dir = DECISION_DIRECTION[base]
    if judge_dir is Direction.NONE:
        return Stance.NEUTRAL
    if base_dir is Direction.NONE:
        # base abstained; any judge direction is a (potential) push to commit
        return Stance.CONTRADICT
    if judge_dir is base_dir:
        return Stance.CONFIRM
    return Stance.CONTRADICT


def fuse(base: Decision, verdict: JudgeVerdict) -> Decision:
    """Resolve the base call and the judge verdict into a final decision."""
    judge_dir = verdict.suggested_direction
    conf = verdict.confidence

    # Judge is noise or silent -> the base carries (the ~90% calm case).
    if judge_dir is Direction.NONE or conf <= config.IGNORE_CONF_MAX:
        return base

    base_dir = DECISION_DIRECTION[base]

    # Judge agrees with the base's committed direction -> confirm.
    if judge_dir is base_dir:
        return base

    # From here the judge points somewhere the base did not commit to.
    strong = conf >= config.FLIP_CONF_MIN

    if base_dir is not Direction.NONE:
        # Base committed and judge opposes it.
        return _commit_for(judge_dir) if strong else Decision.MONITOR

    # Base is MONITOR; judge sees a direction.
    return _commit_for(judge_dir) if strong else Decision.MONITOR


def explain(base: Decision, verdict: JudgeVerdict, final: Decision) -> str:
    """One-line human rationale for the log."""
    stance = derive_stance(base, verdict.suggested_direction)
    if final is base:
        return (
            f"KEEP {base.value}: judge {stance.value.lower()} "
            f"(dir={verdict.suggested_direction.value}, conf={verdict.confidence})."
        )
    if final is Decision.MONITOR:
        return (
            f"ABSTAIN {base.value}->MONITOR: judge contradicts at conf="
            f"{verdict.confidence} (< flip bar {config.FLIP_CONF_MIN})."
        )
    return (
        f"OVERRIDE {base.value}->{final.value}: judge {stance.value.lower()} "
        f"dir={verdict.suggested_direction.value} at conf={verdict.confidence} "
        f">= flip bar {config.FLIP_CONF_MIN}."
    )
