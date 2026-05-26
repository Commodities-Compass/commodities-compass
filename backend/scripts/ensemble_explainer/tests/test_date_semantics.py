"""Regression tests for P2b cross-Phase date alignment.

Bug history (2026-05-26):
    The P2b refactor (commit 1ec53fb) shifted Phase B agents' default
    ``target_date`` from today() to next_session_date(today()). The pre-flight
    has_contract_data_for_date check was updated to use previous_session, but
    the DB read/write queries inside the engine + readers were NOT plumbed
    through. Production tonight, cc-ensemble-explainer attempted to read
    pl_orchestrator_decision WHERE date = target_date (2026-05-27) and got
    zero rows because cc-ensemble-compute had written its row at the actual
    session date (2026-05-26). Same for daily-analysis + compass-brief-ensemble.

These tests pin the contract :
    * ``data_date`` is used for queries against tables written by Phase A
      jobs (pl_orchestrator_decision, pl_specialist_prediction, the ensemble
      row of pl_indicator_daily, pl_contract_data_daily).
    * ``target_date`` is used for queries against tables written by Phase B
      agents keyed to the upcoming session (pl_fundamental_article,
      pl_weather_observation).

If a future change reintroduces a `WHERE date = :target_date` against a
Phase A table the relevant assertion below will fail loudly.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

from scripts.ensemble_explainer import db_reader


def _make_session_mock(
    *,
    algo_id: str = "algo-uuid",
    orchestrator_row: tuple | None = None,
    specialist_rows: list | None = None,
    press_row: tuple | None = None,
    meteo_row: tuple | None = None,
    technicals_row: tuple | None = None,
) -> tuple[MagicMock, list[dict]]:
    """Return (session_mock, captured_params).

    ``captured_params`` is the ordered list of bind-param dicts that
    ``session.execute(text(...), params)`` was called with — tests assert
    against it to verify which date was bound to which query.
    """
    captured: list[dict] = []

    def _execute(stmt, params=None):
        captured.append(params or {})
        result = MagicMock()
        sql_text = str(stmt)

        if "pl_algorithm_version" in sql_text and "WHERE name" in sql_text:
            result.fetchone.return_value = (algo_id,)
            return result
        if "pl_orchestrator_decision" in sql_text:
            row = MagicMock()
            row._mapping = {
                "decision_wrapped": "OPEN",
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
            result.fetchone.return_value = (
                orchestrator_row if orchestrator_row is not None else row
            )
            return result
        if "pl_specialist_prediction" in sql_text:
            result.all.return_value = specialist_rows or [
                ("winter_tb_6", "OPEN", 6),
                ("winter_tb_12", "OPEN", 12),
            ]
            return result
        if "pl_fundamental_article" in sql_text:
            result.fetchone.return_value = press_row or ("press s", "impact", "neutral")
            return result
        if "pl_weather_observation" in sql_text:
            result.fetchone.return_value = meteo_row or ("meteo s", "impact m")
            return result
        if "pl_contract_data_daily" in sql_text:
            result.fetchone.return_value = technicals_row or (
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
def test_read_explainer_inputs_uses_data_date_for_phase_a_tables() -> None:
    """Phase A tables (orchestrator + specialists + technicals) must be
    queried with ``data_date``, not ``target_date``."""
    session, captured = _make_session_mock()
    target_date = date(2026, 5, 27)  # upcoming session (Wed)
    data_date = date(2026, 5, 26)  # last completed session (Tue)

    db_reader.read_explainer_inputs(
        session, target_date, contract_id="c-uuid", data_date=data_date
    )

    # Phase A queries: orchestrator + specialists (have algo + contract +
    # date) AND technicals (have contract + date, no algo). All MUST bind
    # ``date`` = data_date.
    phase_a_calls = [p for p in captured if "date" in p and "contract" in p]
    assert phase_a_calls, (
        "No call observed against any Phase A table — fixture drifted."
    )
    for params in phase_a_calls:
        assert params["date"] == data_date, (
            f"Phase A table queried with date={params['date']} but expected "
            f"data_date={data_date} (target_date was {target_date}). "
            "Regression of the P2b cross-Phase date alignment bug."
        )


@pytest.mark.unit
def test_read_explainer_inputs_uses_target_date_for_phase_b_tables() -> None:
    """Phase B P2b-keyed tables (press + meteo) must be queried with
    ``target_date`` — these rows are written by press_review + meteo agents
    for the upcoming session they address."""
    session, captured = _make_session_mock()
    target_date = date(2026, 5, 27)
    data_date = date(2026, 5, 26)

    db_reader.read_explainer_inputs(
        session, target_date, contract_id="c-uuid", data_date=data_date
    )

    # The press + meteo calls both bind "date" but NO "contract" or "algo".
    phase_b_calls = [
        p for p in captured if "date" in p and "contract" not in p and "algo" not in p
    ]
    assert phase_b_calls, (
        "No call observed against pl_fundamental_article or "
        "pl_weather_observation — test fixture drifted from production code."
    )
    for params in phase_b_calls:
        assert params["date"] == target_date, (
            f"Phase B table queried with date={params['date']} but expected "
            f"target_date={target_date} (data_date was {data_date}). The P2b "
            "press/meteo rows are keyed to the upcoming session."
        )


@pytest.mark.unit
def test_read_explainer_inputs_default_data_date_is_target_date() -> None:
    """Backward compatibility: when ``data_date`` is not provided, all queries
    fall back to ``target_date`` (matches pre-P2b historical-backfill use)."""
    session, captured = _make_session_mock()
    target_date = date(2026, 5, 27)

    db_reader.read_explainer_inputs(session, target_date, contract_id="c-uuid")

    dated_calls = [p for p in captured if "date" in p]
    assert dated_calls
    for params in dated_calls:
        assert params["date"] == target_date
