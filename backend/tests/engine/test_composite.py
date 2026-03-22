"""Tests for the composite scoring engine (NEW CHAMPION power formula)."""

from __future__ import annotations


import pytest

from app.engine.composite import (
    _power_term,
    compute_decision,
    compute_linear_indicator,
    compute_momentum,
    compute_score,
)
from app.engine.types import NEW_CHAMPION, AlgorithmConfig


class TestPowerTerm:
    def test_positive_input(self) -> None:
        # 2.0 * sign(3.0) * |3.0|^1.5 = 2.0 * 1 * 5.196 = 10.392
        result = _power_term(2.0, 1.5, 3.0)
        assert result == pytest.approx(2.0 * 3.0**1.5)

    def test_negative_input(self) -> None:
        # 2.0 * sign(-3.0) * |-3.0|^1.5 = 2.0 * -1 * 5.196 = -10.392
        result = _power_term(2.0, 1.5, -3.0)
        assert result == pytest.approx(-2.0 * 3.0**1.5)

    def test_zero_input(self) -> None:
        assert _power_term(2.0, 1.5, 0.0) == 0.0

    def test_nan_input(self) -> None:
        assert _power_term(2.0, 1.5, float("nan")) == 0.0

    def test_zero_coefficient(self) -> None:
        """Zero weight should produce zero contribution."""
        assert _power_term(0.0, 1.5, 5.0) == 0.0

    def test_exponent_one(self) -> None:
        """With exponent=1, result is just coefficient × value."""
        assert _power_term(3.0, 1.0, 2.0) == pytest.approx(6.0)
        assert _power_term(3.0, 1.0, -2.0) == pytest.approx(-6.0)

    def test_fractional_exponent(self) -> None:
        """Fractional exponents should work (no complex numbers)."""
        result = _power_term(1.0, 0.5, 4.0)
        assert result == pytest.approx(2.0)  # 1.0 * 1 * 4^0.5 = 2.0


class TestComputeScore:
    def test_all_zeros(self) -> None:
        """All zero inputs should return just the constant k."""
        score = compute_score(0, 0, 0, 0, 0, 0, 0, 0, NEW_CHAMPION)
        assert score == pytest.approx(NEW_CHAMPION.k)

    def test_known_values(self) -> None:
        """Spot-check with known inputs."""
        score = compute_score(
            rsi_norm=1.0,
            macd_norm=0.5,
            stoch_norm=-1.0,
            atr_norm=0.0,
            cp_norm=0.0,
            voi_norm=0.0,
            momentum=0.2,
            macroeco=0.05,
            config=NEW_CHAMPION,
        )
        # Manual calculation:
        expected = NEW_CHAMPION.k
        expected += NEW_CHAMPION.a * 1.0 * abs(1.0) ** NEW_CHAMPION.b  # RSI
        expected += NEW_CHAMPION.c * 1.0 * abs(0.5) ** NEW_CHAMPION.d  # MACD
        expected += NEW_CHAMPION.e * (-1.0) * abs(-1.0) ** NEW_CHAMPION.f  # STOCH
        # ATR, CP, VOI = 0 → no contribution
        expected += NEW_CHAMPION.n * 1.0 * abs(0.2) ** NEW_CHAMPION.o  # MOMENTUM
        expected += NEW_CHAMPION.p * 1.0 * abs(0.05) ** NEW_CHAMPION.q  # MACROECO
        assert score == pytest.approx(expected)

    def test_symmetry_sign_flip(self) -> None:
        """Flipping all input signs should change the score."""
        score_pos = compute_score(1, 1, 1, 1, 1, 1, 0.2, 0.05, NEW_CHAMPION)
        score_neg = compute_score(-1, -1, -1, -1, -1, -1, -0.2, -0.05, NEW_CHAMPION)
        assert score_pos != pytest.approx(score_neg)


class TestComputeDecision:
    def test_open(self) -> None:
        assert compute_decision(2.0, NEW_CHAMPION) == "OPEN"
        assert compute_decision(1.5, NEW_CHAMPION) == "OPEN"  # exactly at threshold

    def test_hedge(self) -> None:
        assert compute_decision(-2.0, NEW_CHAMPION) == "HEDGE"
        assert compute_decision(-1.5, NEW_CHAMPION) == "HEDGE"  # exactly at threshold

    def test_monitor(self) -> None:
        assert compute_decision(0.0, NEW_CHAMPION) == "MONITOR"
        assert compute_decision(1.49, NEW_CHAMPION) == "MONITOR"
        assert compute_decision(-1.49, NEW_CHAMPION) == "MONITOR"

    def test_nan(self) -> None:
        assert compute_decision(float("nan"), NEW_CHAMPION) == "MONITOR"


class TestComputeMomentum:
    def test_increasing(self) -> None:
        assert compute_momentum(1.5, 1.0) == 0.2

    def test_decreasing(self) -> None:
        assert compute_momentum(1.0, 1.5) == -0.2

    def test_equal(self) -> None:
        assert compute_momentum(1.0, 1.0) == -0.2

    def test_nan(self) -> None:
        assert compute_momentum(float("nan"), 1.0) == 0.0


class TestLinearIndicator:
    def test_all_zeros(self) -> None:
        result = compute_linear_indicator(0, 0, 0, 0, 0, 0)
        assert result == pytest.approx(0.519)

    def test_known_coefficients(self) -> None:
        """Verify hardcoded coefficients match INDICATOR!N formula."""
        result = compute_linear_indicator(1, 1, 1, 1, 1, 1)
        expected = -0.79 + 0.49 - 1.16 - 0.11 - 0.82 - 0.52 + 0.519
        assert result == pytest.approx(expected)


class TestAlgorithmConfig:
    def test_from_db_rows(self) -> None:
        params = {
            "k": "-1.2",
            "a": "-1.3",
            "b": "1.8",
            "c": "0.5",
            "d": "0.7",
            "e": "-2.5",
            "f": "1.0",
            "g": "1.204",
            "h": "0.5",
            "i": "-0.4",
            "j": "1.751",
            "l": "4.98",
            "m": "1.2",
            "n": "-1.3",
            "o": "0.515",
            "p": "-0.5",
            "q": "1.98",
            "open_threshold": "1.5",
            "hedge_threshold": "-1.5",
        }
        config = AlgorithmConfig.from_db_rows("test_v1", params)
        assert config.k == -1.2
        assert config.open_threshold == 1.5
        assert config.version_name == "test_v1"

    def test_new_champion_frozen(self) -> None:
        """AlgorithmConfig should be immutable."""
        with pytest.raises(AttributeError):
            NEW_CHAMPION.k = 0.0  # type: ignore[misc]
