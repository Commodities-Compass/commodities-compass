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

import json

import uuid
from datetime import date as date_cls
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from scripts.regime_brief.brief_generator import BriefLeakError, render_brief
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
        target_date=date_cls(2026, 8, 18),
        contract_id=uuid.uuid4(),
        contract_code="CAU26",
        language=language,
        technicals_snapshot=(
            "Date close : 2026-08-17\n"
            "  CLOSE=8,000.00 | HIGH=8,060.00 | LOW=7,930.00\n"
            "  VOLUME=10311 | OI=42000 | IV=0.45\n"
            "  STOCK_US=233,799.00 | STOCK_EU=29,128.80 | COM_NET=-20476"
        ),
        watch_lines=(
            "> À SURVEILLER AUJOURD'HUI :",
            "        • Baissier si le cours casse le SUPPORT 1 (7850).",
        ),
        ytd_score=86.68,
        farmgate=None,
        press_sentiment="Prudence constructive.",
        meteo_summary="Conditions normales sur les six zones.",
        meteo_impact="2/10; pluies conformes.",
        meteo_trajectory="Campagne — petite saison sèche : santé moyenne 4.8/5.",
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


def _payload(conclusion: str) -> str:
    """A narrator response as the LLM would return it.

    Built with json.dumps rather than a hand-written literal: the conclusion now
    carries newlines and apostrophes, and escaping those by hand inside a Python
    string is how this file first failed to parse.
    """
    return json.dumps(
        {
            "conclusion": conclusion,
            "eco": "Fondamentaux équilibrés.",
            "confidence_rationale": "Une normalisation invaliderait.",
        },
        ensure_ascii=False,
    )


def _narrative() -> Narrative:
    return Narrative(
        # Six lines, first marked '>' — the shape the dashboard lays out into
        # three tabs (see narrator.CONCLUSION_LINES). A shorter fixture used to
        # pass here while production shipped a single paragraph and left two tabs
        # empty; the guard now rejects both.
        conclusion=(
            "> Le marché reste porté par une offre contrainte.\n"
            "L'acheteur garde ses couvertures et laisse courir.\n"
            "Les arrivages pèsent peu à ce stade.\n"
            "La demande de broyage reste ferme sur la fenêtre.\n"
            "Le franchissement technique est net.\n"
            "Les niveaux de repli restent éloignés."
        ),
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
            _payload(
                "> Le marché reste porté.\n"
                "L'acheteur garde ses couvertures.\n"
                "Les arrivages pèsent peu.\n"
                "La demande de broyage tient.\n"
                "Le franchissement est net.\n"
                "Les niveaux de repli sont loin."
            )
        )

        narrative = narrate(_data(), client)

        assert narrative.conclusion.splitlines()[0] == "> Le marché reste porté."
        assert len(narrative.conclusion.splitlines()) == 6
        assert narrative.eco == "Fondamentaux équilibrés."

    def test_a_single_paragraph_conclusion_is_refused(self) -> None:
        """The failure that reached production and emptied two dashboard tabs.

        The prompt asked for structured lines from its first version; the model
        answered with one flowing paragraph and nothing checked. The dashboard
        cuts the analysis lines into thirds, so a single item filled the first tab
        and left "Supply & Momentum" and "Technical Outlook" reading "Aucune
        information" on a session that had plenty to say.
        """
        client = self._client(
            _payload("Le marché reste porté et l'acheteur garde ses couvertures.")
        )

        with pytest.raises(NarrationError, match="line"):
            narrate(_data(), client)

    def test_a_second_marker_is_refused(self) -> None:
        """The watch section is appended by code, never written by the model.

        A second '>' is what opens the watch block in the frontend parser. If the
        model emits one, its prose lands in the block that is supposed to carry
        pivot levels read straight from pl_derived_indicators — the one place the
        pipeline guarantees a figure was not invented.
        """
        client = self._client(
            _payload("> Titre.\nUne.\nDeux.\nTrois.\n> À SURVEILLER :\nQuatre.")
        )

        with pytest.raises(NarrationError, match="marker|'>'"):
            narrate(_data(), client)


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
    def test_carries_all_six_sections(self) -> None:
        """The brief is the whole of Compass — the podcast maps onto each section.

        Ship a thinner brief and the prompt breaks: it looks for the YTD at
        point 2, section II at point 4, the stocks at point 7 and the TO WATCH
        alerts at point 8.
        """
        brief = render_brief(_data(), _narrative())

        for header in (
            "I — SIGNAL",
            "II — LECTURE ÉDITORIALE",
            "III — ÉCO & REVUE DE PRESSE",
            "IV — WEATHER WATCH",
            "V — PHOTO TECHNIQUE",
            "VI — RECOMMANDATIONS OPÉRATIONNELLES",
        ):
            assert header in brief, f"section manquante : {header}"

    def test_figures_come_from_the_data_not_the_prose(self) -> None:
        """facts/voice split: the template owns every number."""
        brief = render_brief(_data(), _narrative())

        assert "CLOSE=8,000.00" in brief
        assert "STOCK_US=233,799.00" in brief  # stocks — podcast point 7
        assert "COM_NET=-20476" in brief
        assert "SUPPORT 1 (7850)" in brief  # TO WATCH — podcast point 8

    def test_ytd_is_present_for_the_podcast(self) -> None:
        """Point 2 of the prompt cites the YTD verbatim."""
        brief = render_brief(_data(), _narrative())

        assert "+86.68%" in brief

    def test_published_signal_is_the_fused_call(self) -> None:
        """MONITOR (judge) must show, not OPEN (regime's raw base call)."""
        brief = render_brief(_data(), _narrative())

        assert "MONITOR" in brief
        # Confidence carries its rationale — the prompt rewords that sentence.
        assert "3/5 — Une normalisation" in brief

    def test_editorial_section_names_no_mechanism(self) -> None:
        """Section II is the only track-specific part, and it stays business-facing."""
        brief = render_brief(_data(), _narrative())

        assert "Régime de marché identifié : tendance haussière établie" in brief
        # CONTRADICT → the arbitration wording, never the raw stance token.
        assert "s'oppose à la position technique" in brief
        assert "CONTRADICT" not in brief
        assert "bull" not in brief

    def test_narrative_sections_are_present(self) -> None:
        brief = render_brief(_data(), _narrative())

        assert "Le marché reste porté" in brief
        assert "Le contexte fondamental reste équilibré." in brief
        assert "Une normalisation logistique invaliderait la lecture." in brief

    def test_rationale_never_reaches_the_published_text(self) -> None:
        brief = render_brief(_data(), _narrative())

        assert "ABSTAIN" not in brief
        assert "flip bar" not in brief

    def test_english_brief_uses_english_labels(self) -> None:
        brief = render_brief(_data("en"), _narrative())

        assert "II — EDITORIAL READ" in brief
        assert "III — ECO & PRESS REVIEW" in brief
        assert "Market regime identified: established uptrend" in brief
        assert "LECTURE ÉDITORIALE" not in brief


