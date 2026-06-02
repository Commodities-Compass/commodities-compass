"""Tests for the redacted Compass daily brief generator (pure formatter).

The brief is uploaded verbatim to NotebookLM for daily audio generation, so
its surface is intentionally redacted of any reference to the underlying
decision engine. These tests enforce both the new shape (6 sections) and the
absence of forbidden engine-revealing tokens — adding any of them back to
the rendered text is a regression.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from scripts.compass_brief_ensemble.brief_generator import (
    UnsafeBriefContentError,
    render_brief,
)
from scripts.compass_brief_ensemble.db_reader import EnsembleBriefData, SpecialistVote


# Tokens that must NEVER appear in the rendered brief. Each one is either
# a model-family hint, an architecture leak, or an internal diagnostic name.
_FORBIDDEN_TOKENS = (
    "ensemble v1",
    "Ensemble v1",
    "machine learning",
    "soft-gate",
    "softgate",
    "wrapper",
    "Wrapper",
    "detectors",
    "Detectors",
    "dispersion fire",
    "running_acc",
    "realized_return",
    "anomaly_z",
    "anomaly_score_z",
    "cluster Winter",
    "cluster Spring",
    "orchestrateur bayésien",
    "14 spécialistes",
    "spécialistes sur 14",
    "sur 14 confirment",
    "panel de 14",
    "net_score",
    "net score",
    "filet de sécurité",
    "propriétaires",
    "machine-learning",
)


def _sample_data(decision: str = "OPEN", **overrides) -> EnsembleBriefData:
    base = dict(
        target_date=date(2026, 5, 27),
        decision=decision,
        confidence=4,
        direction="HAUSSIERE",
        conclusion=(
            "Position OPEN tenable sur 4-5 sessions. Macro favorable.\n"
            "À SURVEILLER : pression FX\n"
            "À SURVEILLER : sortie macro hebdomadaire"
        ),
        eco="Marché stable. Press neutre.",
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
            SpecialistVote("exp_optim_002", "OPEN", 12),  # technique
            SpecialistVote("exp_optim_005", "OPEN", 12),  # volatilité
            SpecialistVote("exp_optim_017_bull_4", "OPEN", 12),  # fx
            SpecialistVote("exp_optim_017_bull_8", "OPEN", 12),  # macro
            SpecialistVote("xpol_W_TB_garch", "HEDGE", 24),  # dissenter
        ],
        press_summary="Marché cocoa stable. Production CIV en ligne.",
        press_impact="Neutre",
        press_sentiment="neutre",
        meteo_summary="Pluies modérées à Daloa. Soubré sec.",
        meteo_impact="Impact production faible",
        technicals_snapshot="Date close : 2026-05-26\n  CLOSE=4,500.00 ...",
        persistence_days=3,
        ytd_score=Decimal("12.45"),
    )
    base.update(overrides)
    return EnsembleBriefData(**base)


@pytest.mark.unit
def test_brief_contains_all_six_sections() -> None:
    text = render_brief(_sample_data())
    for marker in (
        "I — SIGNAL",
        "II — LECTURE ÉDITORIALE",
        "III — ÉCO & PRESS REVIEW",
        "IV — WEATHER WATCH",
        "V — CHIFFRES TECHNIQUES",
        "VI — RECOMMANDATIONS",
    ):
        assert marker in text, f"Missing section: {marker}"


@pytest.mark.unit
def test_brief_does_not_render_dropped_sections() -> None:
    text = render_brief(_sample_data())
    for dropped in (
        "MACRO RADAR",
        "À PROPOS DU PANEL",
        "DÉCOMPOSITION",
        "Triggers de réévaluation",
        "Persistence",
        "Voix engagées",
        "Voix silencieuses",
    ):
        assert dropped not in text, (
            f"'{dropped}' should not appear in the redacted brief."
        )


@pytest.mark.unit
@pytest.mark.parametrize("token", _FORBIDDEN_TOKENS)
def test_brief_redacts_forbidden_engine_tokens(token: str) -> None:
    """Fail-loud regression guard for engine-revealing wording in the
    rendered brief — adding any of these tokens back is a leak."""
    text = render_brief(_sample_data())
    assert token not in text, f"Forbidden token leaked in the redacted brief: {token!r}"


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
        specialists=[
            SpecialistVote("exp_optim_017_bear_4", "HEDGE", 12),  # bearish FX
            SpecialistVote("xpol_S_bear_garch_macro", "HEDGE", 24),  # bearish macro
            SpecialistVote("exp_optim_002", "OPEN", 12),  # dissenter, ignored
        ],
    )
    text = render_brief(data)
    assert "Position           : HEDGE" in text
    assert "BAISSIERE" in text


@pytest.mark.unit
def test_signal_section_shows_ytd_when_present() -> None:
    text = render_brief(_sample_data(ytd_score=Decimal("12.45")))
    assert "Performance YTD" in text
    assert "+12.45%" in text


@pytest.mark.unit
def test_signal_section_skips_ytd_when_missing() -> None:
    text = render_brief(_sample_data(ytd_score=None))
    assert "Performance YTD" not in text


@pytest.mark.unit
def test_signal_section_renders_negative_ytd_with_sign() -> None:
    text = render_brief(_sample_data(ytd_score=Decimal("-3.10")))
    assert "-3.10%" in text


@pytest.mark.unit
def test_editorial_section_names_a_headline_specialist() -> None:
    """The editorial section should name exactly one specialist as the
    headline (Top 1 + thematic), aligned with the daily decision."""
    text = render_brief(_sample_data(decision="OPEN"))
    assert "Lecture phare du jour" in text
    # The headline label for an OPEN day with a Bullish FX engaged
    # specialist in the fixture should be "Stratège haussier FX"
    # (bullish bias + pred=OPEN).
    assert "Stratège haussier FX" in text


@pytest.mark.unit
def test_editorial_section_groups_others_by_theme() -> None:
    text = render_brief(_sample_data())
    assert "D'autres lectures convergent" in text


@pytest.mark.unit
def test_editorial_section_handles_no_engaged_specialists() -> None:
    """When the entire panel abstains, the editorial section degrades
    gracefully without leaking any engine framing."""
    data = _sample_data(
        decision="MONITOR",
        specialists=[
            SpecialistVote("exp_optim_002", "MONITOR", 12),
            SpecialistVote("exp_optim_005", "MONITOR", 12),
        ],
    )
    text = render_brief(data)
    assert "Pas de lecture marquée engagée" in text


@pytest.mark.unit
def test_intro_is_brand_only_neutral_line() -> None:
    """The intro must NOT describe the architecture (panel size, model
    family, training scope) — only the product framing."""
    text = render_brief(_sample_data())
    intro_marker = "Lecture Compass du jour sur le front-month cocoa Londres"
    assert intro_marker in text


@pytest.mark.unit
def test_header_drops_engine_version_branding() -> None:
    text = render_brief(_sample_data())
    assert "COMPASS DAILY BRIEF — Cocoa Outlook" in text
    # No version suffix in the header
    assert "(Ensemble v1.0.0)" not in text


@pytest.mark.unit
def test_missing_eco_and_conclusion_still_renders() -> None:
    text = render_brief(_sample_data(eco=None, conclusion=None))
    assert "III — ÉCO & PRESS REVIEW" in text
    assert "VI — RECOMMANDATIONS" in text


@pytest.mark.unit
def test_unsafe_conclusion_fails_loud() -> None:
    """When cc-ensemble-explainer hasn't run, pl_indicator_daily.conclusion
    still holds the placeholder written by cc-ensemble-compute, which embeds
    'soft-gate=', 'wrapper_fired=' and other engine internals. The brief
    job MUST refuse to render — per fail-loud pipeline policy, the operator
    diagnoses the upstream agent, fixes it, and relaunches manually."""
    placeholder = (
        "C5 ensemble decision=OPEN (soft-gate=OPEN, wrapper_fired=[none], "
        "winter=-1, spring=-5)"
    )
    with pytest.raises(UnsafeBriefContentError, match="conclusion"):
        render_brief(_sample_data(conclusion=placeholder))


@pytest.mark.unit
def test_unsafe_eco_field_fails_loud() -> None:
    leaky_eco = "Marché stable. Anomaly_z=0.42, soft-gate confirms."
    with pytest.raises(UnsafeBriefContentError, match="eco"):
        render_brief(_sample_data(eco=leaky_eco))


@pytest.mark.unit
def test_unsafe_conclusion_llm_panel_count_fails_loud() -> None:
    """Real-world regression: cc-ensemble-explainer LLM previously wrote
    '> 8 spécialistes sur 14 confirment...' which the original forbidden
    list missed (it only matched the forward order '14 spécialistes').
    The expanded list must catch both orientations."""
    leaky = (
        "> 8 spécialistes sur 14 confirment la position HEDGE, "
        "conviction forte (net_score -1.000).\n"
        "        • CLOSE aujourd'hui à 2964..."
    )
    with pytest.raises(UnsafeBriefContentError):
        render_brief(_sample_data(conclusion=leaky))


@pytest.mark.unit
def test_unsafe_press_summary_fails_loud() -> None:
    """Defense-in-depth: even press_review (an external LLM) is checked —
    an accidental hallucination embedding 'soft-gate' would otherwise leak
    straight into the podcast."""
    leaky_press = "Marché stable. Le soft-gate indique une orientation."
    with pytest.raises(UnsafeBriefContentError, match="press_summary"):
        render_brief(_sample_data(press_summary=leaky_press))
