"""Pure-logic tests for dashboard_service helpers (no DB, no I/O).

Covers the scoring formula and text utilities that the YTD walk and
recommendations rendering depend on. Edge cases mirror real prod
incidents (zero-base division, MONITOR with no move, large %).
"""

from __future__ import annotations

import math

import pytest

from app.services.dashboard_service import (
    _clean_numbers,
    _score_day,
    parse_recommendations_text,
)


# ---------------------------------------------------------------------------
# _score_day — CONCLUSION scoring formula
# ---------------------------------------------------------------------------


class TestScoreDayOpen:
    """OPEN scoring: rewards correct call (price up), penalises wrong call."""

    def test_open_price_up_large_move(self) -> None:
        # +2% move > 1% threshold → bonus 1.25
        assert _score_day("OPEN", 100.0, 102.0) == pytest.approx(1.25)

    def test_open_price_up_small_move(self) -> None:
        # +0.5% move ≤ 1% threshold → base 1.0
        assert _score_day("OPEN", 100.0, 100.5) == pytest.approx(1.0)

    def test_open_price_down_penalised(self) -> None:
        # -3% move → -2 × 0.03 = -0.06
        assert _score_day("OPEN", 100.0, 97.0) == pytest.approx(-0.06)

    def test_open_flat_close_treated_as_no_gain(self) -> None:
        # close_t == close_t_plus_h → falls into "not > close_t" branch → 0 penalty
        assert _score_day("OPEN", 100.0, 100.0) == pytest.approx(0.0)


class TestScoreDayHedge:
    """HEDGE scoring: mirror of OPEN, rewards correct call (price down)."""

    def test_hedge_price_down_large_move(self) -> None:
        assert _score_day("HEDGE", 100.0, 98.0) == pytest.approx(1.25)

    def test_hedge_price_down_small_move(self) -> None:
        assert _score_day("HEDGE", 100.0, 99.5) == pytest.approx(1.0)

    def test_hedge_price_up_penalised(self) -> None:
        # +5% move → -2 × 0.05 = -0.10
        assert _score_day("HEDGE", 100.0, 105.0) == pytest.approx(-0.10)


class TestScoreDayMonitor:
    """MONITOR scoring: prefers volatility, neutral on flat."""

    def test_monitor_large_move_either_direction(self) -> None:
        assert _score_day("MONITOR", 100.0, 102.0) == pytest.approx(1.0)
        assert _score_day("MONITOR", 100.0, 98.0) == pytest.approx(1.0)

    def test_monitor_small_move(self) -> None:
        # 0.5% counts as movement but below 1% → 0.75
        assert _score_day("MONITOR", 100.0, 100.5) == pytest.approx(0.75)
        assert _score_day("MONITOR", 100.0, 99.5) == pytest.approx(0.75)

    def test_monitor_flat(self) -> None:
        assert _score_day("MONITOR", 100.0, 100.0) == pytest.approx(0.0)


class TestScoreDayEdgeCases:
    """Defensive handling of pathological inputs."""

    def test_close_t_zero_returns_none(self) -> None:
        # Avoid division by zero — silently skip the day.
        assert _score_day("OPEN", 0.0, 100.0) is None

    def test_unknown_decision_returns_none(self) -> None:
        assert _score_day("UNKNOWN", 100.0, 105.0) is None
        assert _score_day("", 100.0, 105.0) is None

    def test_exact_1_percent_boundary_open_up(self) -> None:
        # abs_pct == 0.01 → NOT > 0.01 → falls back to 1.0, not 1.25
        # (strict inequality in the formula)
        score = _score_day("OPEN", 100.0, 101.0)
        assert score == pytest.approx(1.0)

    def test_no_nan_for_finite_inputs(self) -> None:
        result = _score_day("HEDGE", 100.0, 99.999)
        assert result is not None
        assert math.isfinite(result)


# ---------------------------------------------------------------------------
# _clean_numbers — clamp excess decimals
# ---------------------------------------------------------------------------


class TestCleanNumbers:
    def test_integer_value_loses_decimals(self) -> None:
        assert _clean_numbers("Price 2575.000000 EUR") == "Price 2575 EUR"

    def test_two_decimals_preserved(self) -> None:
        # ≤2 decimals not matched by the >=3 decimals regex
        assert _clean_numbers("Move 12.34%") == "Move 12.34%"

    def test_three_plus_decimals_truncated_to_two(self) -> None:
        assert _clean_numbers("RSI 58.072610") == "RSI 58.07"

    def test_trailing_zero_stripped(self) -> None:
        # 0.420800 → 0.42 (rstrip("0") then rstrip(".") removes redundant)
        assert _clean_numbers("Z 0.420800") == "Z 0.42"

    def test_multiple_values_in_one_string(self) -> None:
        text = "OHLC 2575.000000 / 2580.123456 / 2570.500000"
        assert _clean_numbers(text) == "OHLC 2575 / 2580.12 / 2570.5"

    def test_no_decimals_untouched(self) -> None:
        assert _clean_numbers("Volume 1234567") == "Volume 1234567"


# ---------------------------------------------------------------------------
# parse_recommendations_text — split + strip + clean
# ---------------------------------------------------------------------------


class TestParseRecommendations:
    def test_empty_returns_empty(self) -> None:
        assert parse_recommendations_text("") == []

    def test_single_line(self) -> None:
        assert parse_recommendations_text("Buy on dip") == ["Buy on dip"]

    def test_br_tags_become_separators(self) -> None:
        text = "Line A<br>Line B<br/>Line C"
        assert parse_recommendations_text(text) == ["Line A", "Line B", "Line C"]

    def test_html_tags_stripped(self) -> None:
        text = "<p>Buy now</p><div>Sell later</div>"
        assert parse_recommendations_text(text) == ["Buy now", "Sell later"]

    def test_bullet_dashes_and_unicode_bullets_removed(self) -> None:
        text = "- Item 1\n• Item 2\n* Item 3"
        assert parse_recommendations_text(text) == ["Item 1", "Item 2", "Item 3"]

    def test_blank_lines_skipped(self) -> None:
        text = "A\n\n\nB\n  \nC"
        assert parse_recommendations_text(text) == ["A", "B", "C"]

    def test_decimal_cleanup_applied_to_output(self) -> None:
        text = "Target 2575.000000"
        assert parse_recommendations_text(text) == ["Target 2575"]
