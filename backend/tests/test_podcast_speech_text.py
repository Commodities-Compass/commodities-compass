"""The normaliser and the lexicon — the P0 defects, frozen as tests."""

from __future__ import annotations

import pytest

from scripts.podcast_audio.speech_text import (
    custom_pronunciations,
    normalize_for_speech,
    numeric_tokens,
)

# Verbatim from pl_indicator_daily.conclusion, 2026-08-24, the row that produced
# the first listening pack. Every defect heard in it is in these four lines.
REAL_CONCLUSION = (
    "> Signal MONITOR avec une conviction modérée et une direction haussière.\n"
    "> À SURVEILLER AUJOURD'HUI :\n"
    "        • Baissier si le cours casse le SUPPORT 1 (4 160.67).\n"
    "        • Haussier si le cours franchit la RÉSISTANCE 1 (4 315.67)."
)


class TestNormalizeForSpeech:
    def test_strips_markdown_blockquote(self):
        assert normalize_for_speech("> Signal MONITOR") == "Signal MONITOR"

    def test_strips_bullets(self):
        assert normalize_for_speech("• Baissier si") == "Baissier si"
        assert normalize_for_speech("- Haussier si") == "Haussier si"

    def test_rewrites_the_decimal_point_as_a_comma(self):
        assert "4 160,67" in normalize_for_speech("le SUPPORT 1 (4 160.67)")

    def test_leaves_a_sentence_final_period_alone(self):
        assert normalize_for_speech("Le cours casse. Puis rebondit.").endswith(
            "rebondit."
        )

    def test_collapses_newlines_and_runs_of_spaces(self):
        assert normalize_for_speech("a\n\n  b   c") == "a b c"

    def test_the_real_row_comes_out_speakable(self):
        out = normalize_for_speech(REAL_CONCLUSION)
        assert ">" not in out, "a spoken '>' was the loudest defect of pack 1"
        assert "•" not in out
        assert "4 160,67" in out and "4 315,67" in out
        assert "4 160.67" not in out

    def test_is_idempotent(self):
        once = normalize_for_speech(REAL_CONCLUSION)
        assert normalize_for_speech(once) == once


class TestNumericTokens:
    @pytest.mark.parametrize("written", ["2 438", "2438", "2,438"])
    def test_the_same_figure_written_three_ways_matches(self, written):
        assert numeric_tokens(written) == {"2438"}

    def test_ignores_structural_short_numbers(self):
        # S1, R1 and a confidence out of 5 are language, not data.
        assert numeric_tokens("le SUPPORT 1, la RÉSISTANCE 1, confiance 4/5") == set()

    def test_extracts_every_figure_of_the_real_row(self):
        # Both the full-precision form and the integer part: the validator's job
        # is to catch invention, and a speaker rounding is not invention.
        assert numeric_tokens(normalize_for_speech(REAL_CONCLUSION)) == {
            "4160",
            "416067",
            "4315",
            "431567",
        }

    def test_an_invented_price_does_not_match_the_source(self):
        source = numeric_tokens("clôture à 4 160,67")
        spoken = numeric_tokens("clôture à 4 200,00")
        assert not spoken <= source


class TestLexicon:
    def test_payload_has_the_shape_gemini_tts_accepts(self):
        payload = custom_pronunciations()
        assert set(payload) == {"pronunciations"}
        for entry in payload["pronunciations"]:
            assert set(entry) == {"phrase", "phoneticEncoding", "pronunciation"}
            assert entry["phoneticEncoding"] == "PHONETIC_ENCODING_IPA"
            assert entry["pronunciation"].strip()

    def test_covers_compasteurs(self):
        phrases = {e["phrase"] for e in custom_pronunciations()["pronunciations"]}
        assert "Compasteurs" in phrases

    def test_phrases_are_unique_case_insensitively(self):
        # The API rejects the whole request with INVALID_ARGUMENT otherwise —
        # "Compasteurs" and "COMPASTEURS" together killed the first live run.
        phrases = [
            e["phrase"].lower() for e in custom_pronunciations()["pronunciations"]
        ]
        assert len(phrases) == len(set(phrases))


class TestNumericTokensSeparation:
    """A separator groups thousands only when three digits follow it.

    A looser character class glued neighbouring figures into one — "4238 4201"
    became a single eight-digit number, so every genuine figure in an episode
    then failed the invented-figure check.
    """

    def test_two_figures_separated_by_a_space_stay_separate(self):
        assert numeric_tokens("clôture 4238 contre 4201") == {"4238", "4201"}

    def test_adjacent_figures_with_no_word_between_stay_separate(self):
        assert numeric_tokens("4238 4201 3625 36333") == {
            "4238",
            "4201",
            "3625",
            "36333",
        }

    def test_a_thousands_space_still_groups(self):
        assert numeric_tokens("positions ouvertes 36 333") == {"36333"}

    def test_a_grouped_decimal_survives(self):
        assert numeric_tokens("support à 4 160,67") == {"4160", "416067"}

    def test_a_percentage_is_too_short_to_assert_on(self):
        assert numeric_tokens("en repli de 1,4 %") == set()


class TestSpokenMatchesStored:
    """The database writes for the eye, the episode speaks for the ear.

    Every case below was a live false positive on 2026-08-26: the generator was
    refused three runs running for quoting a stock figure it had read correctly
    out of `technicals_snapshot` (`STOCK_US=236,110.00`).
    """

    def test_a_zero_fraction_is_formatting_not_precision(self):
        assert numeric_tokens("236 110 tonnes") <= numeric_tokens("STOCK_US=236,110.00")

    def test_a_speaker_may_round_a_real_fraction_away(self):
        # STOCK_EU=40,858.92 spoken as "40 858 tonnes" — at that scale the
        # decimal carries nothing, and rounding it off is correct speech.
        assert numeric_tokens("40 858 tonnes") <= numeric_tokens("STOCK_EU=40,858.92")

    def test_the_full_precision_form_still_matches(self):
        # A price level keeps its decimals, and both spellings must resolve.
        assert numeric_tokens("4 160,67") <= numeric_tokens("SUPPORT 1 (4 160.67)")

    def test_an_actually_invented_figure_is_still_caught(self):
        assert not numeric_tokens("9 999 tonnes") <= numeric_tokens(
            "STOCK_US=236,110.00"
        )


class TestSeparatorMeansOppositeThingsPerLocale:
    """`,` and `.` swap roles between French and English.

    Live false positive, 2026-08-26: the English episode quoted `236,110 tonnes`
    straight out of `technicals_snapshot` and was refused, because the thousands
    comma was read as a decimal point and produced a stray `236`.
    """

    def test_a_french_decimal_comma_keeps_two_precisions(self):
        assert numeric_tokens("4 160,67") == {"4160", "416067"}

    def test_an_english_thousands_comma_is_one_number(self):
        assert numeric_tokens("236,110") == {"236110"}

    def test_the_stored_form_matches_both_spoken_forms(self):
        source = numeric_tokens("STOCK_US=236,110.00 | STOCK_EU=40,858.92 | OI=23806")
        assert numeric_tokens("236 110 et 40 858 tonnes, OI 23 806") <= source
        assert numeric_tokens("236,110 and 40,858 tonnes, OI 23,806") <= source

    def test_a_three_digit_group_never_becomes_a_fraction(self):
        # "236 point 110" is what broke it; the group is thousands, not decimals.
        assert "236" not in numeric_tokens("236,110")
