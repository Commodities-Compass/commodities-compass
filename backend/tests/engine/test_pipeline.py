"""Tests for the full pipeline: raw data → trading signals."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.engine.normalization import rolling_zscore
from app.engine.pipeline import IndicatorPipeline, PipelineResult
from app.engine.registry import IndicatorRegistry
from app.engine.smoothing import compute_raw_scores
from app.engine.types import NEW_CHAMPION


def _make_market_data(n: int = 300, seed: int = 42) -> pd.DataFrame:
    """Generate realistic-looking market data for pipeline tests."""
    rng = np.random.default_rng(seed)
    prices = np.cumsum(rng.normal(0, 20, n)) + 2500
    prices = np.maximum(prices, 500)  # floor at 500

    highs = prices + rng.uniform(10, 50, n)
    lows = prices - rng.uniform(10, 50, n)

    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=n, freq="B"),
            "close": prices,
            "high": highs,
            "low": lows,
            "volume": rng.integers(1000, 20000, n),
            "oi": rng.integers(30000, 80000, n),
            "implied_volatility": rng.uniform(0.3, 0.7, n),
            "stock_us": rng.uniform(100000, 200000, n),
            "com_net_us": rng.uniform(-20000, 5000, n),
            "macroeco_bonus": rng.uniform(-0.1, 0.1, n),
        }
    )


class TestRegistry:
    def test_topological_sort(self) -> None:
        """Dependencies are resolved: pivots before close_pivot_ratio."""
        registry = IndicatorRegistry()
        from app.engine.indicators import ALL_INDICATORS

        registry.register_all(ALL_INDICATORS)
        order = registry.compute_order()
        names = [ind.name for ind in order]

        # Pivots must come before close_pivot_ratio
        assert names.index("pivot_points") < names.index("close_pivot_ratio")
        # EMA must come before MACD
        assert names.index("ema12") < names.index("macd")
        assert names.index("ema26") < names.index("macd")
        # MACD must come before MACD signal
        assert names.index("macd") < names.index("macd_signal")
        # True range before Wilder ATR
        assert names.index("true_range") < names.index("wilder_atr")
        # Stochastic K before D
        assert names.index("stochastic_k") < names.index("stochastic_d")

    def test_circular_dependency_detected(self) -> None:
        """Registry should raise on circular dependencies."""

        class FakeA:
            name = "a"
            outputs = ("col_a",)
            depends_on = ("col_b",)
            warmup = 0

            def compute(self, df):
                return df

        class FakeB:
            name = "b"
            outputs = ("col_b",)
            depends_on = ("col_a",)
            warmup = 0

            def compute(self, df):
                return df

        registry = IndicatorRegistry()
        registry.register(FakeA())
        registry.register(FakeB())
        with pytest.raises(ValueError, match="Circular"):
            registry.compute_order()


class TestSmoothing:
    def test_rsi_score_is_sma5(self) -> None:
        """RSI score should be 5-day SMA of rsi_14d."""
        df = _make_market_data(50)
        # Add a fake rsi_14d column
        df["rsi_14d"] = range(50)
        df["macd"] = range(50)
        df["stochastic_k_14"] = range(50)
        df["atr_14d"] = range(50)
        df["volume_oi_ratio"] = [0.5] * 50
        df["close_pivot_ratio"] = [1.0] * 50

        result = compute_raw_scores(df)
        # Check index 10 (well past warmup)
        expected = np.mean([6, 7, 8, 9, 10])
        assert result["rsi_score"].iloc[10] == pytest.approx(expected)

    def test_close_pivot_not_smoothed(self) -> None:
        """Close/Pivot should be direct copy, no smoothing."""
        df = _make_market_data(30)
        df["rsi_14d"] = [50.0] * 30
        df["macd"] = [0.0] * 30
        df["stochastic_k_14"] = [50.0] * 30
        df["atr_14d"] = [100.0] * 30
        df["volume_oi_ratio"] = [0.5] * 30
        df["close_pivot_ratio"] = [1.01, 1.02, 1.03] * 10

        result = compute_raw_scores(df)
        # [1.01, 1.02, 1.03, 1.01, 1.02, 1.03, ...] → index 5 = 1.03
        assert result["close_pivot"].iloc[5] == pytest.approx(1.03)


class TestNormalization:
    def test_rolling_zscore_mean_zero(self) -> None:
        """Z-scores over a stable window should have mean ≈ 0."""
        np.random.seed(42)
        series = pd.Series(np.random.randn(500) * 10 + 50)
        z = rolling_zscore(series, window=252)
        valid = z.dropna()
        assert abs(valid.mean()) < 0.5  # approximately zero

    def test_outlier_clipping(self) -> None:
        """Values beyond cap should be clipped."""
        series = pd.Series([50.0] * 300 + [1000.0])  # extreme outlier
        z = rolling_zscore(series, window=252, outlier_cap=10.0)
        assert z.iloc[-1] <= 10.0

    def test_zero_std_produces_nan(self) -> None:
        """Constant values should produce NaN (not inf)."""
        series = pd.Series([100.0] * 300)
        z = rolling_zscore(series, window=252)
        valid = z.dropna()
        assert not any(np.isinf(valid))


class TestFullPipeline:
    def test_pipeline_runs_end_to_end(self) -> None:
        """Pipeline should produce all expected columns without crashing."""
        df = _make_market_data(300)
        pipeline = IndicatorPipeline(config=NEW_CHAMPION)
        result = pipeline.run(df)

        assert isinstance(result, PipelineResult)

        # Check derived indicators exist
        for col in (
            "pivot",
            "ema12",
            "macd",
            "rsi_14d",
            "stochastic_k_14",
            "atr_14d",
            "bollinger",
        ):
            assert col in result.derived.columns, f"Missing derived column: {col}"

        # Check scores exist
        for col in ("rsi_score", "macd_score", "close_pivot"):
            assert col in result.scores.columns, f"Missing score column: {col}"

        # Check normalized exist
        for col in ("rsi_norm", "macd_norm", "stoch_k_norm"):
            assert col in result.normalized.columns, f"Missing norm column: {col}"

        # Check signals exist
        for col in ("final_indicator", "decision", "momentum", "indicator_value"):
            assert col in result.signals.columns, f"Missing signal column: {col}"

    def test_pipeline_decisions_are_valid(self) -> None:
        """All decisions should be OPEN, MONITOR, or HEDGE."""
        df = _make_market_data(300)
        pipeline = IndicatorPipeline()
        result = pipeline.run(df)
        valid_decisions = {"OPEN", "MONITOR", "HEDGE"}
        actual = set(result.signals["decision"].unique())
        assert actual.issubset(valid_decisions)

    def test_pipeline_immutability(self) -> None:
        """Pipeline should not mutate the input DataFrame."""
        df = _make_market_data(100)
        original_cols = set(df.columns)
        original_shape = df.shape
        pipeline = IndicatorPipeline()
        pipeline.run(df)
        assert set(df.columns) == original_cols
        assert df.shape == original_shape

    def test_pipeline_with_missing_macroeco(self) -> None:
        """Pipeline should handle missing macroeco_bonus gracefully."""
        df = _make_market_data(300)
        df = df.drop(columns=["macroeco_bonus"])
        pipeline = IndicatorPipeline()
        result = pipeline.run(df)
        # Should still produce valid decisions
        assert "decision" in result.signals.columns

    def test_pipeline_short_data(self) -> None:
        """Pipeline should handle data shorter than warmup periods (all NaN, no crash)."""
        df = _make_market_data(10)
        pipeline = IndicatorPipeline()
        result = pipeline.run(df)
        # Most values will be NaN but should not crash
        assert len(result.signals) == 10
