"""Orchestrator: fetch Barchart cmdty page → parse → return StockEuObservation.

Pure fetch + parse — no DB writes. The CLI in ``main.py`` does the UPDATE.

The fetch goes through a headless browser since 2026-09-03: barchart.com sits
behind an AWS WAF that answers every page with an HTTP 202 JS challenge, which
httpx cannot solve. Only the transport changed — the parser below is untouched.

Fail-loud per ``.claude/rules/pipeline-error-handling.md`` — no auto-retry,
no fallback source.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from scripts._shared.barchart_browser import BarchartBrowser, BarchartWafError
from scripts.barchart_stocks_eu_scraper.config import BARCHART_STOCKS_EU_URL
from scripts.barchart_stocks_eu_scraper.parser import (
    StockEuObservation,
    parse_barchart_stocks_eu_html,
)

logger = logging.getLogger(__name__)

# What proves the cmdty page actually arrived — the blocks parser.py reads.
READY_MARKER = "cmdty-quote-table"


class BarchartStocksEuScraperError(RuntimeError):
    """Raised when the Barchart Stock EU fetch / parse pipeline fails."""


def _fetch(url: str, fetch_html: Callable[[str], str] | None = None) -> str:
    """One page load; fail-loud on WAF failure or empty body. No retry."""
    logger.info("Fetching Barchart Stocks EU from %s", url)
    try:
        if fetch_html is not None:
            body = fetch_html(url)
        else:
            with BarchartBrowser() as browser:
                # The parser needs these tables; make their arrival the
                # readiness signal rather than the challenge's disappearance.
                body = browser.fetch_html(url, ready_marker=READY_MARKER)
    except BarchartWafError as exc:
        raise BarchartStocksEuScraperError(f"Could not load {url}: {exc}") from exc

    if not body or not body.strip():
        raise BarchartStocksEuScraperError(f"Empty body from {url}")

    return body


def scrape_latest(
    fetch_html: Callable[[str], str] | None = None,
) -> StockEuObservation:
    """Fetch + parse the live Barchart cmdty IC345DRW page.

    Returns the most recent ICE Europe certified cocoa stock value (in
    60kg bags) along with the 7-day history table for redundancy.
    """
    body = _fetch(BARCHART_STOCKS_EU_URL, fetch_html)
    obs = parse_barchart_stocks_eu_html(body)
    logger.info(
        "Parsed Barchart Stocks EU: %s = %s bags60kg (history rows: %d)",
        obs.date,
        obs.value_bags60kg,
        len(obs.history),
    )
    return obs
