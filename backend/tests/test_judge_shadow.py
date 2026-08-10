"""Tests for the judge shadow overlay module (Campaign 6 Layer-3, INERT).

Covers the load-bearing guarantees:
  1. brief_builder maps DB rows to a valid ``Brief`` (press sections split,
     weather impact score parsed, technicals surfaced).
  2. regime_reader adapts a ``pl_regime_shadow`` row to the RegimeDecisionLike
     duck-typed contract judge expects.
  3. The writer touches ONLY ``pl_judge_shadow`` — never a shared decision or
     indicator table (the isolation judge ships INERT to preserve).
  4. The writer never overwrites ``realized_return`` / ``production_score`` on
     a decision re-run (owned by the horizon-close scoring pass).
"""

from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import MagicMock

import pytest
from judge.schema import (  # type: ignore
    Brief,
    Decision,
    Direction,
    Drift,
    JudgeOutcome,
    JudgeVerdict,
    Stance,
)

from scripts.judge_shadow.brief_builder import (
    BriefDataMissingError,
    build_brief_from_db,
)
from scripts.judge_shadow.db_writer import write_judge_shadow
from scripts.judge_shadow.regime_reader import (
    RegimeShadowMissingError,
    RegimeShadowRow,
    load_regime_for,
)


# ---------- brief_builder --------------------------------------------------


_PRESS_TEXT = """SUPPLY
Ivory Coast port arrivals slowed sharply this week.
Ghana COCOBOD held the farmgate price steady.

FUNDAMENTALS
Barry Callebaut reported first volume growth in two years.
Nestle organic growth strong in H1 2026.

MARKET
On July 31, September (CAU26) closed at 4,011 GBP/t.
StoneX flags a near-balanced 2026/27 market.

MARKET SENTIMENT
Short-term cautious to mildly bullish on supply anxiety.
"""

_WEATHER_TEXT = "Impact: 2/10; Justification: Only San-Pedro slightly degraded, all other zones normal."


def _mock_session_for_brief(
    *,
    press: str | None = _PRESS_TEXT,
    impact: str = "Overall supportive bias into early August.",
    weather: str | None = _WEATHER_TEXT,
    tech: tuple | None = (4011.0, 10311.0, 53.05),
    algo: tuple | None = ("HEDGE", 2.0, "BAISSIERE"),
) -> MagicMock:
    """Simulate the 4 SELECTs brief_builder issues in order."""

    def _fetchone():
        pass

    press_row = None if press is None else MagicMock(summary=press, impact=impact)
    weather_row = None if weather is None else MagicMock(body=weather)
    tech_row = (
        None if tech is None else MagicMock(close=tech[0], volume=tech[1], rsi=tech[2])
    )
    algo_row = (
        None
        if algo is None
        else MagicMock(decision=algo[0], confidence=algo[1], direction=algo[2])
    )

    calls = iter([press_row, weather_row, tech_row, algo_row])
    session = MagicMock()
    session.execute.return_value.fetchone.side_effect = lambda: next(calls)
    return session


class TestBriefBuilder:
    def test_builds_brief_from_db_rows(self) -> None:
        session = _mock_session_for_brief()
        brief = build_brief_from_db(
            session,
            data_date=date(2026, 7, 31),
            target_date=date(2026, 8, 3),
            include_algo_base=True,
        )
        assert isinstance(brief, Brief)
        assert brief.session_date == "2026-08-03"
        assert brief.last_close_date == "2026-07-31"
        # Press sections extracted from labeled body.
        assert "Ivory Coast" in brief.press.supply
        assert "Barry Callebaut" in brief.press.fundamentals
        assert "CAU26" in brief.press.market
        assert "cautious" in brief.press.sentiment
        # impact_synthesis (dedicated column) takes precedence over parser fallback.
        assert brief.press.impact_summary.startswith("Overall supportive")
        # Weather impact score parsed from the "Impact: X/10; ..." line.
        assert brief.weather.impact_10 == pytest.approx(2.0)
        # Technicals surface as floats.
        assert brief.close == pytest.approx(4011.0)
        assert brief.volume == pytest.approx(10311.0)
        assert brief.rsi == pytest.approx(53.05)
        # Prior brief keeps its own base_decision from the algo call.
        assert brief.base_decision == Decision.HEDGE
        assert brief.base_confidence == pytest.approx(2.0)

    def test_include_algo_base_false_uses_placeholders(self) -> None:
        session = _mock_session_for_brief()
        brief = build_brief_from_db(
            session,
            data_date=date(2026, 7, 31),
            target_date=date(2026, 8, 3),
            include_algo_base=False,
        )
        # Placeholder — overridden by base_override in run_shadow / decide()
        assert brief.base_decision == Decision.MONITOR
        assert brief.base_confidence == 0.0
        assert brief.base_direction_label == ""

    def test_missing_press_raises(self) -> None:
        session = _mock_session_for_brief(press=None)
        with pytest.raises(BriefDataMissingError, match="press article"):
            build_brief_from_db(
                session,
                data_date=date(2026, 7, 31),
                target_date=date(2026, 8, 3),
            )

    def test_missing_weather_raises(self) -> None:
        session = _mock_session_for_brief(weather=None)
        with pytest.raises(BriefDataMissingError, match="weather"):
            build_brief_from_db(
                session,
                data_date=date(2026, 7, 31),
                target_date=date(2026, 8, 3),
            )


