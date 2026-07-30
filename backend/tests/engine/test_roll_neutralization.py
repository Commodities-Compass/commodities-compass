"""Tests for contract-roll contamination neutralization (option (b)).

At a front-month roll the continuous series splices the raw close of contract A
(day T-1) to contract B (day T). That step equals the calendar spread — a phantom
return that the positional/recursive indicators (RSI Δ, ATR TR, daily_return)
cannot distinguish from a real move. We (1) mark roll-boundary rows and
(2) neutralize the cross-boundary day-over-day change so the phantom jump never
enters RSI/ATR/daily_return (nor, downstream, their 252d z-scores).

Level-based indicators (MACD/Bollinger/Stochastic) are NOT neutralized here —
that is the accepted (b)-vs-(c) residual (full removal = back-adjusted chain).
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd
import pytest

from app.engine.indicators.atr import TrueRange
from app.engine.indicators.ratios import DailyReturn
from app.engine.indicators.rsi import WilderRSI
from app.engine.pipeline import IndicatorPipeline
from app.engine.runner import mark_roll_boundaries


def _make_ohlcv(
    closes: Sequence[float],
    highs: Sequence[float] | None = None,
    lows: Sequence[float] | None = None,
    codes: Sequence[str] | None = None,
) -> pd.DataFrame:
    n = len(closes)
    if highs is None:
        highs = [c + 5 for c in closes]
    if lows is None:
        lows = [c - 5 for c in closes]
    df = pd.DataFrame(
        {
            "date": pd.date_range("2025-01-01", periods=n, freq="B"),
            "close": closes,
            "high": highs,
            "low": lows,
            "volume": [1000] * n,
            "oi": [5000] * n,
        }
    )
    if codes is not None:
        df["contract_code"] = list(codes)
    return df


# --- mark_roll_boundaries (the loader helper, pure) ---


class TestMarkRollBoundaries:
    def test_marks_contract_change(self) -> None:
        df = _make_ohlcv([100, 101, 200, 202, 300], codes=["A", "A", "B", "B", "C"])
        out = mark_roll_boundaries(df)
        assert list(out["is_roll_boundary"]) == [False, False, True, False, True]

    def test_first_row_never_boundary(self) -> None:
        df = _make_ohlcv([100, 101], codes=["A", "A"])
        out = mark_roll_boundaries(df)
        assert (
            out["is_roll_boundary"].iloc[0] is np.False_
            or not out["is_roll_boundary"].iloc[0]
        )

    def test_single_contract_no_boundaries(self) -> None:
        df = _make_ohlcv([100, 101, 102], codes=["A", "A", "A"])
        out = mark_roll_boundaries(df)
        assert not bool(out["is_roll_boundary"].any())

    def test_does_not_mutate_input(self) -> None:
        df = _make_ohlcv([100, 200], codes=["A", "B"])
        _ = mark_roll_boundaries(df)
        assert "is_roll_boundary" not in df.columns

    def test_empty_df(self) -> None:
        df = _make_ohlcv([], codes=[])
        out = mark_roll_boundaries(df)
        assert "is_roll_boundary" in out.columns
        assert len(out) == 0


# --- DailyReturn neutralization ---


class TestDailyReturnNeutralization:
    def test_return_neutralized_at_roll(self) -> None:
        # jump 101 -> 200 at the roll (idx 2) must NOT be recorded as a +98% return
        df = _make_ohlcv([100.0, 101.0, 200.0, 202.0])
        df["is_roll_boundary"] = [False, False, True, False]
        out = DailyReturn().compute(df)
        assert out["daily_return"].iloc[2] == pytest.approx(0.0)  # neutralized
        assert out["daily_return"].iloc[1] == pytest.approx(101 / 100 - 1)
        assert out["daily_return"].iloc[3] == pytest.approx(202 / 200 - 1)

    def test_no_flag_column_is_backward_compatible(self) -> None:
        df = _make_ohlcv([100.0, 101.0, 200.0])  # no is_roll_boundary column
        out = DailyReturn().compute(df)
        assert out["daily_return"].iloc[2] == pytest.approx(200 / 101 - 1)


# --- TrueRange neutralization ---


class TestTrueRangeNeutralization:
    def test_tr_intraday_only_at_roll(self) -> None:
        # roll at idx 1: TR must be high-low (10), not the cross-contract
        # max(10, |305-100|, |295-100|) = 205
        df = _make_ohlcv([100.0, 300.0], highs=[105.0, 305.0], lows=[95.0, 295.0])
        df["is_roll_boundary"] = [False, True]
        out = TrueRange().compute(df)
        assert out["atr"].iloc[1] == pytest.approx(10.0)

    def test_tr_normal_without_flag(self) -> None:
        df = _make_ohlcv([100.0, 300.0], highs=[105.0, 305.0], lows=[95.0, 295.0])
        out = TrueRange().compute(df)
        assert out["atr"].iloc[1] == pytest.approx(205.0)  # max(10, 205, 195)


# --- WilderRSI neutralization ---


class TestWilderRSINeutralization:
    def _series_with_roll_jump(self) -> pd.DataFrame:
        # gentle mid-range series (RSI ~ mid, not degenerate), then a +100 jump
        closes = [
            100,
            101,
            100,
            102,
            101,
            103,
            102,
            104,
            103,
            105,
            104,
            106,
            105,
            107,
            106,
            206,
        ]
        return _make_ohlcv([float(c) for c in closes])

    def test_roll_jump_removed_from_rsi(self) -> None:
        df = self._series_with_roll_jump()
        flagged = df.copy()
        flag = [False] * len(df)
        flag[15] = True  # the +100 jump is a roll splice
        flagged["is_roll_boundary"] = flag

        rsi_unflagged = WilderRSI().compute(df)["rsi_14d"].iloc[15]
        rsi_flagged = WilderRSI().compute(flagged)["rsi_14d"].iloc[15]

        # the phantom +100 gain is removed → flagged RSI is strictly lower
        assert rsi_flagged < rsi_unflagged
        # and the gain at the roll is not booked (loss/gain smoothing not spiked up)
        assert (
            WilderRSI().compute(flagged)["gain_14d"].iloc[15]
            < WilderRSI().compute(df)["gain_14d"].iloc[15]
        )


# --- End-to-end: column flows through the pipeline, z-score not spiked ---


class TestPipelineRollFlow:
    def _long_series_with_roll(self, roll_idx: int, n: int = 60) -> pd.DataFrame:
        rng = [100.0 + (i % 5) for i in range(n)]  # bounded oscillation
        rng[roll_idx] += 120.0  # phantom roll jump
        for j in range(roll_idx + 1, n):
            rng[j] += 120.0  # new contract trades ~120 higher (level shift)
        df = _make_ohlcv(rng)
        flag = [False] * n
        flag[roll_idx] = True
        df["is_roll_boundary"] = flag
        return df

    def test_flag_survives_to_signals(self) -> None:
        df = self._long_series_with_roll(roll_idx=30)
        result = IndicatorPipeline().run(df)
        assert "is_roll_boundary" in result.signals.columns
        assert bool(result.signals["is_roll_boundary"].iloc[30]) is True

    def test_atr_not_inflated_at_roll(self) -> None:
        df = self._long_series_with_roll(roll_idx=30)
        result = IndicatorPipeline().run(df)
        # the true-range at the roll row is the intraday range only (~10),
        # not the ~120 cross-contract jump
        assert float(result.derived["atr"].iloc[30]) < 30.0


# --- Persistence: db_writer emits the boolean flag (DB-free, mock session) ---


class TestWriterPersistsRollFlag:
    def test_is_roll_boundary_written_as_bool(self) -> None:
        import uuid
        from unittest.mock import MagicMock

        from app.engine.db_writer import write_derived_indicators

        df = pd.DataFrame(
            {
                "date": pd.to_datetime(["2025-01-02", "2025-01-03"]),
                "is_roll_boundary": [False, True],
            }
        )
        session = MagicMock()
        written = write_derived_indicators(session, df, uuid.uuid4())

        assert written == 2
        calls = session.execute.call_args_list
        assert "is_roll_boundary" in str(calls[0].args[0])  # column in the SQL
        assert calls[0].args[1]["is_roll_boundary"] is False
        assert calls[1].args[1]["is_roll_boundary"] is True
