"""Unit tests for app.core.i18n language resolution."""

import pytest

from app.core.i18n import DEFAULT_LANGUAGE, Language, resolve_language


class TestResolveLanguage:
    def test_default_is_french(self):
        assert DEFAULT_LANGUAGE == Language.FR
        assert resolve_language(None, None) == Language.FR

    @pytest.mark.parametrize("q", ["en", "EN", " en ", "En"])
    def test_query_param_recognised(self, q):
        assert resolve_language(q, None) == Language.EN

    def test_query_param_beats_header(self):
        # Explicit user choice wins over the browser header.
        assert resolve_language("fr", "en-US,en;q=0.9") == Language.FR

    def test_unknown_query_falls_through_to_header(self):
        assert resolve_language("de", "en") == Language.EN

    def test_header_primary_tag_extracted(self):
        assert resolve_language(None, "en-GB,en;q=0.9,fr;q=0.8") == Language.EN
        assert resolve_language(None, "fr-CA,fr;q=0.9") == Language.FR

    def test_unknown_everything_falls_to_default(self):
        assert resolve_language("xx", "de-DE,zh;q=0.5") == Language.FR

    def test_empty_strings_fall_to_default(self):
        assert resolve_language("", "") == Language.FR

    def test_language_behaves_as_str(self):
        # StrEnum: value comparison + DB binding work as plain strings.
        assert Language.FR == "fr"
        assert Language.EN == "en"
        assert f"{Language.EN}" == "en"
