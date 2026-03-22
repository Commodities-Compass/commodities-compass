"""Tests for individual technical indicators.

Each test validates against known reference values or mathematical properties.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd
import pytest

from app.engine.indicators.atr import TrueRange, WilderATR
from app.engine.indicators.bollinger import BollingerBands
from app.engine.indicators.ema import EMA12, EMA26, _compute_ema
from app.engine.indicators.macd import MACD, MACDSignal
from app.engine.indicators.pivots import PivotPoints
from app.engine.indicators.ratios import ClosePivotRatio, DailyReturn, VolumeOIRatio
from app.engine.indicators.rsi import WilderRSI
from app.engine.indicators.stochastic import StochasticK, StochasticD


def _make_ohlcv(
    closes: Sequence[float],
    highs: Sequence[float] | None = None,
    lows: Sequence[float] | None = None,
    volumes: Sequence[int] | None = None,
    ois: Sequence[int] | None = None,
) -> pd.DataFrame:
    """Helper to build a minimal OHLCV DataFrame."""
    n = len(closes)
    if highs is None:
        highs = [c + 10 for c in closes]
    if lows is None:
        lows = [c - 10 for c in closes]
    if volumes is None:
        volumes = [1000] * n
    if ois is None:
        ois = [5000] * n
    return pd.DataFrame(
        {
            "date": pd.date_range("2025-01-01", periods=n, freq="B"),
            "close": closes,
            "high": highs,
            "low": lows,
            "volume": volumes,
            "oi": ois,
        }
    )


# --- Pivot Points ---


class TestPivotPoints:
    def test_standard_pivot(self) -> None:
        df = _make_ohlcv([100.0], highs=[110.0], lows=[90.0])
        result = PivotPoints().compute(df)

        assert result["pivot"].iloc[0] == pytest.approx(100.0)  # (110+90+100)/3
        assert result["r1"].iloc[0] == pytest.approx(110.0)  # 2*100 - 90
        assert result["s1"].iloc[0] == pytest.approx(90.0)  # 2*100 - 110
        assert result["r2"].iloc[0] == pytest.approx(120.0)  # 100 + (110-90)
        assert result["s2"].iloc[0] == pytest.approx(80.0)  # 100 - (110-90)

    def test_pivot_symmetry(self) -> None:
        """R levels and S levels should be symmetric around pivot."""
        df = _make_ohlcv([2000.0], highs=[2100.0], lows=[1900.0])
        result = PivotPoints().compute(df)
        pivot = result["pivot"].iloc[0]
        assert result["r1"].iloc[0] - pivot == pytest.approx(
            pivot - result["s1"].iloc[0]
        )
        assert result["r2"].iloc[0] - pivot == pytest.approx(
            pivot - result["s2"].iloc[0]
        )
        assert result["r3"].iloc[0] - pivot == pytest.approx(
            pivot - result["s3"].iloc[0]
        )

    def test_does_not_mutate_input(self) -> None:
        df = _make_ohlcv([100.0])
        original_cols = set(df.columns)
        PivotPoints().compute(df)
        assert set(df.columns) == original_cols


# --- EMA ---


class TestEMA:
    def test_ema_seed_is_sma(self) -> None:
        """First valid EMA value should equal SMA of first N closes."""
        closes = list(range(100, 113))  # 13 values, enough for EMA12
        result = _compute_ema(pd.Series(closes, dtype=float), 12)
        expected_sma = sum(closes[:12]) / 12
        assert result.iloc[11] == pytest.approx(expected_sma)

    def test_ema_nan_during_warmup(self) -> None:
        closes = list(range(100, 110))  # 10 values, not enough for EMA12
        result = _compute_ema(pd.Series(closes, dtype=float), 12)
        assert all(np.isnan(result))

    def test_ema12_alpha(self) -> None:
        """EMA12 should use alpha = 2/13."""
        closes = list(range(100, 115))  # 15 values
        result = _compute_ema(pd.Series(closes, dtype=float), 12)
        alpha = 2.0 / 13
        # Check recursive step at index 12
        expected = closes[12] * alpha + result.iloc[11] * (1 - alpha)
        assert result.iloc[12] == pytest.approx(expected)

    def test_ema_class_outputs(self) -> None:
        df = _make_ohlcv(list(range(100, 130)))
        result = EMA12().compute(df)
        assert "ema12" in result.columns
        assert np.isnan(result["ema12"].iloc[0])
        assert not np.isnan(result["ema12"].iloc[11])

        result = EMA26().compute(df)
        assert "ema26" in result.columns
        assert not np.isnan(result["ema26"].iloc[25])


# --- MACD ---


class TestMACD:
    def test_macd_is_ema12_minus_ema26(self) -> None:
        df = _make_ohlcv(list(range(100, 140)))
        df = EMA12().compute(df)
        df = EMA26().compute(df)
        result = MACD().compute(df)
        idx = 30  # well past warmup
        expected = result["ema12"].iloc[idx] - result["ema26"].iloc[idx]
        assert result["macd"].iloc[idx] == pytest.approx(expected)

    def test_macd_signal_is_ema9_of_macd(self) -> None:
        df = _make_ohlcv(list(range(100, 150)))
        df = EMA12().compute(df)
        df = EMA26().compute(df)
        df = MACD().compute(df)
        result = MACDSignal().compute(df)
        assert "macd_signal" in result.columns
        # Signal should exist by row 34 (26 warmup + 9 - 1)
        assert not np.isnan(result["macd_signal"].iloc[34])


# --- RSI ---


class TestWilderRSI:
    def test_rsi_range_0_100(self) -> None:
        """RSI must always be between 0 and 100."""
        np.random.seed(42)
        closes = (np.cumsum(np.random.randn(100)) + 2000).tolist()
        df = _make_ohlcv(closes)
        result = WilderRSI().compute(df)
        valid = result["rsi_14d"].dropna()
        assert all(valid >= 0)
        assert all(valid <= 100)

    def test_rsi_all_gains(self) -> None:
        """Monotonically increasing prices → RSI should approach 100."""
        closes = list(range(100, 140))
        df = _make_ohlcv(closes)
        result = WilderRSI().compute(df)
        last_rsi = result["rsi_14d"].iloc[-1]
        assert last_rsi > 90

    def test_rsi_all_losses(self) -> None:
        """Monotonically decreasing prices → RSI should approach 0."""
        closes = list(range(200, 160, -1))
        df = _make_ohlcv(closes)
        result = WilderRSI().compute(df)
        last_rsi = result["rsi_14d"].iloc[-1]
        assert last_rsi < 10

    def test_rsi_warmup_period(self) -> None:
        """RSI needs 15 close values (14 deltas)."""
        closes = list(range(100, 116))  # 16 values
        df = _make_ohlcv(closes)
        result = WilderRSI().compute(df)
        # First 14 should be NaN, index 14 should be valid
        assert np.isnan(result["rsi_14d"].iloc[13])
        assert not np.isnan(result["rsi_14d"].iloc[14])

    def test_rsi_internals_exported(self) -> None:
        closes = list(range(100, 130))
        df = _make_ohlcv(closes)
        result = WilderRSI().compute(df)
        for col in ("rsi_14d", "gain_14d", "loss_14d", "rs"):
            assert col in result.columns


# --- Stochastic ---


class TestStochastic:
    def test_stochastic_range_0_100(self) -> None:
        """Stochastic %K must be clamped to 0-100."""
        np.random.seed(42)
        n = 50
        closes = (np.cumsum(np.random.randn(n)) + 2000).tolist()
        highs = [c + abs(np.random.randn() * 20) for c in closes]
        lows = [c - abs(np.random.randn() * 20) for c in closes]
        df = _make_ohlcv(closes, highs=highs, lows=lows)
        result = StochasticK().compute(df)
        valid = result["stochastic_k_14"].dropna()
        assert all(valid >= 0)
        assert all(valid <= 100)

    def test_stochastic_includes_today(self) -> None:
        """When close equals the 14-day high, %K should be 100."""
        closes = [100.0] * 14
        highs = [100.0] * 14
        lows = [90.0] * 14
        df = _make_ohlcv(closes, highs=highs, lows=lows)
        result = StochasticK().compute(df)
        assert result["stochastic_k_14"].iloc[13] == pytest.approx(100.0)

    def test_stochastic_d_is_sma3_of_k(self) -> None:
        closes = list(range(100, 130))
        df = _make_ohlcv(closes)
        df = StochasticK().compute(df)
        result = StochasticD().compute(df)
        idx = 20
        k_vals = result["stochastic_k_14"].iloc[idx - 2 : idx + 1]
        expected_d = k_vals.mean()
        assert result["stochastic_d_14"].iloc[idx] == pytest.approx(expected_d)


# --- ATR ---


class TestATR:
    def test_true_range_first_row(self) -> None:
        """First TR = High - Low (no previous close)."""
        df = _make_ohlcv([100.0], highs=[110.0], lows=[90.0])
        result = TrueRange().compute(df)
        assert result["atr"].iloc[0] == pytest.approx(20.0)

    def test_true_range_gap_up(self) -> None:
        """TR should capture gap between previous close and today's high."""
        df = _make_ohlcv(
            [100.0, 120.0],
            highs=[110.0, 130.0],
            lows=[90.0, 115.0],
        )
        result = TrueRange().compute(df)
        # TR = max(130-115, |130-100|, |115-100|) = max(15, 30, 15) = 30
        assert result["atr"].iloc[1] == pytest.approx(30.0)

    def test_wilder_atr_seed_is_sma(self) -> None:
        """First ATR value should be SMA of first 14 TRs."""
        closes = list(range(100, 120))
        df = _make_ohlcv(closes)
        df = TrueRange().compute(df)
        result = WilderATR().compute(df)
        first_14_tr = df["atr"].iloc[:14].values
        expected = np.mean(first_14_tr)
        assert result["atr_14d"].iloc[13] == pytest.approx(expected)

    def test_wilder_atr_smoothing(self) -> None:
        """ATR should use Wilder's alpha = 1/14."""
        closes = list(range(100, 120))
        df = _make_ohlcv(closes)
        df = TrueRange().compute(df)
        result = WilderATR().compute(df)
        # Check recursive: ATR[14] = (ATR[13] * 13 + TR[14]) / 14
        prev_atr = result["atr_14d"].iloc[13]
        tr_14 = df["atr"].iloc[14]
        expected = (prev_atr * 13 + tr_14) / 14
        assert result["atr_14d"].iloc[14] == pytest.approx(expected)


