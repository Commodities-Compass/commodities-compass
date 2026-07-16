"""US-1 facts/voice: the deterministic renderer + accuracy gate.

Grounded on the real 2026-07-02 production row so the rendered numbers match
what the pipeline actually produced (e.g. RSI 60.9521 -> alert threshold 58,
stock 212482 -> "212,482 tonnes").
"""

from datetime import date

import pytest

from scripts.daily_analysis.accuracy_gate import (
    AccuracyGateError,
    assert_no_hallucinated_numbers,
)
from scripts.daily_analysis.facts import FactsPayload, MetricPair, build_facts_payload
from scripts.daily_analysis.render import get_renderer
from scripts.daily_analysis.render import fr

# Real 2026-07-02 numbers (today) + 2026-07-01 (yesterday).
TODAY_ROW = {
    "close": 3746.0,
    "volume": 9442,
    "oi": 49850,
    "implied_volatility": 0.4982,
    "rsi_14d": 60.952103,
    "macd": 113.656854,
    "s1": 3686.333333,
    "s2": 3626.666667,
    "r1": 3830.333333,
    "r2": 3914.666667,
    "stock_us": 212482.0,
    "stock_eu_tonnes": 35271.0,
}
YESTERDAY_ROW = {
    "close": 3817.0,
    "volume": 10865,
    "oi": 49482,
    "implied_volatility": 0.5313,
    "rsi_14d": 59.0,
    "macd": 139.374,
    "stock_us": 211245.0,
    "stock_eu_tonnes": 35271.0,
}


@pytest.fixture
def facts() -> FactsPayload:
    return build_facts_payload(TODAY_ROW, YESTERDAY_ROW, session_date=date(2026, 7, 2))


class TestMetricPair:
    def test_direction(self):
        assert MetricPair(3746, 3817).direction == "down"
        assert MetricPair(49850, 49482).direction == "up"
        assert MetricPair(35271, 35271).direction == "flat"
        assert MetricPair(3746, None).direction is None
        assert MetricPair(None, 3817).direction is None


class TestBuildFactsPayload:
    def test_typed_extraction(self, facts: FactsPayload):
        assert facts.close.today == 3746.0
        assert facts.close.yesterday == 3817.0
        assert facts.s2 == pytest.approx(3626.6666, abs=1e-3)
        assert facts.stock_us.today == 212482.0

    def test_thousand_separated_string_coerces(self):
        p = build_facts_payload(
            {"stock_us": "212,482"},
            {"stock_us": "211,245"},
            session_date=date(2026, 7, 2),
        )
        assert p.stock_us.today == 212482.0

    def test_none_stays_none(self):
        p = build_facts_payload({}, {}, session_date=date(2026, 7, 2))
        assert p.close.today is None
        assert p.all_numbers() == []


class TestFrenchRenderer:
    def test_fact_bullets_numbers(self, facts: FactsPayload):
        body = fr.render_fact_bullets(facts)
        assert (
            "Le CLOSE s'établit à 3746, contre 3817 la veille — tendance baissière."
            in body
        )
        assert (
            "Le VOLUME ressort à 9442, contre 10865 la veille — activité en repli."
            in body
        )
        assert (
            "L'OPEN INTEREST s'inscrit à 49850, contre 49482 la veille — accumulation de positions."
            in body
        )
        assert "Le RSI est à 60.9521 — zone neutre." in body
        assert "Le MACD est à 113.657 (positif) — momentum en repli." in body
        assert "La volatilité implicite est à 0.4982, contre 0.5313 la veille" in body
        assert (
            "Le STOCK US est à 212,482 tonnes, contre 211,245 tonnes la veille" in body
        )
        assert (
            "Le STOCK EU est à 35,271 tonnes, contre 35,271 tonnes la veille — stocks stables."
            in body
        )
        # 8 bullets, each on its own indented line
        assert body.count("        • ") == 8

    def test_watch_section_pins_s1_r1_rsi(self, facts: FactsPayload):
        watch = fr.render_watch_section(facts)
        assert watch.startswith("> A SURVEILLER AUJOURD'HUI:")
        assert (
            "Baissier si le CLOSE passe sous le SUPPORT 1 (3686.33) — objectif SUPPORT 2 à 3626.67."
            in watch
        )
        assert (
            "Haussier si le CLOSE dépasse la RESISTANCE 1 (3830.33) — objectif RESISTANCE 2 à 3914.67."
            in watch
        )
        # RSI 60.95 (>=50) -> threshold round(60.95)-3 = 58, reproducing prod
        assert "Baissier si le RSI repasse sous 58 (actuellement 60.9521)" in watch
        assert watch.count("        • ") == 3

    def test_render_conclusion_assembles_headline_and_body(self, facts: FactsPayload):
        out = fr.render_conclusion(
            "Lecture Compass alignée sur MONITOR, conviction faible", facts
        )
        assert out.startswith("> Lecture Compass alignée sur MONITOR")
        assert "        • Le CLOSE" in out
        assert "> A SURVEILLER AUJOURD'HUI:" in out

    def test_registry_returns_fr(self, facts: FactsPayload):
        assert get_renderer("fr") is fr
        assert get_renderer("en") is fr  # falls back until US-3 adds EN

    def test_partial_facts_render_available_only(self):
        p = build_facts_payload(
            {"close": 3746.0, "s1": 3686.0},
            {"close": 3817.0},
            session_date=date(2026, 7, 2),
        )
        body = fr.render_fact_bullets(p)
        assert "Le CLOSE" in body
        assert "Le VOLUME" not in body  # volume absent -> no bullet
        watch = fr.render_watch_section(p)
        assert "SUPPORT 1" in watch
        assert "RESISTANCE 1" not in watch  # r1 absent


class TestAccuracyGate:
    def test_grounded_numbers_pass(self, facts: FactsPayload):
        # A headline citing real facts (close, rsi) is allowed.
        assert_no_hallucinated_numbers(
            "Repli du CLOSE à 3746, RSI à 60.9521 — lecture défensive.", facts
        )

    def test_ungrounded_number_raises(self, facts: FactsPayload):
        with pytest.raises(AccuracyGateError):
            assert_no_hallucinated_numbers(
                "Le CLOSE bondit à 9999 — cassure haussière.", facts
            )

    def test_contextual_small_integers_ignored(self, facts: FactsPayload):
        # Horizon "4 à 5 sessions" and confiance "3" must not trip the gate.
        assert_no_hallucinated_numbers(
            "Lecture Compass à horizon 4 à 5 sessions, conviction 3 sur 5.", facts
        )

    def test_rounding_tolerance(self, facts: FactsPayload):
        # 3746.00 vs grounded 3746.0 — fine within tolerance.
        assert_no_hallucinated_numbers("CLOSE à 3746.00.", facts)
