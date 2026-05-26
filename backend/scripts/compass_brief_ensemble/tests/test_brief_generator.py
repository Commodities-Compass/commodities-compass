"""Tests for the ensemble brief generator (pure formatter)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from scripts.compass_brief_ensemble.brief_generator import render_brief
from scripts.compass_brief_ensemble.db_reader import EnsembleBriefData, SpecialistVote


def _sample_data(decision: str = "OPEN", **overrides) -> EnsembleBriefData:
    base = dict(
        target_date=date(2026, 5, 27),
        decision=decision,
        confidence=4,
        direction="HAUSSIERE",
        conclusion=(
            "Position OPEN tenable sur 4-5 jours. Macro favorable.\n"
            "À SURVEILLER : anomaly_z > 2.5\n"
            "À SURVEILLER : sentiment shift > 1.5σ"
        ),
        eco="Marché stable. Press neutre. Anomaly z=0.4 (normal).",
        soft_gate_decision=decision,
        wrapper_active=False,
        net_score=Decimal("0.2345"),
        n_committed_specialists=11,
        fired_running_acc=False,
        fired_trend=False,
        fired_dispersion=False,
        fired_three_way=False,
        running_acc_5d=Decimal("0.9100"),
        realized_return_5d=Decimal("0.0212"),
        anomaly_score_z=Decimal("0.40"),
        macro_direction=1,
        macro_surprise=Decimal("0.420"),
        macro_half_life_days=4,
        prior_open=Decimal("0.51"),
        prior_hedge=Decimal("0.21"),
        prior_monitor=Decimal("0.28"),
        winter_vote_signed=3,
        spring_vote_signed=2,
        specialists=[
            SpecialistVote("exp_optim_002", "OPEN", 12),
            SpecialistVote("exp_optim_005", "OPEN", 12),
            SpecialistVote("exp_optim_008", "OPEN", 12),
            SpecialistVote("exp_optim_011", "OPEN", 12),
            SpecialistVote("xpol_W_TB_garch", "HEDGE", 24),
            SpecialistVote("xpol_S_macro_combined", "OPEN", 12),
        ],
        press_summary="Marché cocoa stable. Production CIV en ligne.",
        press_impact="Neutre",
        press_sentiment="neutre",
        meteo_summary="Pluies modérées à Daloa. Soubré sec.",
        meteo_impact="Impact production faible",
        technicals_snapshot="Date close : 2026-05-26\n  CLOSE=4,500.00 ...",
        persistence_days=3,
    )
    base.update(overrides)
    return EnsembleBriefData(**base)


@pytest.mark.unit
def test_brief_contains_all_seven_sections() -> None:
    text = render_brief(_sample_data())
    for marker in (
        "I — SIGNAL ENSEMBLE",
        "II — DÉCOMPOSITION 14 SPÉCIALISTES",
        "III — MACRO RADAR ENSEMBLE",
        "IV — ÉCO & PRESS REVIEW",
        "V — WEATHER WATCH",
        "VI — CHIFFRES TECHNIQUES",
        "VII — RECOMMANDATIONS",
    ):
        assert marker in text, f"Missing section: {marker}"


@pytest.mark.unit
def test_decision_open_appears_in_signal_section() -> None:
    text = render_brief(_sample_data(decision="OPEN"))
    assert "Position           : OPEN" in text


@pytest.mark.unit
def test_decision_hedge_renders_consistently() -> None:
    data = _sample_data(
        decision="HEDGE",
        direction="BAISSIERE",
        soft_gate_decision="HEDGE",
        winter_vote_signed=-3,
        spring_vote_signed=-2,
        macro_direction=-1,
    )
    text = render_brief(data)
    assert "Position           : HEDGE" in text
    assert "BAISSIERE" in text
    assert "bearish" in text


@pytest.mark.unit
def test_persistence_days_shown() -> None:
    text = render_brief(_sample_data(persistence_days=5))
    assert "5 jour(s)" in text


@pytest.mark.unit
def test_dissenter_detection() -> None:
    text = render_brief(_sample_data(decision="OPEN"))
    assert "Désaccord notable" in text
    assert "xpol_W_TB_garch" in text  # the lone HEDGE in our sample


@pytest.mark.unit
def test_specialists_table_lists_all_with_clusters() -> None:
    text = render_brief(_sample_data())
    # All 6 specialists must appear in the table
    assert "exp_optim_002" in text
    assert "xpol_W_TB_garch" in text
    # Cluster annotation visible (winter or spring or other)
    assert "[winter]" in text or "[spring]" in text


@pytest.mark.unit
def test_anomaly_critical_label() -> None:
    text = render_brief(_sample_data(anomaly_score_z=Decimal("3.10")))
    assert "CRITIQUE" in text


@pytest.mark.unit
def test_low_running_acc_triggers_extra_trigger() -> None:
    text = render_brief(_sample_data(running_acc_5d=Decimal("0.55")))
    assert "running_acc_5d=0.550" in text  # Note: rendered with _fmt precision 3
    assert "sous 0.6" in text


@pytest.mark.unit
def test_missing_eco_still_renders() -> None:
    text = render_brief(_sample_data(eco=None, conclusion=None))
    assert "ÉCO & PRESS REVIEW" in text
    assert "VII — RECOMMANDATIONS" in text


@pytest.mark.unit
def test_winter_signed_vote_shows_bullish_glyph() -> None:
    text = render_brief(_sample_data(winter_vote_signed=4))
    assert "Cluster Winter" in text
    # Has either the ↗ glyph or "bullish" tag
    assert "↗" in text or "bullish" in text
