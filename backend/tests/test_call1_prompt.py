"""US-3b-ii: Call #1 (macro/weather) prompt is language-parametric.

The ``eco`` field is native-language prose (D3) — the EN prompt asks for a fresh
English summary, never a translation of the FR one. The JSON output shape and
the score scale stay identical across languages so the parser + numeric pipeline
are language-agnostic.
"""

from scripts.daily_analysis.prompts import build_call1_prompt


class TestCall1PromptLanguage:
    def test_fr_default_is_french(self):
        p = build_call1_prompt("news", "meteo", "hist")
        assert "expert en analyse du marché du cacao" in p
        assert "HAUSSIÈRES" in p
        # Context injected, not the placeholder.
        assert "news" in p

    def test_en_is_native_english(self):
        p = build_call1_prompt("news", "meteo", "hist", language="en")
        assert "expert cocoa-market analyst" in p
        assert "BULLISH" in p
        assert "BEARISH" in p
        # No French scoring vocabulary leaks into the EN prompt.
        assert "HAUSSIÈRES" not in p
        assert "Facteurs HAUSSIERS" not in p

    def test_output_json_shape_identical_across_languages(self):
        fr = build_call1_prompt("", "", "", language="fr")
        en = build_call1_prompt("", "", "", language="en")
        for p in (fr, en):
            assert '"date"' in p
            assert '"macroeco_bonus"' in p
            assert '"eco"' in p
        # Same continuous score scale in both.
        assert "-0.10" in en and "+0.10" in en

    def test_empty_context_uses_language_specific_placeholder(self):
        fr = build_call1_prompt("", "", "", language="fr")
        en = build_call1_prompt("", "", "", language="en")
        assert "(aucune actualité disponible)" in fr
        assert "(no news available)" in en

    def test_unknown_language_falls_back_to_french(self):
        p = build_call1_prompt("", "", "", language="xx")
        assert "expert en analyse du marché du cacao" in p