# --- Bollinger Bands ---


class TestBollingerBands:
    def test_middle_is_sma20(self) -> None:
        closes = list(range(100, 130))
        df = _make_ohlcv(closes)
        result = BollingerBands().compute(df)
        expected_sma = np.mean(closes[:20])
        assert result["bollinger"].iloc[19] == pytest.approx(expected_sma)

    def test_symmetric_bands(self) -> None:
        """Upper and lower bands should be equidistant from middle."""
        closes = list(range(100, 130))
        df = _make_ohlcv(closes)
        result = BollingerBands().compute(df)
        idx = 25
        middle = result["bollinger"].iloc[idx]
        upper = result["bollinger_upper"].iloc[idx]
        lower = result["bollinger_lower"].iloc[idx]
        assert upper - middle == pytest.approx(middle - lower)

    def test_width_is_relative(self) -> None:
        """Width = (upper - lower) / middle."""
        closes = list(range(100, 130))
        df = _make_ohlcv(closes)
        result = BollingerBands().compute(df)
        idx = 25
        expected_width = (
            result["bollinger_upper"].iloc[idx] - result["bollinger_lower"].iloc[idx]
        ) / result["bollinger"].iloc[idx]
        assert result["bollinger_width"].iloc[idx] == pytest.approx(expected_width)

    def test_constant_prices_zero_width(self) -> None:
        """If all prices are identical, bands collapse (width ≈ 0)."""
        closes = [2000.0] * 25
        df = _make_ohlcv(closes)
        result = BollingerBands().compute(df)
        assert result["bollinger_width"].iloc[24] == pytest.approx(0.0, abs=1e-10)


