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
    """A full-length episode with the shape validated by ear in P0.

    Sized on the real thing: the NotebookLM episodes of 2026-08-24 and 08-25 run
    237 to 326 s, so this lands near their ~290 s middle. Varied turn length with
    genuine short reactions is what separates a conversation from two narrators
    taking turns. Every figure spoken comes from ``make_data()``.
    """
    return (
        Turn(
            "Ana",
            "Bonjour les COMPASTEURS ! Le signal Compass du jour sur le cacao Londres, horizon la prochaine séance. Marc, on commence par la performance ?",
        ),
        Turn(
            "Marc",
            "Volontiers. Le signal reste dans le vert depuis le début de l'année, et ça donne un peu de recul pour lire la séance d'aujourd'hui sans surréagir à un mouvement isolé.",
        ),
        Turn("Ana", "Et le signal du jour, alors ?"),
        Turn("Marc", "C'est un MONITOR."),
        Turn("Ana", "Donc on observe. Avec quelle conviction ?"),
        Turn(
            "Marc",
            "Modérée, trois sur cinq. Mais la direction sous-jacente reste haussière, et c'est tout l'intérêt du jour pour un acheteur physique qui doit se positionner sans se précipiter.",
        ),
        Turn(
            "Ana",
            "Alors ça, c'est intéressant. Parce que la lecture technique penchait plutôt vers la couverture, non ?",
        ),
        Turn(
            "Marc",
            "Exactement, et c'est tout l'arbitrage du jour. La lecture technique appelle à la prudence dans un contexte de volatilité élevée, mais la lecture macro ne suit pas, et c'est elle qui prend le dessus aujourd'hui.",
        ),
        Turn("Ana", "...parce que l'offre se resserre."),
        Turn(
            "Marc",
            "Voilà. Les arrivées portuaires ralentissent en Côte d'Ivoire, ce qui entretient la tension sur les disponibilités physiques depuis plusieurs semaines maintenant. Et les prévisions de récolte sont revues en baisse, ce qui vient s'ajouter à cette tension.",
        ),
        Turn(
            "Ana", "Ce ralentissement, il se lit comment concrètement sur le terrain ?"
        ),
        Turn(
            "Marc",
            "Par des volumes qui arrivent aux ports moins vite qu'attendu à ce stade de campagne. Ça ne veut pas dire que la récolte est mauvaise, ça veut dire que la marchandise met plus de temps à devenir disponible, et c'est cette différence-là que le marché price en ce moment.",
        ),
        Turn("Ana", "Côté éco, il y a autre chose à retenir ?"),
        Turn(
            "Marc",
            "La demande chocolat tient, et c'est le point qui empêche la tension de se dénouer toute seule. Tant que les arrivages ne repartent pas et que la demande reste là, le marché reste sur cette asymétrie, avec un vendeur qui n'a pas de raison de brader.",
        ),
        Turn("Ana", "Et la météo dans les origines ?"),
        Turn(
            "Marc",
            "Favorable en Côte d'Ivoire et au Ghana. C'est justement ce qui pourrait limiter les perturbations à court terme, donc c'est le paramètre à surveiller de près sur les prochaines séances.",
        ),
        Turn(
            "Ana",
            "C'est un peu contre-intuitif, non ? Une bonne météo qui devient un risque.",
        ),
        Turn(
            "Marc",
            "C'est tout le paradoxe du moment. Une météo favorable, dans un marché tendu par la logistique, ça veut dire que la marchandise finira par arriver. Donc oui, la bonne nouvelle agronomique est le principal facteur de détente des prix.",
        ),
        Turn("Ana", "On passe aux niveaux. Qu'est-ce qui compte demain ?"),
        Turn(
            "Marc",
            "La clôture s'est faite à 4238, contre 4201 la veille. Volume à 3625 lots, positions ouvertes à 36333. Deux niveaux structurent la séance : baissier si le cours casse le support à 4 160,67, haussier s'il franchit la résistance à 4 315,67.",
        ),
        Turn("Ana", "Les positions ouvertes, elles nous disent quelque chose ?"),
        Turn(
            "Marc",
            "Elles restent étoffées, ce qui veut dire que le marché ne se vide pas. On n'est pas sur un mouvement de sortie, on est sur une hésitation, et c'est cohérent avec le MONITOR du jour.",
        ),
        Turn("Ana", "Concrètement, pour un acheteur physique, on fait quoi ?"),
        Turn(
            "Marc",
            "On ne tranche pas, on surveille. On garde ses couvertures existantes, on ne se renforce pas tant que la résistance n'est pas franchie, et on reste prêt à ajuster rapidement si le support cède en séance.",
        ),
        Turn("Ana", "Et si on est déjà couvert ?"),
        Turn(
            "Marc",
            "On ne touche à rien. Une journée d'observation ne justifie pas de payer un aller-retour, surtout dans un marché où la volatilité reste élevée.",
        ),
        Turn("Ana", "Et ce qui remettrait tout ça en cause ?"),
        Turn(
            "Marc",
            "Une reprise rapide des arrivages portuaires en Côte d'Ivoire. Avec une météo qui reste favorable, ça détendrait la tension très vite et ça pèserait sur les prix. C'est le scénario à garder en tête.",
        ),
        Turn(
            "Ana",
            "Message reçu. On se retrouve demain pour voir si les arrivages ont bougé.",
        ),
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

    def test_rejects_a_second_decision_pushed_as_a_call(self):
        turns = good_turns() + (
            Turn("Ana", "On passe en HEDGE alors ?"),
            Turn("Marc", "Oui, HEDGE. À demain les COMPASTEURS !"),
        )
        with pytest.raises(ScriptError, match="ambiguous"):
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
    def test_rejects_uniform_turn_lengths(self):
        body = "Le marché reste tendu sur les disponibilités physiques aujourd'hui."
        turns = (
            (Turn("Ana", "Bonjour les COMPASTEURS ! " + body),)
            + tuple(Turn("Marc" if i % 2 else "Ana", body) for i in range(12))
            + (Turn("Marc", "À demain les COMPASTEURS ! " + body),)
        )
        with pytest.raises(ScriptError, match="too uniform"):
            validate(script(turns), make_data(), NARRATIVE)

    def test_rejects_too_few_turns(self):
        turns = (
            Turn("Ana", "Bonjour les COMPASTEURS ! On est en MONITOR aujourd'hui."),
            Turn("Marc", "À demain les COMPASTEURS !"),
        )
        with pytest.raises(ScriptError, match="not a conversation"):
            validate(script(turns), make_data(), NARRATIVE)

    def test_rejects_an_episode_with_no_short_reaction(self):
        long = "Le marché reste tendu sur les disponibilités physiques et les arrivées ralentissent nettement."
        turns = (
            (
                Turn(
                    "Ana",
                    "Bonjour les COMPASTEURS ! " + long + " Nous sommes en MONITOR.",
                ),
            )
            + tuple(
                Turn(
                    "Marc" if i % 2 else "Ana",
                    long
                    + f" Point numéro {i} développé longuement ici même."[: 60 + i * 3],
                )
                for i in range(10)
            )
            + (Turn("Marc", "À demain les COMPASTEURS ! " + long),)
        )
        with pytest.raises(ScriptError, match="short interjection|too uniform"):
            validate(script(turns), make_data(), NARRATIVE)


class TestDuration:
    def test_rejects_an_episode_longer_than_the_promise(self):
        filler = Turn("Marc", "Le marché reste tendu. " * 40)
        turns = good_turns()[:-1] + (filler,) * 6 + (good_turns()[-1],)
        with pytest.raises(ScriptError, match="outside"):
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
