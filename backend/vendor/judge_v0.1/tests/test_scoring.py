"""Production scoring rule."""

from __future__ import annotations

import pytest

from judge.schema import Decision
from judge.scoring import score_decision, ytd


def test_wrong_hedge_into_big_up_move_matches_reference():
    # The 07-31 case: HEDGE, +9.75% -> -2*0.0975 = -0.195
    assert score_decision(Decision.HEDGE, 0.0975) == pytest.approx(-0.195)


def test_flip_to_open_wins_big():
    assert score_decision(Decision.OPEN, 0.0975) == 1.25


def test_monitor_rewarded_on_big_move():
    assert score_decision(Decision.MONITOR, 0.0975) == 1.0


def test_monitor_quiet_day():
    assert score_decision(Decision.MONITOR, 0.005) == 0.75


def test_correct_small_move_open():
    assert score_decision(Decision.OPEN, 0.004) == 1.0


def test_correct_hedge_down():
    assert score_decision(Decision.HEDGE, -0.03) == 1.25


@pytest.mark.parametrize(
    "swing",
    [
        # (base score, flip score, monitor score) for the +9.75% miss
        (score_decision(Decision.HEDGE, 0.0975), score_decision(Decision.OPEN, 0.0975)),
    ],
)
def test_overlay_swing_is_large(swing):
    base, flipped = swing
    assert flipped - base > 1.4  # +1.25 - (-0.195) = 1.445


def test_ytd_is_mean_times_100():
    assert ytd([1.25, -0.195, 1.0]) == pytest.approx((1.25 - 0.195 + 1.0) / 3 * 100)
    assert ytd([]) == 0.0
