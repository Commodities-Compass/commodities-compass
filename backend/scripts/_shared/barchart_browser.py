"""Headless-browser fetch for barchart.com (AWS WAF JS challenge).

Barchart put the site behind AWS WAF on 2026-09-03. Every page now answers
``HTTP 202`` with a ~2KB interstitial that loads ``challenge.js`` from
``*.token.awswaf.com``, mints an ``aws-waf-token`` cookie in JS and reloads.
A plain httpx client cannot produce that token, so both httpx-based Barchart
jobs (``intraday-monitor``, ``barchart-stocks-eu-scraper``) went through this
module instead. ``barchart-scraper`` was already on Playwright and never broke.

This is the second Barchart posture change in three days — 2026-09-01 was the
CloudFront ``public, s-maxage=300`` caching that stripped ``Set-Cookie`` and
killed the ``core-api`` XSRF flow. Expect more; keep the parsers pure and the
transport swappable.

Design (mirrors ``nca_grindings_scraper/browser.py``, a different site behind a
different WAF with the same shape):
- One browser context per run. The ``aws-waf-token`` obtained on the first page
  load is reused for every later fetch in the same run — verified live: a cmdty
  page that answers 202 cold answered 200 on a context that had already cleared
  the challenge on a futures page.
- Fail-loud: if the challenge does not clear within the budget (e.g. it
  escalated to an interactive captcha), raise rather than hand an interstitial
  to a parser that would read it as an empty quote.
"""

from __future__ import annotations

import logging
import platform

from playwright.sync_api import BrowserContext, Page
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

# Markers of the AWS WAF interstitial. Verified absent from the settled pages
# (574KB futures render, 150KB cmdty render) on 2026-09-03 — so their presence
# is a reliable "still challenged" signal, not a false positive on real content.
_CHALLENGE_MARKERS = (
    "awswaf",
    "challenge-container",
    "gokuprops",
    "awswafintegration",
)

# The browser auto-advances through the challenge (~3s observed). Budget well
# past that, then one forced reload before failing loud.
_POLL_INTERVAL_MS = 1_500
_PASSIVE_POLLS = 12  # ~18s letting the WAF auto-advance
_POST_RELOAD_POLLS = 6  # ~9s after a forced reload

DEFAULT_TIMEOUT_MS = 60_000


class BarchartWafError(RuntimeError):
    """Raised when barchart.com cannot be loaded through the WAF."""


def looks_challenged(html: str | None) -> bool:
    """True while ``html`` is the WAF interstitial rather than real content.

    Empty/None counts as challenged: ``page.content()`` can return nothing
    mid-navigation, and treating that as "settled" would hand a parser a blank
    document that fails much further downstream with a useless message.
    """
    if not html or not html.strip():
        return True
    lowered = html.lower()
    return any(marker in lowered for marker in _CHALLENGE_MARKERS)


class BarchartBrowser:
    """Context manager holding one Playwright browser/context for a run."""

    def __init__(
        self,
        *,
        headless: bool = True,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> None:
        self._headless = headless
        self._timeout_ms = timeout_ms
        self._pw = None
        self._browser = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    def _require_page(self) -> Page:
        if self._page is None:
            raise BarchartWafError(
                "Browser page not started — use BarchartBrowser as a context manager"
            )
        return self._page

    def __enter__(self) -> "BarchartBrowser":
        logger.info("Launching Playwright browser (headless=%s)", self._headless)
        self._pw = sync_playwright().start()
        # Chromium on Linux/Cloud Run (the only browser baked into
        # Dockerfile.jobs); WebKit locally on macOS, mirroring the other
        # Barchart scrapers. Both clear the challenge (verified 2026-09-03).
        launcher = (
            self._pw.webkit if platform.system() == "Darwin" else self._pw.chromium
        )
        self._browser = launcher.launch(headless=self._headless)
        self._context = self._browser.new_context()
        self._context.set_default_timeout(self._timeout_ms)
        self._page = self._context.new_page()
        return self

    def __exit__(self, *_exc) -> None:
        for closer in (self._context, self._browser):
            try:
                if closer is not None:
                    closer.close()
            except PlaywrightError:  # pragma: no cover - best-effort teardown
                pass
        if self._pw is not None:
            self._pw.stop()
        logger.info("Browser closed")

    def fetch_html(self, url: str) -> str:
        """Load ``url`` through the WAF and return the settled page HTML."""
        logger.info("Loading %s (through AWS WAF)", url)
        try:
            self._require_page().goto(
                url, wait_until="domcontentloaded", timeout=self._timeout_ms
            )
        except PlaywrightError as exc:
            raise BarchartWafError(f"Network error loading {url}: {exc}") from exc

        self._await_challenge_clear(url)
        return self._require_page().content()

    def _await_challenge_clear(self, url: str) -> None:
        for _ in range(_PASSIVE_POLLS):
            if not looks_challenged(self._safe_content()):
                return
            self._require_page().wait_for_timeout(_POLL_INTERVAL_MS)

        logger.warning("AWS WAF challenge still up for %s — forcing one reload", url)
        try:
            self._require_page().goto(
                url, wait_until="domcontentloaded", timeout=self._timeout_ms
            )
        except PlaywrightError:  # pragma: no cover - reload is best-effort
            pass
        for _ in range(_POST_RELOAD_POLLS):
            if not looks_challenged(self._safe_content()):
                return
            self._require_page().wait_for_timeout(_POLL_INTERVAL_MS)

        raise BarchartWafError(
            f"AWS WAF challenge did not clear for {url} within budget — the "
            "headless browser could not pass it (likely escalated to an "
            "interactive captcha). This needs a human, not a retry."
        )

    def _safe_content(self) -> str | None:
        """``page.content()`` throws mid-navigation; None keeps us polling."""
        try:
            return self._require_page().content()
        except PlaywrightError:
            return None
