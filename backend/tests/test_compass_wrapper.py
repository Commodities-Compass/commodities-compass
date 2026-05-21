"""Tests for the Compass-side wrapper override.

Covers the AND-gated relaxation of cluster_dispersion veto:
- vendor wrapper's OR logic is preserved when running_acc is unhealthy
- dispersion-only veto is released when running_acc is healthy (≥ threshold)
- NaN running_acc (bootstrap window) stays conservative (veto preserved)
- non-dispersion vetoes (running_acc, trend, three-way) are never relaxed
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import cast

import pandas as pd
import pytest
from ensemble.orchestrator.transition_wrapper import WrapperConfig

from scripts.ensemble_compute.compass_wrapper import (
    CompassTransitionWrapper,
)


def _config() -> WrapperConfig:
    """Match the frozen tpw_v1 active detectors."""
    return WrapperConfig(
        use_running_acc=True,
        tau_run=0.5931,
        running_window=5,
        min_running_n=2,
        use_trend_conflict=False,
        tau_trend=0.030,
        trend_window=7,
        use_cluster_dispersion=True,
        min_cluster_n=2,
        use_three_way_disagreement=False,
    )


def _cluster_mapping() -> dict[str, str]:
    """Two-specialist cluster mapping that makes dispersion fire easy."""
    return {"w1": "winter", "w2": "winter", "s1": "spring", "s2": "spring"}


def _bidate(n: int) -> list[pd.Timestamp]:
    """Build N consecutive timestamps from a fixed concrete datetime base.

    Cast is safe — `pd.Timestamp(datetime(...))` never returns NaT for a
    concrete datetime input; pandas' return type is conservative only
    because it must cover the NaT input case.
    """
    base = datetime(2026, 1, 5)
    return [
        cast(pd.Timestamp, pd.Timestamp(base + timedelta(days=i))) for i in range(n)
    ]


def _seed_decisions(
    dates: list[pd.Timestamp], today_decision: str = "OPEN"
) -> pd.DataFrame:
    """Build a decisions_df with N-1 prior committed-correct rows + today."""
    rows: list[dict] = []
    for i, d in enumerate(dates):
        is_today = i == len(dates) - 1
        rows.append(
            {
                "date": d,
                "decision": today_decision if is_today else "OPEN",
                "net_score": 0.4 if is_today else 0.3,
                "macro_direction": 0,
                "prior_open": 0.6,
                "prior_hedge": 0.2,
                "prior_monitor": 0.2,
                "committed": False if is_today else True,
                "correct": False if is_today else True,
                "forward_return": 0.02 if is_today else 0.01,
            }
        )
    return pd.DataFrame(rows)


def _seed_votes_dispersed(today: pd.Timestamp) -> pd.DataFrame:
    """Winter committed bullish (OPEN x2), Spring committed bearish (HEDGE x2)."""
    return pd.DataFrame(
        [
            {"date": today, "specialist_name": "w1", "pred": "OPEN"},
            {"date": today, "specialist_name": "w2", "pred": "OPEN"},
            {"date": today, "specialist_name": "s1", "pred": "HEDGE"},
            {"date": today, "specialist_name": "s2", "pred": "HEDGE"},
        ]
    )


def _seed_votes_aligned(today: pd.Timestamp) -> pd.DataFrame:
    """All 4 specialists vote OPEN — no dispersion."""
    return pd.DataFrame(
        [
            {"date": today, "specialist_name": name, "pred": "OPEN"}
            for name in ("w1", "w2", "s1", "s2")
        ]
    )


def _returns(dates: list[pd.Timestamp]) -> pd.Series:
    """Flat ~0% daily returns (so trend detector — if on — would not fire)."""
    return pd.Series([0.0001] * len(dates), index=dates)


@pytest.mark.unit
def test_release_dispersion_only_when_running_acc_healthy() -> None:
    """Dispersion fires alone, running_acc=1.0 → commit released."""
    dates = _bidate(5)
    today = dates[-1]
    # 4 priors all committed+correct → running_acc = 1.0
    decisions = _seed_decisions(dates, today_decision="OPEN")
    votes = _seed_votes_dispersed(today)
    wrapper = CompassTransitionWrapper(
        config=_config(),
        cluster_mapping=_cluster_mapping(),
        dispersion_with_acc_threshold=0.70,
    )
    wrapped, diag = wrapper.apply(decisions, votes, _returns(dates))
    today_row = wrapped[wrapped["date"] == today].iloc[0]
    assert bool(today_row["fired_dispersion"]) is True
    assert bool(today_row["fired_running_acc"]) is False
    assert today_row["decision_wrapped"] == "OPEN"  # released
    assert bool(today_row["wrapper_active"]) is False
    assert bool(today_row["committed_wrapped"]) is True
    today_diag = diag[diag["date"] == today].iloc[0]
    assert today_diag["final_decision"] == "OPEN"
    assert bool(today_diag["any_fired"]) is False


@pytest.mark.unit
def test_veto_when_dispersion_and_running_acc_unhealthy() -> None:
    """Both detectors fire → veto preserved (legitimate)."""
    dates = _bidate(5)
    today = dates[-1]
    decisions = _seed_decisions(dates, today_decision="OPEN")
    # Flip the trailing accuracy to 0/4 so running_acc=0.0 < tau_run=0.5931
    decisions.loc[decisions["date"] != today, "correct"] = False
    votes = _seed_votes_dispersed(today)
    wrapper = CompassTransitionWrapper(
        config=_config(),
        cluster_mapping=_cluster_mapping(),
        dispersion_with_acc_threshold=0.70,
    )
    wrapped, _ = wrapper.apply(decisions, votes, _returns(dates))
    today_row = wrapped[wrapped["date"] == today].iloc[0]
    assert bool(today_row["fired_running_acc"]) is True
    assert bool(today_row["fired_dispersion"]) is True
    assert today_row["decision_wrapped"] == "MONITOR"  # veto preserved


@pytest.mark.unit
def test_veto_when_running_acc_alone_fires() -> None:
    """Running_acc fires, no dispersion → veto preserved (gate-accuracy rule)."""
    dates = _bidate(5)
    today = dates[-1]
    decisions = _seed_decisions(dates, today_decision="OPEN")
    decisions.loc[decisions["date"] != today, "correct"] = False
    votes = _seed_votes_aligned(today)  # no dispersion
    wrapper = CompassTransitionWrapper(
        config=_config(),
        cluster_mapping=_cluster_mapping(),
        dispersion_with_acc_threshold=0.70,
    )
    wrapped, _ = wrapper.apply(decisions, votes, _returns(dates))
    today_row = wrapped[wrapped["date"] == today].iloc[0]
    assert bool(today_row["fired_running_acc"]) is True
    assert bool(today_row["fired_dispersion"]) is False
    assert today_row["decision_wrapped"] == "MONITOR"


@pytest.mark.unit
def test_commit_when_no_detector_fires() -> None:
    """Neither detector fires → original commit unchanged."""
    dates = _bidate(5)
    today = dates[-1]
    decisions = _seed_decisions(dates, today_decision="OPEN")
    votes = _seed_votes_aligned(today)  # no dispersion
    wrapper = CompassTransitionWrapper(
        config=_config(),
        cluster_mapping=_cluster_mapping(),
        dispersion_with_acc_threshold=0.70,
    )
    wrapped, _ = wrapper.apply(decisions, votes, _returns(dates))
    today_row = wrapped[wrapped["date"] == today].iloc[0]
    assert bool(today_row["fired_running_acc"]) is False
    assert bool(today_row["fired_dispersion"]) is False
    assert today_row["decision_wrapped"] == "OPEN"


@pytest.mark.unit
def test_nan_running_acc_releases_dispersion_only() -> None:
    """Bootstrap: not enough prior committed rows → running_acc=NaN.

    With no accuracy signal available, the dispersion-only veto is too weak
    to be trusted on its own — default-allow releases the commit. This is the
    behaviour that lets coverage climb out of the cold-start hole.
    """
    dates = _bidate(2)  # only 1 prior row → min_running_n=2 unmet
    today = dates[-1]
    decisions = _seed_decisions(dates, today_decision="OPEN")
    votes = _seed_votes_dispersed(today)
    wrapper = CompassTransitionWrapper(
        config=_config(),
        cluster_mapping=_cluster_mapping(),
        dispersion_with_acc_threshold=0.60,
    )
    wrapped, _ = wrapper.apply(decisions, votes, _returns(dates))
    today_row = wrapped[wrapped["date"] == today].iloc[0]
    assert bool(today_row["fired_dispersion"]) is True
    assert math.isnan(float(today_row["running_acc_5d"]))
    # NaN + dispersion only → released (default-allow on bootstrap).
    assert today_row["decision_wrapped"] == "OPEN"
    assert bool(today_row["wrapper_active"]) is False
