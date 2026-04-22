"""Tests for scripts.llm_utils — JSON extraction and repair from LLM responses."""

import pytest

from scripts.llm_utils import (
    _fix_invalid_escapes,
    _fix_unescaped_quotes,
    extract_json,
    fix_unescaped_newlines,
)


class TestFixUnescapedNewlines:
    def test_literal_newline_in_string(self) -> None:
        raw = '{"key": "line1\nline2"}'
        assert fix_unescaped_newlines(raw) == '{"key": "line1\\nline2"}'

    def test_literal_tab_in_string(self) -> None:
        raw = '{"key": "col1\tcol2"}'
        assert fix_unescaped_newlines(raw) == '{"key": "col1\\tcol2"}'

    def test_already_escaped_left_alone(self) -> None:
        raw = '{"key": "line1\\nline2"}'
        assert fix_unescaped_newlines(raw) == raw

    def test_newline_outside_string_untouched(self) -> None:
        raw = '{\n"key": "val"\n}'
        assert fix_unescaped_newlines(raw) == raw


class TestFixInvalidEscapes:
    def test_single_quote_escape(self) -> None:
        assert _fix_invalid_escapes("l\\'or") == "l'or"

    def test_hex_escape(self) -> None:
        result = _fix_invalid_escapes("\\x41")
        assert "\\x" not in result or result.count("\\") >= 2

    def test_bell_escape(self) -> None:
        assert _fix_invalid_escapes("\\a") == "a"

    def test_valid_escapes_untouched(self) -> None:
        text = '\\n \\r \\t \\\\ \\"'
        assert _fix_invalid_escapes(text) == text


class TestFixUnescapedQuotes:
    def test_embedded_quote_escaped(self) -> None:
        raw = '{"key": "She said "hello" to him"}'
        fixed = _fix_unescaped_quotes(raw)
        assert '"hello"' not in fixed or '\\"hello\\"' in fixed
        # Must be parseable after fix
        import json

        parsed = json.loads(fixed)
        assert "hello" in parsed["key"]

    def test_normal_json_untouched(self) -> None:
        raw = '{"key": "value", "num": 42}'
        assert _fix_unescaped_quotes(raw) == raw

    def test_nested_objects_untouched(self) -> None:
        raw = '{"a": {"b": "c"}, "d": "e"}'
        assert _fix_unescaped_quotes(raw) == raw

    def test_already_escaped_quotes(self) -> None:
        raw = '{"key": "She said \\"hello\\""}'
        assert _fix_unescaped_quotes(raw) == raw

    def test_quote_before_comma(self) -> None:
        raw = '{"a": "val", "b": "val2"}'
        assert _fix_unescaped_quotes(raw) == raw

    def test_quote_before_closing_brace(self) -> None:
        raw = '{"key": "val"}'
        assert _fix_unescaped_quotes(raw) == raw


class TestExtractJson:
    def test_clean_json(self) -> None:
        raw = '{"resume": "text", "mots_cle": "k1;k2"}'
        result = extract_json(raw)
        assert result == {"resume": "text", "mots_cle": "k1;k2"}

    def test_markdown_fences(self) -> None:
        raw = '```json\n{"key": "val"}\n```'
        result = extract_json(raw)
        assert result == {"key": "val"}

    def test_trailing_comma(self) -> None:
        raw = '{"key": "val",}'
        result = extract_json(raw)
        assert result == {"key": "val"}

    def test_literal_newline_in_string(self) -> None:
        raw = '{"key": "line1\nline2"}'
        result = extract_json(raw)
        assert result["key"] == "line1\nline2"

    def test_unclosed_brace(self) -> None:
        raw = '{"key": "val"'
        result = extract_json(raw)
        assert result == {"key": "val"}

    def test_embedded_quotes(self) -> None:
        raw = '{"summary": "The expert said "prices will rise" today"}'
        result = extract_json(raw)
        assert "prices will rise" in result["summary"]

    def test_invalid_escape_sequence(self) -> None:
        raw = '{"key": "l\'or du cacao"}'
        result = extract_json(raw)
        assert "or" in result["key"]

    def test_no_json_raises(self) -> None:
        with pytest.raises(ValueError, match="No JSON object found"):
            extract_json("just some text with no braces")

    def test_unparseable_raises(self) -> None:
        with pytest.raises(ValueError, match="Could not parse JSON"):
            extract_json("{not json at all {{{")

    def test_text_before_and_after_json(self) -> None:
        raw = 'Here is the result:\n{"key": "val"}\nDone!'
        result = extract_json(raw)
        assert result == {"key": "val"}

    def test_press_review_like_embedded_quotes(self) -> None:
        """Simulates the actual failure: French text with embedded quotes near end."""
        raw = (
            '{"resume": "Le marché du cacao reste sous pression. '
            'Les experts notent que "la récolte ivoirienne est en baisse" '
            'ce qui impacte les cours.", '
            '"mots_cle": "cacao;récolte;Côte d\'Ivoire", '
            '"impact_synthetiques": "Impact global négatif"}'
        )
        result = extract_json(raw)
        assert "récolte" in result["resume"]
        assert result["impact_synthetiques"] == "Impact global négatif"
