"""Behavioural cover for the guards added when scripts/ came under pyright.

`scripts/` was excluded from type checking on 2026-03-09 and everything built
since — regime, judge, watchai, publish-session — was never checked. Closing the
66 errors it hid changed real behaviour in a handful of places, and the modules
concerned sit at 0-31 % coverage. These tests pin the changed behaviour so the
merge rests on evidence rather than on the full suite passing elsewhere.
"""

from __future__ import annotations

import pytest

from scripts.barchart_scraper.validator import DataValidator


class TestZeroIsNotAbsent:
    """The one genuine semantic change of the pass.

    The logical checks used to be guarded by `if data.get("high") and ...`, so a
    price of exactly 0.0 — falsy — skipped the HIGH/LOW coherence check on the
    very rows most likely to be broken. `is not None` was the intent.
    """

    def _logical_errors(self, data: dict) -> list[str]:
        return [
            e
            for e in DataValidator.validate_all(data)
            if "cannot be less than" in e or "must be between" in e
        ]

    def test_a_zero_high_below_a_real_low_is_now_caught(self):
        data = {"close": 4200.0, "high": 0.0, "low": 4100.0}
        assert any("cannot be less than" in e for e in self._logical_errors(data))

    def test_a_zero_close_outside_the_range_is_now_caught(self):
        data = {"close": 0.0, "high": 4300.0, "low": 4100.0}
        assert any("must be between" in e for e in self._logical_errors(data))

    def test_a_missing_field_still_skips_the_logical_check(self):
        # None means "not scraped"; only the null check should fire, and the
        # comparison must not raise on a None operand.
        assert (
            self._logical_errors({"close": 4200.0, "high": None, "low": 4100.0}) == []
        )

    def test_a_coherent_row_stays_clean(self):
        assert (
            self._logical_errors({"close": 4200.0, "high": 4300.0, "low": 4100.0}) == []
        )


class TestRequirePageFailsLoud:
    """A scraper used outside its context manager used to raise AttributeError
    on None from inside Playwright. Both now name the problem."""

    def test_barchart_names_the_problem(self):
        from scripts.barchart_scraper.scraper import (
            BarchartScraperError,
            BarchartScraper,
        )

        with pytest.raises(BarchartScraperError, match="not started"):
            BarchartScraper()._require_page()

    def test_nca_names_the_problem(self):
        from scripts.nca_grindings_scraper.browser import NcaBrowser
        from scripts.nca_grindings_scraper.errors import NcaScraperError

        with pytest.raises(NcaScraperError, match="not started"):
            NcaBrowser()._require_page()


class TestFirstTextBlock:
    """`response.content[0].text` assumed the first block is text. A thinking or
    tool-use block first is an AttributeError in production."""

    def test_returns_the_text_when_it_comes_first(self):
        from scripts.press_review_agent.llm_client import _first_text_block
        from scripts.press_review_agent.config import Provider

        block = type("TextBlock", (), {"text": '{"ok": true}'})()
        assert _first_text_block([block], Provider.CLAUDE) == '{"ok": true}'

    def test_skips_a_leading_non_text_block(self):
        from scripts.press_review_agent.llm_client import _first_text_block
        from scripts.press_review_agent.config import Provider

        thinking = type("ThinkingBlock", (), {"thinking": "hmm"})()
        text = type("TextBlock", (), {"text": "payload"})()
        assert _first_text_block([thinking, text], Provider.CLAUDE) == "payload"

    def test_fails_loud_when_there_is_no_text_at_all(self):
        from scripts.press_review_agent.llm_client import _first_text_block
        from scripts.press_review_agent.config import Provider

        tool = type("ToolUseBlock", (), {"input": {}})()
        with pytest.raises(RuntimeError, match="no text block"):
            _first_text_block([tool], Provider.CLAUDE)


class TestJudgeConfidenceNeverDefaultsSilently:
    """A zeroed confidence is a stored lie, and 0.0 is a valid confidence."""

    def test_reads_a_numeric_payload(self):
        from scripts.judge_shadow.db_writer import _as_float

        assert _as_float(3) == 3.0
        assert _as_float("2.5") == 2.5

    def test_raises_on_a_non_numeric_payload(self):
        from scripts.judge_shadow.db_writer import _as_float

        with pytest.raises(TypeError, match="not numeric"):
            _as_float({"unexpected": "shape"})

    def test_still_raises_on_unparseable_text_as_float_did(self):
        from scripts.judge_shadow.db_writer import _as_float

        with pytest.raises(ValueError):
            _as_float("not-a-number")
