"""Tests for the adhesion-based qualitative conviction mapping.

``_qualitative_conviction`` is the new base of the brief's confidence score
(``forte`` / ``modérée`` / ``faible``). It replaces the raw ``net_score``
that the LLM previously saw and quoted — the LLM now only sees the label,
no number.

Formula : adhesion = |net_score| × sqrt(n_committed / 14)

Thresholds calibrated against the 30-day prod distribution :
    adhesion ≥ 0.70 → forte
    0.40 ≤ a < 0.70 → modérée
    adhesion < 0.40 → faible
"""

from __future__ import annotations

import pytest

from scripts.daily_analysis.prompts import _qualitative_conviction


@pytest.mark.unit
class TestQualitativeConviction:
    def test_saturated_net_score_high_engagement_returns_forte(self) -> None:
        # 2026-06-01 prod row: net=-1, n_committed=8 → adhesion = 1×√(8/14)=0.756
        assert _qualitative_conviction(-1.0, 8) == "forte"

    def test_saturated_net_score_mid_engagement_returns_forte(self) -> None:
        # 2026-06-02 prod row: net=-1, n_committed=7 → adhesion = 0.707
        assert _qualitative_conviction(-1.0, 7) == "forte"

    def test_saturated_net_score_low_engagement_returns_moderee(self) -> None:
        # 2026-05-28 prod row: net=+1, n_committed=4 → adhesion = 0.535
        assert _qualitative_conviction(1.0, 4) == "modérée"

    def test_saturated_net_score_very_low_engagement_returns_moderee(self) -> None:
        # n=3 → adhesion = √(3/14) = 0.463 → modérée (just above 0.40)
        assert _qualitative_conviction(1.0, 3) == "modérée"

    def test_saturated_net_score_minimal_engagement_returns_faible(self) -> None:
        # n=2 → adhesion = √(2/14) = 0.378 → faible
        assert _qualitative_conviction(-1.0, 2) == "faible"

    def test_partial_net_score_high_engagement_returns_faible(self) -> None:
        # 2026-04-23 prod row: net=-0.20, n_committed=11 → adhesion = 0.177
        assert _qualitative_conviction(-0.20, 11) == "faible"

    def test_full_unanimity_returns_forte(self) -> None:
        # 14/14 unanimous → adhesion = 1.0 → forte
        assert _qualitative_conviction(1.0, 14) == "forte"

    def test_zero_engagement_returns_faible(self) -> None:
        # No specialist committed → adhesion = 0 → faible (safe default)
        assert _qualitative_conviction(0.0, 0) == "faible"

    def test_none_inputs_return_faible(self) -> None:
        assert _qualitative_conviction(None, None) == "faible"
        assert _qualitative_conviction(-1.0, None) == "faible"
        assert _qualitative_conviction(None, 8) == "faible"

    def test_invalid_inputs_return_faible(self) -> None:
        # Defensive — non-numeric strings should not raise.
        assert _qualitative_conviction("not_a_number", 5) == "faible"

    def test_threshold_boundary_just_below_forte(self) -> None:
        # Adhesion just below 0.70 must NOT be forte.
        # |net|=0.95, n=7 → 0.95 × √0.5 = 0.671
        assert _qualitative_conviction(0.95, 7) == "modérée"

    def test_threshold_boundary_just_above_modere(self) -> None:
        # Adhesion just above 0.40 must be modérée.
        # |net|=0.6, n=7 → 0.6 × √0.5 = 0.424
        assert _qualitative_conviction(0.6, 7) == "modérée"
