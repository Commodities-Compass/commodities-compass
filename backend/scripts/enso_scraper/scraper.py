"""Orchestrator: fetch NOAA PSL → parse → return EnsoRecord list.

Pure-fetch logic, no DB writes. The DB layer (db_writer.py) is called
separately by main.py to keep the fetch testable in isolation (httpx mock).
"""

from __future__ import annotations

import logging

import httpx

from scripts.enso_scraper.config import (
    FETCH_TIMEOUT_SECONDS,
    NINO34_URL,
    ONI_URL,
    USER_AGENT,
    VALUE_NAME_NINO34,
    VALUE_NAME_ONI,
)
from scripts.enso_scraper.parser import EnsoRecord, parse_psl_text

logger = logging.getLogger(__name__)


class EnsoScraperError(RuntimeError):
    """Raised when the NOAA PSL fetch or parse fails.

    Fail-loud per ``.claude/rules/pipeline-error-handling.md`` — no auto-retry,
    no fallback source.
    """


def _fetch(url: str) -> str:
    """HTTP GET with a single attempt; fail-loud on any non-200."""
    try:
        response = httpx.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=FETCH_TIMEOUT_SECONDS,
            follow_redirects=True,
        )
    except httpx.HTTPError as exc:
        raise EnsoScraperError(f"Network error fetching {url}: {exc}") from exc

    if response.status_code != 200:
        raise EnsoScraperError(
            f"HTTP {response.status_code} fetching {url}: {response.text[:200]!r}"
        )

    body = response.text
    if not body.strip():
        raise EnsoScraperError(f"Empty body from {url}")

    return body


def scrape_oni() -> list[EnsoRecord]:
    """Fetch + parse NOAA ONI (3-month mean SST anomaly).

    Returns a list of EnsoRecord sorted ascending by date, with
    ``value_name="oni"``. Fail-loud on network, HTTP, or parse errors.
    """
    logger.info("Fetching ONI from %s", ONI_URL)
    body = _fetch(ONI_URL)
    records = parse_psl_text(body, value_name=VALUE_NAME_ONI)
    if not records:
        raise EnsoScraperError(
            f"NOAA ONI fetch returned no parseable rows ({ONI_URL}). "
            "Check the source format or NOAA outage."
        )
    logger.info(
        "Parsed %d ONI records (%s → %s)",
        len(records),
        records[0].date,
        records[-1].date,
    )
    return records


def scrape_nino34() -> list[EnsoRecord]:
    """Fetch + parse NOAA Niño 3.4 SST anomaly.

    Returns a list of EnsoRecord sorted ascending by date, with
    ``value_name="nino34_anomaly"``. Fail-loud on network, HTTP, or parse
    errors.
    """
    logger.info("Fetching Niño 3.4 anomaly from %s", NINO34_URL)
    body = _fetch(NINO34_URL)
    records = parse_psl_text(body, value_name=VALUE_NAME_NINO34)
    if not records:
        raise EnsoScraperError(
            f"NOAA Niño 3.4 fetch returned no parseable rows ({NINO34_URL}). "
            "Check the source format or NOAA outage."
        )
    logger.info(
        "Parsed %d Niño 3.4 records (%s → %s)",
        len(records),
        records[0].date,
        records[-1].date,
    )
    return records


def scrape_all() -> list[EnsoRecord]:
    """Fetch both ONI + Niño 3.4 and return a merged list.

    Caller (db_writer) splits records by ``value_name`` and routes each to its
    corresponding column.
    """
    return scrape_oni() + scrape_nino34()
