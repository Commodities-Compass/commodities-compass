"""Unit tests for the NCA headless-browser WAF-clearance detection logic."""

from __future__ import annotations

import pytest
from playwright.sync_api import Error as PlaywrightError

from scripts.nca_grindings_scraper.browser import _looks_challenged


class _FakePage:
    """Minimal page stand-in exposing ``url`` and ``content()``."""

    def __init__(self, url: str, content: str | Exception):
        self.url = url
        self._content = content

    def content(self) -> str:
        if isinstance(self._content, Exception):
            raise self._content
        return self._content


@pytest.mark.unit
def test_challenge_detected_in_url() -> None:
    page = _FakePage(
        "https://candyusa.com/.well-known/sgcaptcha/?r=%2Fcocoa-grinds-report",
        "<html>whatever</html>",
    )
    assert _looks_challenged(page) is True


@pytest.mark.unit
def test_challenge_detected_in_body() -> None:
    page = _FakePage(
        "https://candyusa.com/cocoa-grinds-report/",
        '<meta http-equiv="refresh" content="0;/.well-known/sgcaptcha/?r=x">',
    )
    assert _looks_challenged(page) is True


@pytest.mark.unit
def test_clean_page_not_challenged() -> None:
    page = _FakePage(
        "https://candyusa.com/cocoa-grinds-report/",
        '<html><a href="Q1-2026-Cocoa-Grinds.pdf">Q1 2026</a></html>',
    )
    assert _looks_challenged(page) is False


@pytest.mark.unit
def test_mid_navigation_treated_as_challenged() -> None:
    # content() throwing mid-navigation must be treated as still-challenged
    # so the poller keeps waiting instead of returning a half-loaded page.
    page = _FakePage(
        "https://candyusa.com/cocoa-grinds-report/",
        PlaywrightError("Execution context was destroyed"),
    )
    assert _looks_challenged(page) is True
