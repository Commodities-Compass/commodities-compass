"""Regression test for P2b cross-Phase date alignment in compass_brief_ensemble.

See ``scripts/ensemble_explainer/tests/test_date_semantics.py`` for the full
bug history. This module mirrors the contract for the ensemble brief reader :
``data_date`` for Phase A tables (orchestrator, specialists, ensemble row of
pl_indicator_daily, contract data) and ``target_date`` for Phase B tables
(press, meteo).
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

from scripts.compass_brief_ensemble import db_reader


def _make_session_mock() -> tuple[MagicMock, list[dict]]:
    captured: list[dict] = []

    def _execute(stmt, params=None):
        captured.append(params or {})
        result = MagicMock()
        sql_text = str(stmt)

        if "pl_algorithm_version" in sql_text and "WHERE name" in sql_text:
            result.fetchone.return_value = ("algo-uuid",)
            return result
        if (
            "pl_indicator_daily" in sql_text
            and "decision" in sql_text
            and "LIMIT 1" in sql_text
        ):
            row = MagicMock()
            row._mapping = {
                "decision": "OPEN",
                "confidence": 4,
                "direction": "HAUSSIERE",
                "conclusion": "x" * 100,
                "eco": "y" * 50,
            }
            result.fetchone.return_value = row
            return result
        if "pl_orchestrator_decision" in sql_text:
            row = MagicMock()
            row._mapping = {
                "soft_gate_decision": "OPEN",
                "wrapper_active": False,
                "net_score": 0.1,
                "n_committed_specialists": 12,
                "fired_running_acc": False,
                "fired_trend": False,
                "fired_dispersion": False,
                "fired_three_way": False,
                "running_acc_5d": 0.95,
                "realized_return_5d": 0.01,
                "anomaly_score_z": 0.5,
                "macro_direction": 1,
                "macro_surprise": 0.2,
                "macro_half_life_days": 5,
                "prior_open": 0.5,
                "prior_hedge": 0.3,
                "prior_monitor": 0.2,
                "winter_vote_signed": 3,
                "spring_vote_signed": 2,
            }
            result.fetchone.return_value = row
            return result
        if "pl_specialist_prediction" in sql_text:
            result.all.return_value = [("winter_tb_6", "OPEN", 6)]
            return result
        if "pl_indicator_daily" in sql_text and "LIMIT :limit" in sql_text:
            # persistence days lookup
            result.all.return_value = [(date(2026, 5, 26), "OPEN")]
            return result
        if "pl_fundamental_article" in sql_text:
            result.fetchone.return_value = ("press s", "impact", "neutral")
            return result
        if "pl_weather_observation" in sql_text:
            result.fetchone.return_value = ("meteo s", "impact m")
            return result
        if "pl_contract_data_daily" in sql_text:
            result.fetchone.return_value = (
                date(2026, 5, 26),
                2057,
                2162,
                2010,
                12000,
                36000,
                0.55,
                100,
                50,
                -3000,
            )
            return result
        result.fetchone.return_value = None
        result.all.return_value = []
        return result

    session = MagicMock()
    session.execute.side_effect = _execute
    return session, captured


@pytest.mark.unit
def test_read_brief_data_uses_data_date_for_phase_a_tables() -> None:
    session, captured = _make_session_mock()
    target_date = date(2026, 5, 27)
    data_date = date(2026, 5, 26)

    db_reader.read_brief_data(
        session, target_date, contract_id="c-uuid", data_date=data_date
    )

    # Phase A: ensemble row + orchestrator + specialists + persistence +
    # technicals — all bind "contract" (and "algo" for some). All MUST use
    # data_date.
    phase_a_calls = [
        p for p in captured if ("date" in p or "limit" in p) and "contract" in p
    ]
    assert phase_a_calls, "Fixture drifted — no Phase A queries observed."
    for params in phase_a_calls:
        bound_date = params.get("date")
        assert bound_date == data_date, (
            f"Phase A table queried with date={bound_date} but expected "
            f"data_date={data_date} (target_date was {target_date}). "
            "Regression of the P2b cross-Phase date alignment bug."
        )


@pytest.mark.unit
def test_read_brief_data_uses_target_date_for_phase_b_tables() -> None:
    session, captured = _make_session_mock()
    target_date = date(2026, 5, 27)
    data_date = date(2026, 5, 26)

    db_reader.read_brief_data(
        session, target_date, contract_id="c-uuid", data_date=data_date
    )

    phase_b_calls = [
        p
        for p in captured
        if "date" in p and "contract" not in p and "algo" not in p and "limit" not in p
    ]
    assert phase_b_calls, "Fixture drifted — no Phase B queries observed."
    for params in phase_b_calls:
        assert params["date"] == target_date, (
            f"Phase B table queried with date={params['date']} but expected "
            f"target_date={target_date}."
        )
