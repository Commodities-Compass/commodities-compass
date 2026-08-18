"""cc-regime-brief — native prose per language, one algorithm, no fallbacks.

The brief is the only place in the regime pipeline that writes prose, and it
writes it twice: into the .txt read aloud by NotebookLM, and onto the served
row the dashboard reads. Those two must be the same text — a split between what
is read and what is displayed is invisible until a client notices.

The properties pinned here:

  * ``rationale`` never reaches the prompt (it is a policy trace, not prose);
  * a narrative that names the machinery is refused, not published;
  * the filenames carry the ``-Regime`` suffix, so the overlapping tracks
    cannot overwrite each other on Drive;
  * every missing input raises — no silent section, no other algorithm.
"""

from __future__ import annotations

import uuid
from datetime import date as date_cls
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from scripts.regime_brief.brief_generator import render_brief
from scripts.regime_brief.config import filename_for
from scripts.regime_brief.db_reader import (
    BriefData,
    JudgeCall,
    RegimeCall,
    Technicals,
)
from scripts.regime_brief.narrator import (
    Narrative,
    NarrationError,
    _build_prompt,
    narrate,
)

_RATIONALE = "ABSTAIN HEDGE->MONITOR: judge contradicts at conf=3 (< flip bar 4)."


def _data(language: str = "fr") -> BriefData:
    return BriefData(
        session_date=date_cls(2026, 8, 17),
        contract_id=uuid.uuid4(),
        contract_code="CAU26",
        language=language,
        regime=RegimeCall(
            decision="OPEN", regime="bull", specialist="bull", prob_up=0.6123
        ),
        judge=JudgeCall(
            final_decision="MONITOR",
            direction="UP",
            stance="CONTRADICT",
            confidence=3,
            is_anomaly=False,
            changed=True,
            drift_summary="Weather stress eased while arrivals accelerated.",
            key_risk="A collapse in processing margins.",
            disconfirming_case="Smooth Ivorian port arrivals would undo this.",
            evidence=("port arrivals reached 1.996 million tonnes",),
        ),
        technicals=Technicals(
            close=Decimal("8000"),
            close_prev=Decimal("7900"),
            volume=10311,
            oi=42000,
            rsi_14d=Decimal("53.05"),
            s1=Decimal("7850"),
            r1=Decimal("8150"),
        ),
        press_summary="Les arrivages ivoiriens accélèrent.",
        press_impact="Biais haussier modéré.",
        weather_body="Impact: 2/10; pluies conformes aux normales.",
    )


def _narrative() -> Narrative:
    return Narrative(
        conclusion="Le marché reste porté.\nLes arrivages pèsent peu à ce stade.",
        eco="Le contexte fondamental reste équilibré.",
        confidence_rationale="Une normalisation logistique invaliderait la lecture.",
    )


class TestPromptHygiene:
    def test_rationale_never_reaches_the_prompt(self) -> None:
        """The policy trace stays in pl_judge_shadow, for audit and replay only."""
        prompt = _build_prompt(_data())

        assert _RATIONALE not in prompt
        assert "ABSTAIN" not in prompt
        assert "flip bar" not in prompt

    def test_judge_material_does_reach_the_prompt(self) -> None:
        """What IS editorial must be handed over — drift, risk, counter-case, quotes."""
        prompt = _build_prompt(_data())

        assert "Weather stress eased" in prompt
        assert "collapse in processing margins" in prompt
        assert "Smooth Ivorian port arrivals" in prompt
        assert "1.996 million tonnes" in prompt

    def test_each_language_gets_its_own_native_prompt(self) -> None:
        """Native composition, not translation of a single source text."""
        assert "Tu es l'analyste" in _build_prompt(_data("fr"))
        assert "You are the Compass CC desk analyst" in _build_prompt(_data("en"))


class TestNarratorGuards:
    def _client(self, payload: str) -> MagicMock:
        client = MagicMock()
        client.call.return_value = MagicMock(
            raw_text=payload, model="o4-mini", output_tokens=120
        )
        return client

    def test_machinery_mention_is_refused(self) -> None:
        """A brief is read aloud — one word about a model breaks the product."""
        client = self._client(
            '{"conclusion": "Le modèle anticipe une hausse.",'
            ' "eco": "Contexte porteur.",'
            ' "confidence_rationale": "Un repli invaliderait."}'
        )

        with pytest.raises(NarrationError, match="machinery"):
            narrate(_data(), client)

    def test_partial_narrative_is_refused(self) -> None:
        client = self._client(
            '{"conclusion": "Une lecture.", "eco": "", "confidence_rationale": "x"}'
        )

        with pytest.raises(NarrationError, match="missing"):
            narrate(_data(), client)

    def test_clean_narrative_is_accepted(self) -> None:
        client = self._client(
            '{"conclusion": "Le marché reste porté.",'
            ' "eco": "Fondamentaux équilibrés.",'
            ' "confidence_rationale": "Une normalisation invaliderait."}'
        )

        narrative = narrate(_data(), client)

        assert narrative.conclusion == "Le marché reste porté."
        assert narrative.eco == "Fondamentaux équilibrés."


class TestFilenames:
    def test_regime_suffix_prevents_drive_collision(self) -> None:
        """The legacy brief is `{date}-CompassBrief.txt` and upload overwrites."""
        assert filename_for("20260817", "fr") == "20260817-CompassBrief-Regime.txt"
        assert filename_for("20260817", "en") == "20260817-CompassBrief-Regime-EN.txt"

    def test_never_collides_with_the_legacy_or_ensemble_stems(self) -> None:
        for language in ("fr", "en"):
            name = filename_for("20260817", language)
            assert name != "20260817-CompassBrief.txt"
            assert "Ensemble" not in name


class TestRendering:
    def test_figures_come_from_the_data_not_the_prose(self) -> None:
        """facts/voice split: the template owns every number."""
        brief = render_brief(_data(), _narrative())

        assert "8 000" in brief  # close, rendered by the template
        assert "+100" in brief  # change vs previous close
        assert "+1.27 %" in brief  # percent change, computed not retyped
        assert "RSI 14j : 53" in brief  # RSI (1 decimal, value-agnostic)
        assert "7 850" in brief and "8 150" in brief  # S1 / R1
        assert "10 311" in brief and "42 000" in brief  # volume / OI

    def test_published_signal_is_the_fused_call(self) -> None:
        """MONITOR (judge) must show, not OPEN (regime's raw base call)."""
        brief = render_brief(_data(), _narrative())

        assert "MONITOR" in brief
        assert "Conviction : 3/5" in brief

    def test_narrative_sections_are_present(self) -> None:
        brief = render_brief(_data(), _narrative())

        assert "Le marché reste porté." in brief
        assert "Le contexte fondamental reste équilibré." in brief
        assert "Une normalisation logistique invaliderait la lecture." in brief

    def test_rationale_never_reaches_the_published_text(self) -> None:
        brief = render_brief(_data(), _narrative())

        assert "ABSTAIN" not in brief
        assert "flip bar" not in brief

    def test_english_brief_uses_english_labels(self) -> None:
        brief = render_brief(_data("en"), _narrative())

        assert "TODAY'S SIGNAL" in brief
        assert "MARKET" in brief
        assert "SIGNAL DU JOUR" not in brief
