"""Orchestrator: fetch Barchart cmdty page → parse → return StockEuObservation.

Pure fetch + parse — no DB writes. The CLI in ``main.py`` does the UPDATE.

Fail-loud per ``.claude/rules/pipeline-error-handling.md`` — no auto-retry,
no fallback source.
"""

from __future__ import annotations

import logging

import httpx

from scripts.barchart_stocks_eu_scraper.config import (
    BARCHART_STOCKS_EU_URL,
    FETCH_TIMEOUT_SECONDS,
    USER_AGENT,
)
from scripts.barchart_stocks_eu_scraper.parser import (
    StockEuObservation,
    parse_barchart_stocks_eu_html,
)

logger = logging.getLogger(__name__)


class BarchartStocksEuScraperError(RuntimeError):
    """Raised when the Barchart Stock EU fetch / parse pipeline fails."""


def _fetch(url: str) -> str:
    """HTTP GET with single attempt; fail-loud on network / HTTP / empty body."""
    logger.info("Fetching Barchart Stocks EU from %s", url)
    try:
        response = httpx.get(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml",
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=FETCH_TIMEOUT_SECONDS,
            follow_redirects=True,
        )
    except httpx.HTTPError as exc:
        raise BarchartStocksEuScraperError(
            f"Network error fetching {url}: {exc}"
        ) from exc

    if response.status_code != 200:
        raise BarchartStocksEuScraperError(
            f"HTTP {response.status_code} fetching {url}: {response.text[:200]!r}"
        )

    body = response.text
    if not body.strip():
        raise BarchartStocksEuScraperError(f"Empty body from {url}")

    return body


def scrape_latest() -> StockEuObservation:
    """Fetch + parse the live Barchart cmdty IC345DRW page.

    Returns the most recent ICE Europe certified cocoa stock value (in
    60kg bags) along with the 7-day history table for redundancy.
    """
    body = _fetch(BARCHART_STOCKS_EU_URL)
    obs = parse_barchart_stocks_eu_html(body)
    logger.info(
        "Parsed Barchart Stocks EU: %s = %s bags60kg (history rows: %d)",
        obs.date,
        obs.value_bags60kg,
        len(obs.history),
    )
    return obs