class TestLeakGuardBySource:
    """The guard polices two sources with two different threat models.

    Origin: 2026-08-23. The press review summarised an article using the word
    « modèle » — ordinary business French — and `render_brief` refused to render,
    killing the job for a session whose decision was already computed. One list
    was applied both to our own prose and to text other agents wrote from
    external sources.
    """

    @staticmethod
    def _with(**overrides) -> BriefData:
        from dataclasses import replace

        return replace(_data(), **overrides)

    def test_our_own_prose_is_still_held_to_the_strict_list(self) -> None:
        """The guard must not have been loosened where it was designed to bite."""
        leaky = Narrative(
            conclusion=(
                "> Le modèle anticipe une hausse.\nUne.\nDeux.\nTrois.\nQuatre.\nCinq."
            ),
            eco="Contexte porteur.",
            confidence_rationale="Un repli invaliderait.",
        )

        with pytest.raises(BriefLeakError, match="conclusion"):
            render_brief(_data(), leaky)

    def test_business_french_in_the_press_review_is_not_a_leak(self) -> None:
        """The exact 2026-08-23 failure. 'modèle' in cocoa journalism is a word."""
        data = self._with(
            press_summary=(
                "Le modèle coopératif ivoirien est cité en exemple ; un "
                "algorithme de tri des fèves est testé à San-Pédro."
            )
        )

        brief = render_brief(data, _narrative())

        assert "modèle coopératif" in brief

    def test_every_third_party_field_is_covered(self) -> None:
        """Only `press_summary` was checked before; the others were blind spots."""
        for field in (
            "press_summary",
            "press_impact",
            "press_sentiment",
            "meteo_summary",
            "meteo_impact",
            "weather_body",
        ):
            data = self._with(**{field: "prob_up=0.61 sur la séance"})

            with pytest.raises(BriefLeakError, match=field):
                render_brief(data, _narrative())

    def test_the_narrow_list_still_catches_our_own_vocabulary(self) -> None:
        """Tokens that could ONLY come from us must still abort the render."""
        for token in ("regime router", "soft-gate", "o4-mini", "LightGBM"):
            data = self._with(press_summary=f"Analyse {token} du marché.")

            with pytest.raises(BriefLeakError):
                render_brief(data, _narrative())


