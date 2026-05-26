"""Orchestrator: discover ECA PDF URLs from the listing page, fetch + parse them.

Two entry points:

  * ``discover_pdf_urls()`` — scrape the listing page once and return a mapping
    of ``period_label → pdf_url`` for every quarter publicly linked. Used by
    both the daily scraper (gate matches) and the backfill.

  * ``fetch_and_parse(period_label, pdf_url)`` — single-PDF helper. Returns
    a list of :class:`EcaRecord` (volume_tonnes + yoy_pct).

No DB writes here. Caller (main / backfill) is responsible for persistence.
"""

from __future__ import annotations

import logging
import re

import httpx

from scripts.eca_grindings_scraper.config import (
    FETCH_TIMEOUT_SECONDS,
    LISTING_URL,
    USER_AGENT,
)
from scripts.eca_grindings_scraper.parser import EcaRecord, parse_eca_pdf

logger = logging.getLogger(__name__)


# WESTERN-STATS-Q<n>-<YYYY>[-suffix].pdf — captures the period label.
_PDF_LINK_RE = re.compile(
    r'href="(?P<url>https?://[^"]*WESTERN-STATS-Q(?P<q>\d)-(?P<y>\d{4})[^"]*\.pdf)"',
    re.IGNORECASE,
)


class EcaScraperError(RuntimeError):
    """Fail-loud error for ECA scraper (per pipeline-error-handling rule)."""


def _http_get(url: str) -> httpx.Response:
    try:
        response = httpx.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=FETCH_TIMEOUT_SECONDS,
            follow_redirects=True,
        )
    except httpx.HTTPError as exc:
        raise EcaScraperError(f"Network error fetching {url}: {exc}") from exc

    if response.status_code != 200:
        raise EcaScraperError(
            f"HTTP {response.status_code} fetching {url}: {response.text[:200]!r}"
        )
    return response


def discover_pdf_urls() -> dict[str, str]:
    """Scrape the ECA listing page and return ``{period_label: pdf_url}``.

    Period labels follow the canonical ``Q{n}-{YYYY}`` format used by the
    publication calendar. If a quarter is linked more than once (rare; old
    revisions), the LAST URL wins — listings always show the most recent
    revision higher on the page, so we deliberately keep the latest seen.
    """
    logger.info("Discovering ECA PDF URLs from %s", LISTING_URL)
    response = _http_get(LISTING_URL)
    body = response.text
    if not body.strip():
        raise EcaScraperError("ECA listing page returned empty body.")

    urls: dict[str, str] = {}
    for match in _PDF_LINK_RE.finditer(body):
        period_label = f"Q{match.group('q')}-{match.group('y')}"
        urls[period_label] = match.group("url")

    if not urls:
        raise EcaScraperError(
            "ECA listing page contains no WESTERN-STATS PDF links. "
            "Check the listing URL or page structure."
        )

    logger.info(
        "Discovered %d ECA PDFs (range %s..%s)",
        len(urls),
        min(urls),
        max(urls),
    )
    return urls


def fetch_and_parse(period_label: str, pdf_url: str) -> list[EcaRecord]:
    """Download one ECA PDF and parse it into a list of EcaRecord."""
    logger.info("Fetching ECA %s from %s", period_label, pdf_url)
    response = _http_get(pdf_url)
    if not response.content:
        raise EcaScraperError(f"ECA PDF body empty: {pdf_url}")
    records = parse_eca_pdf(response.content, period_label=period_label)
    logger.info(
        "Parsed %s: %d records (publication_date=%s)",
        period_label,
        len(records),
        records[0].publication_date if records else "?",
    )
    return records
