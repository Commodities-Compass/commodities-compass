"""Tests for the regime shadow-compute module (Campaign 6, INERT).

Covers the two load-bearing guarantees:
  1. slice_panel cuts a correct trailing window from the self-computed chain.
  2. the writer touches ONLY pl_regime_shadow — never a shared decision/indicator
     table (the isolation the algo ships INERT to preserve).
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import cast
from unittest.mock import MagicMock

import pandas as pd
import pytest

from regime.config import DERIVED_PASSTHROUGH
from regime.data_loader_protocol import RegimeDecision
from scripts.regime_shadow.db_writer import write_regime_shadow
from scripts.regime_shadow.panel_loader import RegimePanelError, slice_panel


def _features(n: int, end: str = "2026-07-27") -> pd.DataFrame:
    dates = pd.bdate_range(end=end, periods=n)
    data: dict = {"date": dates, "contract_id": [str(uuid.uuid4())] * n}
    for i, col in enumerate(DERIVED_PASSTHROUGH):
        data[col] = [float(i + 1)] * n  # non-null so the panel is valid
    return pd.DataFrame(data)


def _d(ts: object) -> date:
    """A pandas Timestamp scalar → plain date (pandas stubs widen Timestamp.date())."""
    t = pd.Timestamp(cast(str, ts))
    return date(int(t.year), int(t.month), int(t.day))


def _ts(s: str) -> pd.Timestamp:
    return cast(pd.Timestamp, pd.Timestamp(s))


class TestSlicePanel:
    def test_returns_window_and_contract(self) -> None:
        feats = _features(200)
        panel, contract_id = slice_panel(feats, date(2026, 7, 27))
        assert list(panel.columns) == ["date", *DERIVED_PASSTHROUGH]
        assert len(panel) == 150  # WINDOW_ROWS
        assert panel["date"].iloc[-1] == pd.Timestamp("2026-07-27")
        assert contract_id == feats["contract_id"].iloc[-1]

    def test_missing_end_date_raises(self) -> None:
        feats = _features(200)
        with pytest.raises(RegimePanelError, match="not in the self-computed chain"):
            slice_panel(feats, date(2030, 1, 1))

    def test_too_few_rows_raises(self) -> None:
        feats = _features(30)  # < MIN_TRAILING_ROWS (61)
        with pytest.raises(RegimePanelError, match="rows <"):
            slice_panel(feats, _d(feats["date"].iloc[-1]))

    def test_window_ends_exactly_on_target(self) -> None:
        feats = _features(200)
        # a mid-series date resolves to that date, not the chain tail
        target = _d(feats["date"].iloc[150])
        panel, _ = slice_panel(feats, target)
        assert _d(panel["date"].iloc[-1]) == target


class TestWriterIsolation:
    """The shadow writer must never touch a shared decision/indicator table."""

    _FORBIDDEN = (
        "pl_indicator_daily",
        "pl_orchestrator_decision",
        "pl_derived_indicators",
        "pl_specialist_prediction",
    )

    def test_writes_only_pl_regime_shadow(self) -> None:
        session = MagicMock()
        dec = RegimeDecision(
            date=_ts("2026-07-27"),
            decision="OPEN",
            regime="transition",
            specialist="highvol",
            prob_up=0.5172,
            states={"rsi_14d": 47.17, "atr_14d": 266.3, "trend20": 0.01},
        )
        written = write_regime_shadow(
            session,
            dec,
            session_date=date(2026, 7, 27),
            contract_id=uuid.uuid4(),
            algorithm_version_id=uuid.uuid4(),
        )
        assert written == 1
        sql = " ".join(str(call.args[0]) for call in session.execute.call_args_list)
        assert "pl_regime_shadow" in sql
        for forbidden in self._FORBIDDEN:
            assert forbidden not in sql, f"writer touched {forbidden}"

    def test_realized_columns_not_overwritten_on_decision_write(self) -> None:
        # The UPSERT must leave realized_return / production_score alone (owned by
        # the horizon-close scoring pass) so a decision rerun never wipes a label.
        session = MagicMock()
        dec = RegimeDecision(
            date=_ts("2026-07-27"),
            decision="HEDGE",
            regime="bear",
            specialist="bear",
            prob_up=0.3,
            states={},
        )
        write_regime_shadow(
            session,
            dec,
            session_date=date(2026, 7, 27),
            contract_id=uuid.uuid4(),
            algorithm_version_id=uuid.uuid4(),
        )
        sql = " ".join(str(call.args[0]) for call in session.execute.call_args_list)
        assert "realized_return" not in sql
        assert "production_score" not in sql
