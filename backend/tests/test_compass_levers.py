"""Tests for the Compass levers added 2026-06: trend-conflict plumbing, regime-MONITOR,
alpha_macro cap, config-as-data wrapper loader.

Covers the new pure decision logic deterministically (no DB):
- _regime_monitor_fires: fires only on committed decisions in a top-vol regime
- _macro_half_life_days: piecewise mirror of MacroEventLayer
- _cast_to_field: bool/int/float coercion + drift fail-loud
- CompassTransitionWrapper captures fired_trend / fired_three_way
"""

from __future__ import annotations

import dataclasses

import pandas as pd
import pytest
from ensemble.orchestrator.transition_wrapper import WrapperConfig

from scripts.ensemble_compute.cluster_mapping_loader import (
    WrapperConfigDriftError,
    _cast_to_field,
)
from scripts.ensemble_compute.compass_wrapper import CompassTransitionWrapper
from scripts.ensemble_compute.main import (
    _macro_half_life_days,
    _regime_monitor_fires,
)


def _market(atr_pct_series: list[float], close: float = 3000.0) -> pd.DataFrame:
    """Build a market_history-shaped frame with a given atr% path (last row = today)."""
    return pd.DataFrame(
        {
            "close": [close] * len(atr_pct_series),
            "atr_14d": [p * close for p in atr_pct_series],
        }
    )


# ----------------------------- regime-MONITOR -----------------------------
def test_regime_monitor_off_when_threshold_none() -> None:
    m = _market([0.05] * 100)
    assert _regime_monitor_fires(m, None, "HEDGE") is False


def test_regime_monitor_off_when_already_monitor() -> None:
    m = _market([0.09] * 100)  # blown-out vol
    assert _regime_monitor_fires(m, 0.80, "MONITOR") is False


def test_regime_monitor_fires_on_committed_top_vol() -> None:
    # 99 calm days + a today value above all of them → percentile = 1.0 > 0.80.
    m = _market([0.03] * 99 + [0.09])
    assert _regime_monitor_fires(m, 0.80, "HEDGE") is True
    assert _regime_monitor_fires(m, 0.80, "OPEN") is True


def test_regime_monitor_quiet_when_today_low_vol() -> None:
    m = _market([0.09] * 99 + [0.02])  # today is the calmest → low percentile
    assert _regime_monitor_fires(m, 0.80, "HEDGE") is False


def test_regime_monitor_needs_enough_history() -> None:
    m = _market([0.09] * 30)  # < 60 rows → no override
    assert _regime_monitor_fires(m, 0.80, "HEDGE") is False


# ----------------------------- macro half-life ----------------------------
@pytest.mark.parametrize(
    "surprise,expected",
    [(0.0, 1), (0.29, 1), (0.30, 3), (0.59, 3), (0.60, 7), (0.95, 7)],
)
def test_macro_half_life_days(surprise: float, expected: int) -> None:
    assert _macro_half_life_days(surprise) == expected


# ----------------------------- config casting -----------------------------
def _field(name: str) -> dataclasses.Field:
    return {f.name: f for f in dataclasses.fields(WrapperConfig)}[name]


def test_cast_bool_truthy_falsy() -> None:
    assert _cast_to_field(_field("use_trend_conflict"), "1") is True
    assert _cast_to_field(_field("use_trend_conflict"), "0") is False
    assert _cast_to_field(_field("use_running_acc"), "true") is True


def test_cast_int_and_float() -> None:
    assert _cast_to_field(_field("running_window"), "3.0") == 3
    assert _cast_to_field(_field("tau_run"), "0.5931") == pytest.approx(0.5931)


def test_cast_invalid_raises_drift() -> None:
    with pytest.raises(WrapperConfigDriftError):
        _cast_to_field(_field("tau_run"), "not-a-number")


# ----------------------- wrapper fired_trend capture ----------------------
def test_wrapper_captures_fired_trend_defaults() -> None:
    w = CompassTransitionWrapper(dispersion_with_acc_threshold=0.60)
    assert w.last_fired_trend is False
    assert w.last_fired_three_way is False


def test_wrapper_captures_fired_trend_after_apply() -> None:
    """With trend-conflict ON and a 5d move opposite net_score, fired_trend is captured."""
    cfg = WrapperConfig(
        use_running_acc=False,
        use_cluster_dispersion=False,
        use_three_way_disagreement=False,
        use_trend_conflict=True,
        tau_trend=0.02,
        trend_window=5,
    )
    w = CompassTransitionWrapper(config=cfg, dispersion_with_acc_threshold=0.60)
    dates = pd.date_range("2026-05-01", periods=8, freq="D")
    # net_score positive (OPEN bias) but price fell hard over the window → trend conflict.
    decisions = pd.DataFrame(
        {
            "date": dates,
            "decision": ["OPEN"] * 8,
            "net_score": [0.8] * 8,
            "macro_direction": [0] * 8,
            "prior_open": [0.5] * 8,
            "prior_hedge": [0.3] * 8,
            "prior_monitor": [0.2] * 8,
            "committed": [True] * 8,
            "correct": [True] * 8,
            "forward_return": [0.0] * 8,
        }
    )
    votes = pd.DataFrame(columns=pd.Index(["date", "specialist_name", "pred"]))
    returns = pd.Series([-0.02] * 8, index=dates)  # sustained decline vs the OPEN/net>0
    _, _ = w.apply(decisions, votes, returns)
    assert isinstance(w.last_fired_trend, bool)
    assert w.last_fired_trend is True
