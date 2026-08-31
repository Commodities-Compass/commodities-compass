"""Headless-browser fetcher for candyusa.com (SiteGround sgcaptcha WAF bypass).

candyusa.com answers datacenter / Cloud Run egress IPs with an HTTP 202
``sgcaptcha`` JS-challenge (a ``<meta http-equiv="refresh">`` interstitial that
redirects to ``/.well-known/sgcaptcha/``). Plain httpx cannot pass it; a real
browser executes the challenge JS, receives the clearance cookie, and lands on
the real page. See ``config.py`` for the full incident history.

Design:
- One browser context for the whole run. The clearance cookie obtained while
  loading the listing is reused for every subsequent PDF download via the
  context's ``request`` API — no need to re-clear the challenge per file.
- Fail-loud: if the challenge does not clear within the budget (e.g. it escalated
  to an interactive captcha a headless browser cannot solve), raise
  ``NcaScraperError`` rather than parsing the interstitial as if it were content.
"""

from __future__ import annotations

import logging
import platform

from playwright.sync_api import BrowserContext, Page
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from scripts.nca_grindings_scraper.config import BROWSER_TIMEOUT_MS
from scripts.nca_grindings_scraper.errors import NcaScraperError

logger = logging.getLogger(__name__)

# Marker present in both the challenge URL and its HTML body.
_SGCAPTCHA_MARKER = "sgcaptcha"

# Challenge-clear polling: the browser auto-advances through the meta-refresh, so
# we just wait for the markers to disappear. Two passes: passive wait, then one
# forced reload as a last resort before failing loud.
_POLL_INTERVAL_MS = 1_500
_PASSIVE_POLLS = 12  # ~18s letting the WAF auto-advance
_POST_RELOAD_POLLS = 6  # ~9s after a forced reload


def _looks_challenged(page) -> bool:
    """True while the page is still on / showing the sgcaptcha interstitial."""
    if _SGCAPTCHA_MARKER in (page.url or ""):
        return True
    try:
        return _SGCAPTCHA_MARKER in page.content()
    except PlaywrightError:
        # Mid-navigation: content() can throw. Treat as still-challenged so we
        # keep polling rather than returning a half-loaded interstitial.
        return True


class NcaBrowser:
    """Context manager holding one Playwright browser/context for a scraper run."""

    def __init__(self, *, headless: bool = True, timeout_ms: int = BROWSER_TIMEOUT_MS):
        self._headless = headless
        self._timeout_ms = timeout_ms
        self._pw = None
        self._browser = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    def _require_page(self) -> Page:
        """The live page, or fail loud.

        ``_page`` stays None until ``_launch`` runs; reaching a fetch without it
        is a programming error, and a named exception beats an AttributeError on
        None from inside Playwright.
        """
        if self._page is None:
            raise NcaScraperError("Browser page not started — use as a context manager")
        return self._page

    def __enter__(self) -> "NcaBrowser":
        logger.info("Launching Playwright browser (headless=%s)", self._headless)
        self._pw = sync_playwright().start()
        # Chromium on Linux/Cloud Run (the only browser baked into Dockerfile.jobs);
        # WebKit locally on macOS, mirroring the barchart scraper.
        launcher = (
            self._pw.webkit if platform.system() == "Darwin" else self._pw.chromium
        )
        self._browser = launcher.launch(headless=self._headless)
        # Default (real) Chromium UA on purpose — see config.USER_AGENT note.
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
        logger.info("Loading %s (through WAF)", url)
        try:
            self._require_page().goto(
                url, wait_until="domcontentloaded", timeout=self._timeout_ms
            )
        except PlaywrightError as exc:
            raise NcaScraperError(f"Network error loading {url}: {exc}") from exc

        self._await_challenge_clear(url)
        return self._require_page().content()

    def fetch_bytes(self, url: str) -> bytes:
        """Download a binary (PDF) reusing the context's WAF clearance cookie."""
        logger.info("Downloading %s", url)
        try:
            response = self._require_page().request.get(url, timeout=self._timeout_ms)
        except PlaywrightError as exc:
            raise NcaScraperError(f"Network error fetching {url}: {exc}") from exc

        if response.status != 200:
            # WAF may still challenge the binary endpoint — surface it loud.
            raise NcaScraperError(
                f"HTTP {response.status} fetching {url}: {response.text()[:200]!r}"
            )
        body = response.body()
        if not body:
            raise NcaScraperError(f"Empty body fetching {url}")
        return body

    def _await_challenge_clear(self, url: str) -> None:
        for _ in range(_PASSIVE_POLLS):
            if not _looks_challenged(self._require_page()):
                return
            self._require_page().wait_for_timeout(_POLL_INTERVAL_MS)

        logger.warning("sgcaptcha still present for %s — forcing one reload", url)
        try:
            self._require_page().goto(
                url, wait_until="domcontentloaded", timeout=self._timeout_ms
            )
        except PlaywrightError:  # pragma: no cover - reload is best-effort
            pass
        for _ in range(_POST_RELOAD_POLLS):
            if not _looks_challenged(self._require_page()):
                return
            self._require_page().wait_for_timeout(_POLL_INTERVAL_MS)

        raise NcaScraperError(
            f"SiteGround sgcaptcha WAF challenge did not clear for {url} within budget "
            "— headless browser could not pass (likely escalated to an interactive "
            "captcha). Manual fallback: fetch the PDF in a browser + run the backfill CLI."
        )
