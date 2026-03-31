"""Pipeline orchestrator: raw market data → trading signals.

Chains: derived indicators → raw scores → z-score normalization → composite.
All operations are pure functions over DataFrames — no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from app.engine.composite import compute_signals
from app.engine.indicators import ALL_INDICATORS
from app.engine.normalization import normalize_scores
from app.engine.registry import IndicatorRegistry
from app.engine.smoothing import compute_raw_scores
from app.engine.types import AlgorithmConfig, LEGACY_V1


@dataclass(frozen=True)
class PipelineResult:
    """Immutable result of a full pipeline run."""

    derived: pd.DataFrame  # raw data + all derived indicator columns
    scores: pd.DataFrame  # + raw score columns
    normalized: pd.DataFrame  # + z-score columns
    signals: pd.DataFrame  # + composite score, momentum, decision


class IndicatorPipeline:
    """Orchestrates the full computation flow.

    Usage:
        pipeline = IndicatorPipeline()
        result = pipeline.run(raw_df)
        # result.signals has all columns including final_indicator, decision
    """

    def __init__(
        self,
        config: AlgorithmConfig = LEGACY_V1,
        normalization_window: int = 252,
        outlier_cap: float = 10.0,
    ) -> None:
        self.config = config
        self.normalization_window = normalization_window
        self.outlier_cap = outlier_cap

        self._registry = IndicatorRegistry()
        self._registry.register_all(ALL_INDICATORS)

    def run(
        self,
        raw_df: pd.DataFrame,
        macroeco_col: str = "macroeco_bonus",
    ) -> PipelineResult:
        """Execute the full pipeline on raw market data.

        Args:
            raw_df: DataFrame with columns: date, close, high, low,
                     volume, oi, implied_volatility, stock_us, com_net_us.
                     Optionally: macroeco_bonus (LLM-generated).
                     Must be sorted by date ascending.
            macroeco_col: Column name for macroeco bonus values.

        Returns:
            PipelineResult with derived, scores, normalized, and signals DataFrames.
        """
        # Step 1: Compute all derived indicators in dependency order
        derived = self._registry.compute_all(raw_df)

        # Step 2: Compute SMA raw scores
        scores = compute_raw_scores(
            derived, smoothing_window=self.config.smoothing_window
        )

        # Step 3: Rolling z-score normalization
        normalized = normalize_scores(
            scores,
            window=self.normalization_window,
            outlier_cap=self.outlier_cap,
        )

        # Step 4: Composite score + decision
        signals = compute_signals(normalized, self.config, macroeco_col=macroeco_col)

        return PipelineResult(
            derived=derived,
            scores=scores,
            normalized=normalized,
            signals=signals,
        )
