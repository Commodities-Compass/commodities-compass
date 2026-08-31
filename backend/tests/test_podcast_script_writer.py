"""The contract between the served decision and what the episode says out loud.

Until now nothing verified the audio: the NotebookLM prompt asked for these
guarantees in prose and hoped. Each test here is one of those prompt lines,
turned into something that fails.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import cast

import pytest

from scripts._shared.llm_client import LLMClient
from scripts.podcast_audio.script_writer import (
    PodcastScript,
    ScriptError,
    Turn,
    assess_quality,
    source_figures,
    validate,
    write_script,
)
from scripts.regime_brief.db_reader import BriefData, JudgeCall, RegimeCall, Technicals
from scripts.regime_brief.narrator import Narrative


def make_data(language: str = "fr", decision: str = "MONITOR") -> BriefData:
    return BriefData(
        session_date=date(2026, 8, 24),
        target_date=date(2026, 8, 25),
        contract_id=uuid.uuid4(),
        contract_code="CAZ26",
        language=language,
        regime=RegimeCall(
            decision="HEDGE", regime="trend", specialist="s1", prob_up=0.52
        ),
        judge=JudgeCall(
            final_decision=decision,
            direction="haussière",
            stance="confirms",
            confidence=3,
            is_anomaly=False,
            changed=True,
            drift_summary=None,
            key_risk=None,
            disconfirming_case=None,
            evidence=(),
        ),
        technicals=Technicals(
            close=Decimal("4238"),
            close_prev=Decimal("4201"),
            volume=3625,
            oi=36333,
            rsi_14d=Decimal("54.2"),
            s1=Decimal("4160.67"),
            r1=Decimal("4315.67"),
        ),
        technicals_snapshot="Clôture 4238, volume 3625, positions ouvertes 36333.",
        watch_lines=("SUPPORT 1 (4 160.67)", "RÉSISTANCE 1 (4 315.67)"),
        ytd_score=8.3,
        farmgate=None,
        press_summary="Les arrivées portuaires ralentissent en Côte d'Ivoire.",
        press_impact="Tension sur les disponibilités.",
        press_sentiment="neutre",
        meteo_summary="Conditions favorables.",
        meteo_impact="Faible",
        meteo_trajectory="stable",
        weather_body="Météo favorable en Côte d'Ivoire et au Ghana.",
    )


NARRATIVE = Narrative(
    conclusion="> Signal MONITOR avec une conviction modérée.",
    eco="L'offre se resserre, les arrivées ralentissent.",
    confidence_rationale="Une reprise des arrivages détendrait la tension.",
)


def good_turns() -> tuple[Turn, ...]:
    """A full-length episode with the shape measured on the real thing.

    Sized and balanced on three NotebookLM episodes (2026-08-24 FR/EN, 08-25 FR):
    237 to 326 s, the dominant voice carrying 53-57 % of the characters, both
    speakers averaging 83 to 140 characters a turn. Ana is a co-analyst, not a
    host: she brings facts too, and either of them may ask. Every figure spoken
    here comes from ``make_data()``.
    """
    return (
        Turn(
            "Ana",
            "Bonjour les COMPASTEURS ! Le signal Compass du jour sur le cacao Londres, horizon la prochaine séance. Et on démarre sur un MONITOR, conviction modérée.",
        ),
        Turn(
            "Marc",
            "Modérée, mais avec une direction sous-jacente haussière, ce qui change la lecture pour un acheteur physique.",
        ),
        Turn(
            "Ana",
            "Parce que la lecture technique, elle, appelait plutôt à la couverture dans un contexte de volatilité élevée.",
        ),
        Turn(
            "Marc",
            "Et c'est tout l'arbitrage du jour : la lecture macro ne la suit pas, et c'est elle qui prend le dessus.",
        ),
        Turn(
            "Ana",
            "Ce qui se lit surtout du côté de l'offre. Les arrivées portuaires ralentissent en Côte d'Ivoire depuis plusieurs semaines, et les prévisions de récolte sont revues en baisse.",
        ),
        Turn(
            "Marc",
            "Ce ralentissement ne dit pas que la récolte est mauvaise, il dit que la marchandise met plus de temps à devenir disponible.",
        ),
        Turn("Ana", "Ah, c'est ça."),
        Turn("Marc", "Et c'est cette différence-là que le marché price."),
        Turn(
            "Marc",
            "Côté demande, le chocolat tient. C'est ce qui empêche la tension de se dénouer toute seule, parce qu'il n'y a pas de vendeur pressé en face.",
        ),
        Turn(
            "Ana",
            "Donc une asymétrie qui dure tant que les deux jambes restent en place.",
        ),
        Turn(
            "Marc",
            "Voyons la météo, parce qu'elle est contre-intuitive aujourd'hui. Côte d'Ivoire et Ghana, conditions favorables.",
        ),
        Turn(
            "Ana",
            "Contre-intuitive parce qu'une bonne météo, dans un marché tendu par la logistique, veut dire que la marchandise finira par arriver.",
        ),
        Turn(
            "Marc",
            "C'est ça. La bonne nouvelle agronomique est le principal facteur de détente des prix, ce qui est rarement le cas.",
        ),
        Turn(
            "Ana",
            "Passons aux niveaux. La clôture s'est faite à 4238, contre 4201 la veille, sur un volume de 3625 lots.",
        ),
        Turn(
            "Marc",
            "Et les positions ouvertes tiennent à 36333, ce qui veut dire que le marché ne se vide pas.",
        ),
        Turn("Ana", "Pas une sortie, alors."),
        Turn(
            "Marc",
            "Une hésitation, plutôt. C'est cohérent avec le MONITOR : deux niveaux structurent la séance, un support à 4 160,67 et une résistance à 4 315,67.",
        ),
        Turn(
            "Ana",
            "Concrètement, on garde ses couvertures existantes, on ne se renforce pas tant que la résistance n'est pas franchie.",
        ),
        Turn(
            "Marc",
            "Et on reste prêt à ajuster rapidement si le support cède en séance.",
        ),
        Turn("Ana", "Et si on est déjà couvert, on ne touche à rien ?"),
        Turn(
            "Marc",
            "On ne touche à rien. Une journée d'observation ne justifie pas de payer un aller-retour dans un marché aussi volatil.",
        ),
        Turn(
            "Ana",
            "Reste ce qui remettrait tout ça en cause : une reprise rapide des arrivages portuaires ivoiriens.",
        ),
        Turn(
            "Marc",
            "Avec une météo qui reste favorable, ça détendrait la tension très vite et ça pèserait sur les prix. C'est le scénario à garder en tête.",
        ),
        Turn(
            "Ana",
            "Un mot sur la performance avant de fermer : le signal reste dans le vert depuis le début de l'année, ce qui donne un peu de recul pour lire la séance sans surréagir.",
        ),
        Turn(
            "Marc",
            "C'est important de le dire, parce qu'un MONITOR isolé peut donner l'impression d'une hésitation permanente, alors que c'est une posture de gestion assumée.",
        ),
        Turn(
            "Ana",
            "Et côté presse, la traçabilité ivoirienne revient régulièrement dans les commentaires depuis deux semaines.",
        ),
        Turn(
            "Marc",
            "Elle ajoute une friction administrative aux expéditions de début de campagne, ce qui se cumule avec le retard portuaire au lieu de le compenser.",
        ),
        Turn("Ana", "Deux causes, même sens."),
        Turn(
            "Marc",
            "Et c'est ce qui rend la détente moins probable à court terme qu'une simple lecture météo le suggérerait.",
        ),
        Turn(
            "Ana",
            "Pour finir sur le Ghana, la situation y est plus calme que côté ivoirien, sans signal particulier à retenir aujourd'hui.",
        ),
        Turn(
            "Marc",
            "Ce qui est en soi une information : quand une des deux origines ne bouge pas, la tension vient bien de l'autre.",
        ),
        Turn(
            "Ana",
            "Dernier point avant de fermer : la volatilité implicite reste élevée, ce qui renchérit mécaniquement toute couverture optionnelle prise aujourd'hui.",
        ),
        Turn(
            "Marc",
            "D'où la recommandation de ne pas se renforcer sans signal : payer cher une protection pour un marché qui hésite, c'est le pire moment de cycle.",
        ),
        Turn("Ana", "Une dernière chose ?"),
        Turn(
            "Marc",
            "Oui : ne pas confondre une séance d'observation avec une absence de direction. Le biais reste haussier, et si les arrivages ne repartent pas d'ici la fin de semaine, c'est cette lecture-là qui se confirmera d'elle-même, sans qu'on ait eu à parier dessus.",
        ),
        Turn("Ana", "Bien noté."),
        Turn("Ana", "On se retrouve demain pour voir si les arrivages ont bougé."),
        Turn("Marc", "À demain les COMPASTEURS !"),
    )


def script(turns=None, language="fr") -> PodcastScript:
    return PodcastScript(language=language, turns=turns or good_turns())


class TestValidScript:
    def test_a_well_formed_episode_passes(self):
        validate(script(), make_data(), NARRATIVE)

    def test_markup_turns_are_speech_normalised(self):
        turns = (Turn("Ana", "> le SUPPORT 1 (4 160.67)"),)
        out = PodcastScript("fr", turns).as_markup_turns()
        assert out[0]["text"] == "le SUPPORT 1 (4 160,67)"

    def test_source_figures_include_the_narrative_and_the_technicals(self):
        figures = source_figures(make_data(), NARRATIVE)
        assert {"3625", "36333", "416067", "431567"} <= figures


class TestTheFormulas:
    def test_rejects_a_missing_opening(self):
        turns = (Turn("Ana", "Salut à tous, on démarre."),) + good_turns()[1:]
        with pytest.raises(ScriptError, match="must open"):
            validate(script(turns), make_data(), NARRATIVE)

    def test_rejects_a_missing_closing(self):
        turns = good_turns()[:-1] + (Turn("Marc", "Bonne journée."),)
        with pytest.raises(ScriptError, match="must close"):
            validate(script(turns), make_data(), NARRATIVE)


class TestTheDecision:
    def test_rejects_an_episode_that_never_announces_it(self):
        turns = tuple(
            Turn(t.speaker, t.text.replace("MONITOR", "prudence")) for t in good_turns()
        )
        with pytest.raises(ScriptError, match="never announces"):
            validate(script(turns), make_data(), NARRATIVE)

    def test_rejects_a_third_call_pushed_at_the_listener(self):
        # OPEN is neither the served call (MONITOR) nor the technical base
        # (HEDGE), so pushing it twice competes with the published decision.
        turns = good_turns() + (
            Turn("Ana", "On passe en OPEN alors ?"),
            Turn("Marc", "Oui, OPEN. À demain les COMPASTEURS !"),
        )
        with pytest.raises(ScriptError, match="pushes 'OPEN'"):
            validate(script(turns), make_data(), NARRATIVE)

    def test_allows_the_technical_base_to_be_named_freely(self):
        # The editorial section exists to contrast the technical read with the
        # macro overlay; the served prose itself says "la base technique HEDGE".
        # Forbidding the word would forbid the heart of the episode.
        turns = good_turns() + (
            Turn("Ana", "Et la lecture technique disait quoi ?"),
            Turn("Marc", "Elle disait HEDGE, dans un contexte de volatilité élevée."),
            Turn(
                "Ana",
                "Donc HEDGE côté technique, MONITOR une fois le macro pris en compte.",
            ),
            Turn("Marc", "À demain les COMPASTEURS !"),
        )
        validate(script(turns), make_data(), NARRATIVE)


class TestTheMachineryStaysHidden:
    @pytest.mark.parametrize(
        "leak",
        [
            "notre modèle indique",
            "le spécialiste macro dit",
            "la probabilité est de",
            "l'intelligence artificielle a vu",
            "le z-score est élevé",
        ],
    )
    def test_rejects_any_mention_of_the_engine(self, leak):
        turns = good_turns()[:-1] + (
            Turn("Marc", f"{leak}. À demain les COMPASTEURS !"),
        )
        with pytest.raises(ScriptError, match="names the machinery"):
            validate(script(turns), make_data(), NARRATIVE)


class TestInventedFigures:
    def test_rejects_a_price_absent_from_the_session(self):
        turns = good_turns()[:-1] + (
            Turn("Marc", "La clôture était à 9999. À demain les COMPASTEURS !"),
        )
        with pytest.raises(ScriptError, match="absent from the session data"):
            validate(script(turns), make_data(), NARRATIVE)

    def test_accepts_a_figure_written_with_a_thousands_space(self):
        turns = good_turns()[:-1] + (
            Turn("Marc", "Positions ouvertes 36 333. À demain les COMPASTEURS !"),
        )
        validate(script(turns), make_data(), NARRATIVE)


class TestConversationalShape:
    """Texture is measured, never gated: it does not stop an episode shipping."""

    @staticmethod
    def _flattened() -> tuple[Turn, ...]:
        """A valid episode whose middle turns are all the same length."""
        body = (
            "Le marché reste tendu sur les disponibilités physiques, et les "
            "opérateurs surveillent la moindre inflexion des arrivages."
        )
        middle = tuple(Turn("Marc" if i % 2 else "Ana", body) for i in range(40))
        return (good_turns()[0],) + middle + (good_turns()[-1],)

    def test_uniform_turn_lengths_are_reported_not_blocked(self):
        turns = self._flattened()
        validate(script(turns), make_data(), NARRATIVE)  # style never blocks
        assert any("uniform" in w for w in assess_quality(script(turns)).warnings)

    def test_an_imbalanced_episode_is_reported_not_blocked(self):
        long = (
            "Le marché reste tendu et les arrivées ralentissent nettement cette "
            "semaine encore, ce qui entretient la pression sur les disponibilités."
        )
        turns = (
            (good_turns()[0],)
            + tuple(Turn("Marc", long) for _ in range(24))
            + (Turn("Ana", "Oui."), good_turns()[-1])
        )
        validate(script(turns), make_data(), NARRATIVE)
        report = assess_quality(script(turns))
        assert any("carries" in w for w in report.warnings)

    def test_a_balanced_varied_episode_reports_nothing(self):
        assert assess_quality(script()).clean


class TestDuration:
    def test_an_episode_past_the_band_is_reported_not_blocked(self):
        pad = "Le marché reste tendu sur les disponibilités physiques. " * 12
        turns = (
            good_turns()[:-1]
            + tuple(Turn("Ana" if i % 2 else "Marc", pad) for i in range(4))
            + (good_turns()[-1],)
        )
        validate(script(turns), make_data(), NARRATIVE)
        assert any("band" in w for w in assess_quality(script(turns)).warnings)

    def test_a_runaway_generation_is_still_blocked(self):
        pad = "Le marché reste tendu sur les disponibilités physiques. " * 60
        turns = (
            good_turns()[:-1]
            + tuple(Turn("Ana" if i % 2 else "Marc", pad) for i in range(4))
            + (good_turns()[-1],)
        )
        with pytest.raises(ScriptError, match="sanity bounds"):
            validate(script(turns), make_data(), NARRATIVE)


@dataclass
class _FakeResponse:
    """Shaped like LLMResponse — only what write_script reads."""

    raw_text: str
    model: str = "fake"
    output_tokens: int = 1


class _FakeClient:
    """Duck-types LLMClient so no test ever reaches the API."""

    def __init__(self, raw_text: str) -> None:
        self._raw_text = raw_text

    def call(self, prompt: str, **_: object) -> _FakeResponse:
        return _FakeResponse(raw_text=self._raw_text)


def _client_returning(payload: dict) -> LLMClient:
    return cast(LLMClient, _FakeClient(json.dumps(payload)))


class TestWriteScript:
    def test_parses_and_validates_a_model_response(self):
        client = _client_returning(
            {"turns": [{"speaker": t.speaker, "text": t.text} for t in good_turns()]}
        )
        out = write_script(make_data(), NARRATIVE, client)
        assert len(out.turns) == len(good_turns())
        assert out.language == "fr"

    def test_refuses_a_response_with_no_turns(self):
        with pytest.raises(ScriptError, match="no turns"):
            write_script(make_data(), NARRATIVE, _client_returning({"turns": []}))


class TestOpenInterestIsNotADecision:
    """ "open interest" is the standard English term for OI and contains "open".

    Live false positive, 2026-08-26: every English episode was refused because a
    case-insensitive substring count read the phrase as a competing OPEN call.
    """

    def test_english_open_interest_prose_is_not_a_competing_call(self):
        turns = good_turns()[:-1] + (
            Turn("Ana", "Volume and open interest — anything unusual?"),
            Turn(
                "Marc",
                "Volume came in at 3625 with open interest at 36333, both steady.",
            ),
            Turn("Marc", "À demain les COMPASTEURS !"),
        )
        validate(script(turns), make_data(), NARRATIVE)

    def test_the_signal_name_in_capitals_is_still_caught(self):
        turns = good_turns()[:-1] + (
            Turn("Ana", "On bascule en OPEN ?"),
            Turn("Marc", "Oui, OPEN. À demain les COMPASTEURS !"),
        )
        with pytest.raises(ScriptError, match="pushes 'OPEN'"):
            validate(script(turns), make_data(), NARRATIVE)


class TestAcknowledgementTics:
    """Three identical agreement words in one episode is a generator, not a person."""

    def test_rejects_a_pathological_repeat(self):
        # Spread over both voices so this tests the tic, not the balance.
        turns = good_turns()[:-1] + (
            Turn("Marc", "Exactement."),
            Turn("Ana", "Exactement, et sur la météo ?"),
            Turn("Marc", "Exactement, c'est le point à suivre."),
            Turn("Ana", "Exactement, on surveille."),
            Turn("Marc", "Exactement, on ne bouge pas."),
            Turn("Marc", "À demain les COMPASTEURS !"),
        )
        validate(script(turns), make_data(), NARRATIVE)
        assert any("tics" in w for w in assess_quality(script(turns)).warnings)

    def test_allows_a_conversational_amount(self):
        # good_turns() already carries one "Exactement"; a second is conversation.
        turns = good_turns()[:-1] + (
            Turn("Ana", "Et sur la météo ?"),
            Turn("Marc", "Exactement, c'est le point à suivre."),
            Turn("Marc", "À demain les COMPASTEURS !"),
        )
        validate(script(turns), make_data(), NARRATIVE)
