"""US-1c: Call #2 voice prompts request a qualitative headline only — never the
numbered blob (that is rendered deterministically by the engine)."""

from scripts.daily_analysis.voice_prompts import (
    build_call2_voice_prompt,
    build_call2_voice_prompt_ensemble,
)

_VARS = [
    "CLOSE",
    "HIGH",
    "LOW",
    "VOL",
    "OI",
    "VOLIMP",
    "STOCKUS",
    "STOCKEU",
    "COMNET",
    "R1",
    "PIVOT",
    "S1",
    "EMA9",
    "EMA21",
    "MACD",
    "SIGN",
    "RSI14",
    "%K",
    "%D",
    "ATR",
    "BSUP",
    "BBINF",
]
_TODAY = {f"{v}TOD": "100" for v in _VARS}
_YDAY = {f"{v}YES": "99" for v in _VARS}


class _Ens:
    decision_wrapped = "HEDGE"
    net_score = -0.8
    n_committed_specialists = 12
    macro_direction = -1
    macro_surprise = 0.3
    macro_half_life_days = 5


class TestLegacyVoicePrompt:
    def test_requests_headline_not_numbered_conclusion(self):
        p = build_call2_voice_prompt(_TODAY, _YDAY, 1.5, "MONITOR")
        assert "HEADLINE" in p
        assert '"headline"' in p  # JSON output field
        assert "A SURVEILLER" not in p  # engine renders it; the LLM must not
        assert '"conclusion"' not in p

    def test_injects_decision_and_technicals(self):
        p = build_call2_voice_prompt(_TODAY, _YDAY, 1.5, "MONITOR")
        assert "MONITOR" in p
        assert "CLOSE : 100" in p


class TestEnsembleVoicePrompt:
    def test_pins_decision_and_keeps_forbidden_vocab(self):
        p = build_call2_voice_prompt_ensemble(_TODAY, _YDAY, _Ens())
        assert "HEDGE" in p  # decision pinned
        assert "VOCABULAIRE STRICTEMENT INTERDIT" in p
        assert '"confiance_rationale"' in p
        assert "A SURVEILLER" not in p

    def test_conviction_qualitative_injected(self):
        # |net_score|=0.8, n_committed=12 -> adhesion ~0.74 -> "forte"
        p = build_call2_voice_prompt_ensemble(_TODAY, _YDAY, _Ens())
        assert "Conviction Compass intrinsèque : forte" in p


class TestEnglishVoicePrompt:
    def test_legacy_en_requests_headline(self):
        p = build_call2_voice_prompt(_TODAY, _YDAY, 1.5, "MONITOR", language="en")
        assert '"headline"' in p
        assert "editorial read" in p  # EN task
        assert "MONITOR" in p
        assert "A SURVEILLER" not in p

    def test_ensemble_en_pins_decision_and_forbidden_vocab(self):
        p = build_call2_voice_prompt_ensemble(_TODAY, _YDAY, _Ens(), language="en")
        assert "HEDGE" in p  # decision pinned
        assert "STRICTLY FORBIDDEN VOCABULARY" in p
        assert '"confiance_rationale"' in p  # JSON field name stays French

    def test_ensemble_en_conviction_label_translated(self):
        # forte -> EN "strong"
        p = build_call2_voice_prompt_ensemble(_TODAY, _YDAY, _Ens(), language="en")
        assert "Intrinsic Compass conviction: strong" in p
