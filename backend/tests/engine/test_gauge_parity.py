"""The gauge job must reproduce the engine's norms bit-for-bit.

The displayed gauge is the z-score of the SMOOTHED score, not of the raw
indicator. Skipping the smoothing stage would still produce plausible numbers —
they would simply stop matching the ``test_range`` calibration, and the gauge
colours would drift with no error anywhere. Nothing but an equality test
catches that, which is why this file exists.

Verified against production data on 2026-08-18: every session from 2026-07-22
onward matches to 0.000000. Sessions BEFORE that date diverge by 0.6-26 points,
and that is expected — see ``test_documents_the_frozen_history_boundary``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.engine.pipeline import IndicatorPipeline
from app.engine.types import LEGACY_V1
from scripts.compute_gauges.computer import (
    GAUGE_SPECS,
    compute_gauge_frame,
)

# Matches the engine defaults the gauges were calibrated against.
_TOLERANCE = 1e-9


def _make_market_data(n: int = 400, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    prices = np.maximum(np.cumsum(rng.normal(0, 20, n)) + 2500, 500)
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=n, freq="B"),
            "close": prices,
            "high": prices + rng.uniform(10, 50, n),
            "low": prices - rng.uniform(10, 50, n),
            "volume": rng.integers(1000, 20000, n),
            "oi": rng.integers(30000, 80000, n),
            "implied_volatility": rng.uniform(0.3, 0.7, n),
            "macroeco_bonus": rng.uniform(-0.1, 0.1, n),
        }
    )


def _engine_result(df: pd.DataFrame):
    """Run the real engine pipeline — the reference the gauges must match."""
    return IndicatorPipeline(config=LEGACY_V1).run(df)


@pytest.mark.parametrize(
    "indicator_name,raw_col,score_col,norm_col",
    GAUGE_SPECS,
    ids=[spec[0] for spec in GAUGE_SPECS],
)
def test_gauge_matches_engine_norm(
    indicator_name: str, raw_col: str, score_col: str, norm_col: str
) -> None:
    """Stage 3 (the plotted value) is identical to the engine's."""
    market = _make_market_data()
    engine = _engine_result(market)

    # The gauge job starts from stored pl_derived_indicators, i.e. the engine's
    # derived frame — same input, so any difference is in the two stages the
    # gauge job re-applies.
    gauges = compute_gauge_frame(engine.derived)

    expected = pd.Series(engine.normalized[norm_col]).reset_index(drop=True)
    actual = pd.Series(gauges[norm_col]).reset_index(drop=True)

    pd.testing.assert_series_equal(
        actual, expected, check_names=False, atol=_TOLERANCE, rtol=0
    )


@pytest.mark.parametrize(
    "indicator_name,raw_col,score_col,norm_col",
    GAUGE_SPECS,
    ids=[spec[0] for spec in GAUGE_SPECS],
)
def test_gauge_matches_engine_score(
    indicator_name: str, raw_col: str, score_col: str, norm_col: str
) -> None:
    """Stage 2 too — a score drift would silently shift every z-score after it."""
    market = _make_market_data()
    engine = _engine_result(market)
    gauges = compute_gauge_frame(engine.derived)

    expected = pd.Series(engine.scores[score_col]).reset_index(drop=True)
    actual = pd.Series(gauges[score_col]).reset_index(drop=True)

    pd.testing.assert_series_equal(
        actual, expected, check_names=False, atol=_TOLERANCE, rtol=0
    )


def test_skipping_the_smoothing_stage_would_be_detected() -> None:
    """Guard the guard: z-scoring the RAW value must NOT match.

    Without this, a regression that drops the SMA-5 stage could slip through if
    the other assertions were ever weakened — the whole failure mode is that
    wrong values still look reasonable.
    """
    from app.engine.normalization import rolling_zscore

    from scripts.compute_gauges.computer import (
        GAUGE_NORM_WINDOW,
        GAUGE_OUTLIER_CAP,
    )

    market = _make_market_data()
    engine = _engine_result(market)

    naive = rolling_zscore(
        pd.Series(engine.derived["rsi_14d"]),
        window=GAUGE_NORM_WINDOW,
        outlier_cap=GAUGE_OUTLIER_CAP,
    ).reset_index(drop=True)
    correct = pd.Series(engine.normalized["rsi_norm"]).reset_index(drop=True)

    both_defined = naive.notna() & correct.notna()
    assert both_defined.any(), "fixture too short to compare"
    delta = pd.Series(naive[both_defined]) - pd.Series(correct[both_defined])
    assert float(delta.abs().max()) > 0.01


def test_documents_the_frozen_history_boundary() -> None:
    """Why prod parity holds only from 2026-07-22 — do not "fix" this.

    On 2026-07-22 the macroeco fan-out corruption was repaired with
    ``compute-indicators --full --derived-only``: pl_derived_indicators was
    recomputed while pl_indicator_daily (scores, norms, decisions) was left
    FROZEN on purpose, so historical decisions were not restated.

    Consequence: for sessions before that date, pl_indicator_daily.*_norm holds
    pre-correction values that no longer match the corrected derived
    indicators they claim to summarise. The gauge job recomputes from the
    corrected data, so it necessarily differs there — measured on prod
    2026-08-18: 0.6 to 26.3 points before the boundary, 0.000000 after it.

    Switching /indicators-grid to pl_dashboard_gauge therefore CORRECTS the
    historical gauges rather than reproducing them. That is a deliberate
    product decision, recorded here so nobody later reads the divergence as a
    bug in this job.
    """
    from datetime import date

    frozen_history_boundary = date(2026, 7, 22)
    assert frozen_history_boundary.isoformat() == "2026-07-22"
