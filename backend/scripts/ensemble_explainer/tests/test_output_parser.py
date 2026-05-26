"""Unit tests for the Explainer output parser."""

from __future__ import annotations

import pytest

from scripts.ensemble_explainer.output_parser import (
    ExplainerOutputError,
    parse_explainer_output,
)


def _valid_payload(**overrides):
    base = {
        "eco": "Marché stable, anomaly z=0.4. Press neutre.",
        "confidence": 4,
        "direction": "HAUSSIERE",
        "conclusion": (
            "Position OPEN tenable sur la fenêtre 4-5 jours. Specialists cluster Winter +3, "
            "macro_surprise +0.42σ.\n"
            "À SURVEILLER : anomaly_score_z > 2.5\n"
            "À SURVEILLER : sentiment shift > 1.5σ\n"
            "À SURVEILLER : dispersion fire"
        ),
    }
    base.update(overrides)
    return base


@pytest.mark.unit
def test_valid_open_payload() -> None:
    out = parse_explainer_output(_valid_payload(), expected_decision="OPEN")
    assert out.confidence == 4
    assert out.direction == "HAUSSIERE"
    assert "À SURVEILLER" in out.conclusion


@pytest.mark.unit
def test_missing_key_fails() -> None:
    payload = _valid_payload()
    del payload["confidence"]
    with pytest.raises(ExplainerOutputError, match="Missing keys"):
        parse_explainer_output(payload, expected_decision="OPEN")


@pytest.mark.unit
def test_confidence_out_of_range() -> None:
    with pytest.raises(ExplainerOutputError, match="out of"):
        parse_explainer_output(_valid_payload(confidence=6), expected_decision="OPEN")
    with pytest.raises(ExplainerOutputError, match="out of"):
        parse_explainer_output(_valid_payload(confidence=0), expected_decision="OPEN")


@pytest.mark.unit
def test_direction_normalisation() -> None:
    out = parse_explainer_output(
        _valid_payload(direction="haussière"), expected_decision="OPEN"
    )
    assert out.direction == "HAUSSIERE"


@pytest.mark.unit
def test_invalid_direction() -> None:
    with pytest.raises(ExplainerOutputError, match="direction"):
        parse_explainer_output(
            _valid_payload(direction="LATERALE"), expected_decision="OPEN"
        )


@pytest.mark.unit
def test_eco_truncated() -> None:
    long_eco = "x" * 600
    out = parse_explainer_output(_valid_payload(eco=long_eco), expected_decision="OPEN")
    assert len(out.eco) == 300


@pytest.mark.unit
def test_conclusion_contradicts_decision_open() -> None:
    """LLM cannot recommend 'vendre' / 'short' / 'hedge' if decision = OPEN."""
    bad = _valid_payload(conclusion="Position OPEN mais il faut vendre rapidement.")
    with pytest.raises(ExplainerOutputError, match="contradicts ensemble decision"):
        parse_explainer_output(bad, expected_decision="OPEN")


@pytest.mark.unit
def test_conclusion_contradicts_decision_hedge() -> None:
    """LLM cannot recommend 'acheter' / 'open' / 'long' if decision = HEDGE."""
    bad = _valid_payload(conclusion="Position HEDGE mais il faut acheter.")
    with pytest.raises(ExplainerOutputError, match="contradicts ensemble decision"):
        parse_explainer_output(bad, expected_decision="HEDGE")


@pytest.mark.unit
def test_monitor_accepts_both_directions() -> None:
    """MONITOR is neutral — both 'vendre' and 'acheter' are tolerated."""
    payload = _valid_payload(
        conclusion="Position MONITOR — surveiller signaux acheteurs/vendeurs."
    )
    out = parse_explainer_output(payload, expected_decision="MONITOR")
    assert out.conclusion.startswith("Position MONITOR")


@pytest.mark.unit
def test_bad_expected_decision_raises() -> None:
    with pytest.raises(ExplainerOutputError, match="expected_decision"):
        parse_explainer_output(_valid_payload(), expected_decision="BUY")
