"""v0.2 fine-tune tests: PRICE-VS-THESIS + YOUR-OWN-HISTORY blocks.

Two informational additions to the prompt:
  1. Price path over the brief window (cumulative + step returns) — deterministic.
  2. Judge's own prior decisions replayed with the price move since — deterministic.

Neither changes the policy/thresholds — both are LLM-side signals. These tests
only verify the deterministic plumbing (drift computation + prompt rendering).
The behavioural effect is validated in shadow, not in unit tests.
"""

from __future__ import annotations

import pytest
from judge import config, prompt
from judge.drift import compute_drift
from judge.schema import (
    Brief,
    Decision,
    Direction,
    PressRead,
    PriorJudgeRecord,
    WeatherRead,
)


def _brief(session: str, close: float, weather_impact: float | None = 3.0) -> Brief:
    return Brief(
        session_date=session,
        last_close_date=session,
        base_decision=Decision.MONITOR,
        base_confidence=0.0,
        base_direction_label="",
        ytd=None,
        press=PressRead(supply="port arrivals lagging"),
        weather=WeatherRead(impact_10=weather_impact, summary=""),
        close=close,
        volume=None,
        rsi=None,
    )


class TestDriftPriceSeries:
    def test_price_series_computed(self) -> None:
        # 4011 -> 4402 -> 4361 : cum ~+8.72%; steps +9.75%, -0.93%
        window = [
            _brief("2026-07-31", 4011.0),
            _brief("2026-08-03", 4402.0),
            _brief("2026-08-04", 4361.0),
        ]
        drift = compute_drift(window)
        assert drift.price_series == (4011.0, 4402.0, 4361.0)
        assert drift.price_cum_move == pytest.approx((4361.0 - 4011.0) / 4011.0)
        assert len(drift.price_step_moves) == 2
        assert drift.price_step_moves[0] == pytest.approx((4402.0 - 4011.0) / 4011.0)
        assert drift.price_step_moves[1] == pytest.approx((4361.0 - 4402.0) / 4402.0)

    def test_price_move_note_threshold(self) -> None:
        # cum move ≥ 3% must surface a note
        window = [_brief("2026-08-01", 4000.0), _brief("2026-08-02", 4200.0)]
        drift = compute_drift(window)
        assert drift.price_cum_move == pytest.approx(0.05)
        assert any("price up" in n for n in drift.notes)

    def test_price_move_below_threshold_no_note(self) -> None:
        # cum move < 3% must NOT surface a note (keeps signal noise low)
        window = [_brief("2026-08-01", 4000.0), _brief("2026-08-02", 4050.0)]
        drift = compute_drift(window)
        assert drift.price_cum_move == pytest.approx(0.0125)
        assert not any("price" in n for n in drift.notes)

    def test_no_closes_no_price_signal(self) -> None:
        window = [
            Brief(
                session_date="2026-08-01",
                last_close_date="2026-08-01",
                base_decision=Decision.MONITOR,
                base_confidence=0.0,
                base_direction_label="",
                ytd=None,
                press=PressRead(),
                weather=WeatherRead(impact_10=None, summary=""),
                close=None,
                volume=None,
                rsi=None,
            )
        ]
        drift = compute_drift(window)
        assert drift.price_series == ()
        assert drift.price_cum_move is None
        assert drift.price_step_moves == ()


class TestPromptRendering:
    def _window(self) -> list[Brief]:
        return [
            _brief("2026-07-31", 4011.0),
            _brief("2026-08-03", 4402.0),
            _brief("2026-08-04", 4361.0),
        ]

    def test_prompt_version_v2(self) -> None:
        assert config.PROMPT_VERSION == "judge_prompt_v2"

    def test_price_block_in_prompt(self) -> None:
        drift = compute_drift(self._window())
        rendered = prompt.render(self._window(), drift)
        assert "PRICE ACTION over window" in rendered["user"]
        assert "cumulative" in rendered["user"]

    def test_history_block_absent_when_no_history(self) -> None:
        drift = compute_drift(self._window())
        rendered = prompt.render(self._window(), drift, history=None)
        assert "YOUR RECENT CALLS: none on record" in rendered["user"]

    def test_history_block_flags_against(self) -> None:
        # Prior OPEN call at 4402; today closes 4361 -> price -0.93% AGAINST call
        history = [
            PriorJudgeRecord(
                session_date="2026-08-03",
                final_decision=Decision.OPEN,
                suggested_direction=Direction.UP,
                confidence=4,
                close=4402.0,
            )
        ]
        drift = compute_drift(self._window())
        rendered = prompt.render(self._window(), drift, history=history)
        assert "YOUR RECENT CALLS" in rendered["user"]
        assert "AGAINST your call" in rendered["user"]

    def test_history_block_flags_with(self) -> None:
        # Prior OPEN call at 4011; today closes 4361 -> price +8.7% WITH call
        history = [
            PriorJudgeRecord(
                session_date="2026-07-31",
                final_decision=Decision.OPEN,
                suggested_direction=Direction.UP,
                confidence=4,
                close=4011.0,
            )
        ]
        drift = compute_drift(self._window())
        rendered = prompt.render(self._window(), drift, history=history)
        assert "WITH your call" in rendered["user"]

    def test_system_prompt_has_new_rules(self) -> None:
        assert "PRICE-VS-THESIS" in prompt.SYSTEM_PROMPT
        assert "YOUR OWN HISTORY" in prompt.SYSTEM_PROMPT
