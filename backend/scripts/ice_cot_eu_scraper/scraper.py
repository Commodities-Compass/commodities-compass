"""Orchestrator: fetch ICE COT history CSV → parse → return CotEuObservation list.

Pure fetch + parse — no DB writes. The CLI in ``main.py`` does the DB UPSERT.

Fail-loud per ``.claude/rules/pipeline-error-handling.md`` — no auto-retry, no
fallback source.
"""

from __future__ import annotations

import logging

import httpx

from scripts.ice_cot_eu_scraper.config import (
    FETCH_TIMEOUT_SECONDS,
    ICE_COT_HISTORY_URL_TEMPLATE,
    USER_AGENT,
)
from scripts.ice_cot_eu_scraper.parser import CotEuObservation, parse_ice_cot_csv

logger = logging.getLogger(__name__)


class IceCotEuScraperError(RuntimeError):
    """Raised when the ICE COT fetch / parse / filter pipeline fails."""


def _fetch(url: str) -> str:
    """HTTP GET with single attempt; fail-loud on network / HTTP / empty body."""
    logger.info("Fetching ICE COT history from %s", url)
    try:
        response = httpx.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/csv"},
            timeout=FETCH_TIMEOUT_SECONDS,
            follow_redirects=True,
        )
    except httpx.HTTPError as exc:
        raise IceCotEuScraperError(f"Network error fetching {url}: {exc}") from exc

    if response.status_code != 200:
        raise IceCotEuScraperError(
            f"HTTP {response.status_code} fetching {url}: {response.text[:200]!r}"
        )

    body = response.text
    if not body.strip():
        raise IceCotEuScraperError(f"Empty body from {url}")

    return body


def scrape_year(year: int) -> list[CotEuObservation]:
    """Fetch + parse one year's worth of ICE COT EU cocoa rows.

    Returns a sorted list of CotEuObservation. Fails-loud if no cocoa rows
    are found in the file (which would indicate an ICE format change).
    """
    url = ICE_COT_HISTORY_URL_TEMPLATE.format(year=year)
    body = _fetch(url)
    observations = parse_ice_cot_csv(body)

    if not observations:
        raise IceCotEuScraperError(
            f"ICE COT CSV for {year} contained no cocoa EU FutOnly rows "
            f"({url}). Check the CSV format or the cocoa market name string."
        )

    logger.info(
        "Parsed %d ICE COT EU cocoa records for year %d (%s → %s)",
        len(observations),
        year,
        observations[0].report_date,
        observations[-1].report_date,
    )
    return observations
