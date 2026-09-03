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

Readiness is POSITIVE, never an absence. On 2026-09-03 the first cut of this
module waited only for the challenge markers to disappear; Cloud Run received a
page that had never carried them, so "not challenged" read as "settled" and an
unusable page reached the parser 288ms later, which then blamed a layout drift.
A caller now states what proves ITS page arrived (``ready_marker``) and we poll
until that shows up. Failures carry the HTTP status, the page length and a body
snippet, so the next Barchart move diagnoses itself.

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
import re

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


def is_ready(html: str | None, marker: str) -> bool:
    """True when ``html`` is settled content carrying ``marker``.

    Both halves matter: a challenge page that happens to mention the marker is
    not ready, and a page free of challenge markers is not ready either unless
    it actually shows the content the caller came for.
    """
    if looks_challenged(html):
        return False
    return marker in (html or "")


def _snippet(html: str | None, limit: int = 400) -> str:
    """A readable, bounded excerpt of a page body for an error message."""
    if not html:
        return "<empty>"
    text = re.sub(r"<script\b.*?</script>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = " ".join(text.split())
    return text[:limit] if text else html.strip()[:limit]


def describe_failure(
    *,
    url: str,
    status: int | None,
    html: str | None,
    marker: str,
) -> str:
    """Build a failure message that carries its own evidence."""
    status_label = "unknown" if status is None else str(status)
    length = len(html or "")
    if looks_challenged(html):
        cause = (
            "the AWS WAF challenge never cleared — the headless browser could "
            "not pass it (likely escalated to an interactive captcha)"
        )
    else:
        cause = (
            f"the page settled but never showed {marker!r} — this is NOT a "
            "Barchart layout drift until you have checked the body below; a WAF "
            "block page or a CDN error looks exactly like this"
        )
    return (
        f"Could not load {url}: {cause}. "
        f"HTTP {status_label}, {length} chars. Body: {_snippet(html)!r}"
    )


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

    def fetch_html(self, url: str, *, ready_marker: str) -> str:
        """Load ``url`` through the WAF and return the settled page HTML.

        ``ready_marker`` is what proves the caller's page actually arrived — a
        substring only the real content carries. We poll until it shows up
        rather than until the challenge disappears.
        """
        logger.info("Loading %s (through AWS WAF)", url)
        status = self._goto(url)
        self._await_ready(url, ready_marker, status)
        return self._require_page().content()

    def _goto(self, url: str) -> int | None:
        """Navigate, returning the HTTP status (logged — it is the first clue)."""
        try:
            response = self._require_page().goto(
                url, wait_until="domcontentloaded", timeout=self._timeout_ms
            )
        except PlaywrightError as exc:
            raise BarchartWafError(f"Network error loading {url}: {exc}") from exc

        status = response.status if response is not None else None
        logger.info("HTTP %s from %s", status if status is not None else "unknown", url)
        return status

    def _await_ready(self, url: str, marker: str, status: int | None) -> None:
        """Poll until the page shows ``marker``; one forced reload, then fail."""
        for _ in range(_PASSIVE_POLLS):
            if is_ready(self._safe_content(), marker):
                return
            self._require_page().wait_for_timeout(_POLL_INTERVAL_MS)

        logger.warning("%s not ready after first pass — forcing one reload", url)
        try:
            status = self._goto(url)
        except BarchartWafError:  # pragma: no cover - reload is best-effort
            pass
        for _ in range(_POST_RELOAD_POLLS):
            if is_ready(self._safe_content(), marker):
                return
            self._require_page().wait_for_timeout(_POLL_INTERVAL_MS)

        raise BarchartWafError(
            describe_failure(
                url=url, status=status, html=self._safe_content(), marker=marker
            )
        )

    def _safe_content(self) -> str | None:
        """``page.content()`` throws mid-navigation; None keeps us polling."""
        try:
            return self._require_page().content()
        except PlaywrightError:
            return None
