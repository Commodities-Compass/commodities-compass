"""Deterministic fusion policy — the auditable core."""

from __future__ import annotations

import pytest

from judge.policy import derive_stance, fuse
from judge.schema import Decision, Direction, JudgeVerdict, Stance


def _verdict(direction: Direction, conf: int) -> JudgeVerdict:
    return JudgeVerdict(
        suggested_direction=direction,
        confidence=conf,
        stance=Stance.NEUTRAL,
        is_anomaly=False,
        evidence=("a", "b"),
        drift_summary="",
        disconfirming_case="",
        key_risk="",
    )


# --- keep-base cases ---------------------------------------------------------

@pytest.mark.parametrize("base", [Decision.OPEN, Decision.HEDGE, Decision.MONITOR])
def test_no_direction_keeps_base(base):
    assert fuse(base, _verdict(Direction.NONE, 5)) is base


@pytest.mark.parametrize("base", [Decision.OPEN, Decision.HEDGE, Decision.MONITOR])
@pytest.mark.parametrize("conf", [1, 2])
def test_low_confidence_keeps_base(base, conf):
    assert fuse(base, _verdict(Direction.UP, conf)) is base


def test_agreeing_direction_keeps_base():
    assert fuse(Decision.OPEN, _verdict(Direction.UP, 5)) is Decision.OPEN
    assert fuse(Decision.HEDGE, _verdict(Direction.DOWN, 5)) is Decision.HEDGE


# --- abstain (conflict, below flip bar) --------------------------------------

def test_hedge_contradicted_conf3_abstains():
    assert fuse(Decision.HEDGE, _verdict(Direction.UP, 3)) is Decision.MONITOR


def test_open_contradicted_conf3_abstains():
    assert fuse(Decision.OPEN, _verdict(Direction.DOWN, 3)) is Decision.MONITOR


# --- flip (symmetric, conf >= 4) ---------------------------------------------

def test_hedge_flips_to_open_on_strong_up():
    assert fuse(Decision.HEDGE, _verdict(Direction.UP, 4)) is Decision.OPEN


def test_open_flips_to_hedge_on_strong_down():
    # symmetric power (Hedi's call): the layer may open a fresh down bet too
    assert fuse(Decision.OPEN, _verdict(Direction.DOWN, 5)) is Decision.HEDGE


# --- MONITOR base can be pushed to commit ------------------------------------

def test_monitor_commits_on_strong_direction():
    assert fuse(Decision.MONITOR, _verdict(Direction.UP, 4)) is Decision.OPEN
    assert fuse(Decision.MONITOR, _verdict(Direction.DOWN, 4)) is Decision.HEDGE


def test_monitor_stays_on_moderate_direction():
    assert fuse(Decision.MONITOR, _verdict(Direction.UP, 3)) is Decision.MONITOR


# --- stance derivation -------------------------------------------------------

def test_derive_stance():
    assert derive_stance(Decision.HEDGE, Direction.UP) is Stance.CONTRADICT
    assert derive_stance(Decision.HEDGE, Direction.DOWN) is Stance.CONFIRM
    assert derive_stance(Decision.OPEN, Direction.NONE) is Stance.NEUTRAL
    assert derive_stance(Decision.MONITOR, Direction.UP) is Stance.CONTRADICT