# --- Ratios ---


class TestRatios:
    def test_close_pivot_ratio(self) -> None:
        df = _make_ohlcv([100.0], highs=[110.0], lows=[90.0])
        df = PivotPoints().compute(df)
        result = ClosePivotRatio().compute(df)
        pivot = (110 + 90 + 100) / 3
        assert result["close_pivot_ratio"].iloc[0] == pytest.approx(100 / pivot)

    def test_volume_oi_ratio(self) -> None:
        df = _make_ohlcv([100.0], volumes=[10000], ois=[5000])
        result = VolumeOIRatio().compute(df)
        assert result["volume_oi_ratio"].iloc[0] == pytest.approx(2.0)

    def test_volume_oi_zero_oi(self) -> None:
        """Zero OI should produce NaN, not crash."""
        df = _make_ohlcv([100.0], volumes=[10000], ois=[0])
        result = VolumeOIRatio().compute(df)
        assert np.isnan(result["volume_oi_ratio"].iloc[0])

    def test_daily_return(self) -> None:
        df = _make_ohlcv([100.0, 105.0, 102.0])
        result = DailyReturn().compute(df)
        assert np.isnan(result["daily_return"].iloc[0])
        assert result["daily_return"].iloc[1] == pytest.approx(0.05)
        assert result["daily_return"].iloc[2] == pytest.approx(-0.02857, abs=1e-4)