class TestPhaseBGate:
    """The brief must not run on an evening that precedes no session.

    Origin: 2026-08-30. Scheduled daily but ungated, the job re-briefed
    ``MAX(date) FROM pl_regime_shadow`` every weekend and holiday — burning two
    LLM calls and overwriting both the published narrative and the Drive .txt
    the podcast is cut from, while logging ``SUCCESS``. It ran 5 times in 11
    days before a random word choice ("specialist") tripped the leak guard and
    made it visible. The static contract lives in
    tests/test_pipeline_phase_contract.py; this pins the behaviour.
    """

    def test_skips_without_touching_db_llm_or_drive(self):
        from unittest.mock import patch

        from scripts.regime_brief import main as m

        with (
            patch("scripts.db.phase_b_should_skip", return_value=True) as gate,
            patch("scripts.db.get_session") as get_session,
            patch.object(m, "DriveUploader") as uploader,
            patch("sys.argv", ["regime-brief", "--language", "both"]),
        ):
            rc = m.main()

        assert rc == 0
        gate.assert_called_once()
        get_session.assert_not_called()
        uploader.assert_not_called()

    def test_gate_is_consulted_before_any_work(self):
        """A False gate lets the run proceed past the short-circuit.

        --dry-run keeps this hermetic: it skips the DriveUploader branch, whose
        get_credentials_json() would otherwise raise on a machine with no Drive
        credentials (CI) before the run ever reaches the DB.
        """
        from unittest.mock import patch

        from scripts.regime_brief import main as m

        with (
            patch("scripts.db.phase_b_should_skip", return_value=False) as gate,
            patch("scripts.db.get_session", side_effect=RuntimeError("reached DB")),
            # Pins the hermeticity itself: on the --dry-run path the run must
            # never ask for Drive credentials, which is what broke this test in
            # CI (no GOOGLE_SHEETS_SCRAPER_CREDENTIALS_JSON there).
            patch.object(
                m,
                "get_credentials_json",
                side_effect=AssertionError("must not need Drive credentials"),
            ),
            patch("sys.argv", ["regime-brief", "--language", "fr", "--dry-run"]),
            pytest.raises(RuntimeError, match="reached DB"),
        ):
            m.main()

        gate.assert_called_once()

    def test_explicit_session_date_and_force_bypass_the_gate(self):
        """Operator reruns must still work on a non-eve day."""
        from datetime import date

        from scripts.db import phase_b_should_skip

        assert phase_b_should_skip(date(2026, 8, 27), force=False) is False
        assert phase_b_should_skip(None, force=True) is False


class TestOneLanguageDoesNotSilenceTheOther:
    """A failure in one language must not cost the other its episode.

    Origin: 2026-09-01, the first night the merged job ran. The EN narrative
    used the word "specialist", the leak guard refused to render the brief, and
    the exception propagated out of the loop — so the FRENCH episode was never
    produced either, although its narrative and brief were already published and
    correct. The job must still exit non-zero: the gap is loud, not contagious.
    """

    def _run(self, failing_language: str):
        from unittest.mock import MagicMock, patch

        from scripts.regime_brief import main as m

        produced: list[str] = []

        def fake_render(data, narrative):  # noqa: ANN001
            if data.language == failing_language:
                raise m.render_brief.__globals__["BriefLeakError"](
                    "conclusion leaks internals ['specialist']"
                )
            return "brief text"

        def fake_episode(data, narrative, session_date, language, *, publish):  # noqa: ANN001
            produced.append(language)
            return f"{language}.wav"

        session = MagicMock()
        with (
            patch("scripts.db.phase_b_should_skip", return_value=False),
            patch("scripts.db.get_session") as get_session,
            patch.object(m, "_resolve_version_id", return_value="v"),
            patch.object(
                m,
                "_resolve_session_date",
                return_value=__import__("datetime").date(2026, 9, 1),
            ),
            patch.object(m, "read_brief_data") as read,
            patch.object(m, "narrate", return_value=MagicMock()),
            patch.object(m, "render_brief", side_effect=fake_render),
            patch.object(m, "write_narrative"),
            patch.object(m, "_produce_episode", side_effect=fake_episode),
            patch.object(m, "DriveUploader") as uploader,
            patch.object(m, "get_credentials_json", return_value="{}"),
            patch.object(m, "get_drive_briefs_folder_id", return_value="F"),
            patch("sys.argv", ["regime-brief", "--language", "both"]),
        ):
            get_session.return_value.__enter__.return_value = session
            read.side_effect = (
                lambda session, *, session_date, algorithm_version_id, language: (
                    MagicMock(  # noqa: ARG005
                        language=language, watch_lines=()
                    )
                )
            )
            uploader.return_value.upload.return_value = "id"
            rc = m.main()
        return rc, produced

    def test_the_healthy_language_still_gets_its_episode(self):
        rc, produced = self._run(failing_language="en")
        assert produced == ["fr"], "FR must be voiced even though EN failed"

    def test_the_job_still_fails_loud(self):
        rc, _ = self._run(failing_language="en")
        assert rc == 1, "a partial run is a failure, not a success"

    def test_a_french_failure_leaves_english_alone(self):
        rc, produced = self._run(failing_language="fr")
        assert produced == ["en"]
        assert rc == 1