# ---------- regime_reader --------------------------------------------------


class TestRegimeReader:
    def test_returns_row_when_present(self) -> None:
        session = MagicMock()
        session.execute.return_value.fetchone.return_value = MagicMock(
            decision="HEDGE",
            prob_up=0.2133,
            regime="highvol",
            specialist="highvol",
            date=date(2026, 7, 31),
        )
        row = load_regime_for(session, date(2026, 7, 31), allow_stale=True)
        assert isinstance(row, RegimeShadowRow)
        assert row.decision == "HEDGE"
        assert row.prob_up == pytest.approx(0.2133)
        assert row.regime == "highvol"
        assert row.specialist == "highvol"
        assert row.source_date == date(2026, 7, 31)

    def test_missing_row_raises(self) -> None:
        session = MagicMock()
        session.execute.return_value.fetchone.return_value = None
        with pytest.raises(RegimeShadowMissingError):
            load_regime_for(session, date(2026, 8, 3))

    def test_allow_stale_returns_prior_date(self) -> None:
        session = MagicMock()
        session.execute.return_value.fetchone.return_value = MagicMock(
            decision="OPEN",
            prob_up=0.55,
            regime="bull",
            specialist="bull",
            date=date(2026, 7, 31),  # older than the asked date
        )
        row = load_regime_for(session, date(2026, 8, 3), allow_stale=True)
        assert row.source_date == date(2026, 7, 31)


# ---------- db_writer isolation --------------------------------------------


def _sample_outcome() -> JudgeOutcome:
    verdict = JudgeVerdict(
        suggested_direction=Direction.UP,
        confidence=3,
        stance=Stance.CONTRADICT,
        is_anomaly=True,
        evidence=("prices soaring", "port arrivals slowed"),
        drift_summary="press turned supply-supportive",
        disconfirming_case="if arrivals rebound",
        key_risk="Ivorian weather flip",
        prompt_version="judge_prompt_v1",
        model_id="o4-mini",
    )
    drift = Drift(
        n_days=3,
        weather_impact_series=(2.0, 3.0, 2.0),
        weather_delta=0.0,
        notes=("no strong numeric drift",),
    )
    log = {
        "session_date": "2026-08-03",
        "base_source": "regime/1.0.0",
        "base_decision": "HEDGE",
        "base_confidence": 2.87,
        "final_decision": "MONITOR",
        "changed": True,
        "judge_direction": "UP",
        "judge_stance": "CONTRADICT",
        "judge_confidence": 3,
        "is_anomaly": True,
        "weather_series": [2.0, 3.0, 2.0],
        "prompt_version": "judge_prompt_v1",
        "model_id": "o4-mini",
        "rationale": "policy: contradict conf 3 -> MONITOR",
    }
    return JudgeOutcome(
        session_date="2026-08-03",
        base_decision=Decision.HEDGE,
        final_decision=Decision.MONITOR,
        changed=True,
        verdict=verdict,
        drift=drift,
        rationale="policy: contradict conf 3 -> MONITOR",
        log_fields=log,
    )


class TestWriterIsolation:
    """The judge writer must never touch a shared decision/indicator table."""

    _FORBIDDEN = (
        "pl_indicator_daily",
        "pl_orchestrator_decision",
        "pl_derived_indicators",
        "pl_specialist_prediction",
        "pl_regime_shadow",  # judge READS regime, must not WRITE it
    )

    def test_writes_only_pl_judge_shadow(self) -> None:
        session = MagicMock()
        regime_row = RegimeShadowRow(
            decision="HEDGE",
            prob_up=0.2133,
            regime="highvol",
            specialist="highvol",
            source_date=date(2026, 7, 31),
        )
        written = write_judge_shadow(
            session,
            _sample_outcome(),
            session_date=date(2026, 7, 31),
            contract_id=uuid.uuid4(),
            algorithm_version_id=uuid.uuid4(),
            regime_row=regime_row,
        )
        assert written == 1
        sql = " ".join(str(call.args[0]) for call in session.execute.call_args_list)
        assert "pl_judge_shadow" in sql
        for forbidden in self._FORBIDDEN:
            assert forbidden not in sql, f"writer touched {forbidden}"

    def test_realized_columns_not_overwritten_on_rerun(self) -> None:
        session = MagicMock()
        regime_row = RegimeShadowRow(
            decision="HEDGE",
            prob_up=0.2133,
            regime="highvol",
            specialist="highvol",
            source_date=date(2026, 7, 31),
        )
        write_judge_shadow(
            session,
            _sample_outcome(),
            session_date=date(2026, 7, 31),
            contract_id=uuid.uuid4(),
            algorithm_version_id=uuid.uuid4(),
            regime_row=regime_row,
        )
        sql = " ".join(str(call.args[0]) for call in session.execute.call_args_list)
        # The ON CONFLICT DO UPDATE clause must NOT list realized_return /
        # production_score — verified by scanning the SET section (comes AFTER
        # the initial INSERT column list, easiest to spot by tail-substring).
        assert "realized_return   " not in sql.split("DO UPDATE SET")[1]
        assert "production_score  " not in sql.split("DO UPDATE SET")[1]
