"""Orchestrator: discover NCA PDF URLs from chocolatecouncil.org, fetch + parse.

The Chocolate Council page links to every NCA quarterly PDF hosted on
candyusa.com. Filenames are inconsistent (``Q1-2026-Cocoa-Grinds.pdf``,
``Q1_2025_Cocoa_Grinds_REV0421.pdf``, ``Q1_2023_CocoaGrinds_NCA.pdf``, …),
so we MUST scrape the listing rather than predict URLs.
"""

from __future__ import annotations

import logging
import re

import httpx

from scripts.nca_grindings_scraper.config import (
    FETCH_TIMEOUT_SECONDS,
    LISTING_URL,
    USER_AGENT,
)
from scripts.nca_grindings_scraper.parser import NcaRecord, parse_nca_pdf

logger = logging.getLogger(__name__)


# Quarter PDFs on candyusa.com — flexible separators:
#   Q1-2026-Cocoa-Grinds.pdf
#   Q1_2025_Cocoa_Grinds_REV0421.pdf
#   Q1_2023_CocoaGrinds_NCA.pdf
#   2021_1stQtr_CocoaGrinds_NCA.pdf  ← older style (handled by second regex)
_PDF_LINK_RE = re.compile(
    r'href="(?P<url>https?://[^"]*candyusa\.com/[^"]*Q(?P<q>[1-4])'
    r'[-_](?P<y>20\d{2})[^"]*Cocoa[^"]*Grind[^"]*\.pdf)"',
    re.IGNORECASE,
)
# Fallback for the old "2021_1stQtr_..." pattern.
_PDF_LINK_OLD_RE = re.compile(
    r'href="(?P<url>https?://[^"]*candyusa\.com/[^"]*(?P<y>20\d{2})_'
    r'(?P<q>[1-4])(?:st|nd|rd|th)?Qtr[^"]*Cocoa[^"]*Grind[^"]*\.pdf)"',
    re.IGNORECASE,
)


class NcaScraperError(RuntimeError):
    """Fail-loud error for NCA scraper (per pipeline-error-handling rule)."""


def _http_get(url: str) -> httpx.Response:
    try:
        response = httpx.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=FETCH_TIMEOUT_SECONDS,
            follow_redirects=True,
        )
    except httpx.HTTPError as exc:
        raise NcaScraperError(f"Network error fetching {url}: {exc}") from exc

    if response.status_code != 200:
        raise NcaScraperError(
            f"HTTP {response.status_code} fetching {url}: {response.text[:200]!r}"
        )
    return response


def discover_pdf_urls() -> dict[str, str]:
    """Return ``{period_label: pdf_url}`` for every NCA PDF found on the listing."""
    logger.info("Discovering NCA PDF URLs from %s", LISTING_URL)
    response = _http_get(LISTING_URL)
    body = response.text
    if not body.strip():
        raise NcaScraperError("NCA listing page returned empty body.")

    urls: dict[str, str] = {}
    for match in _PDF_LINK_RE.finditer(body):
        period_label = f"Q{match.group('q')}-{match.group('y')}"
        urls[period_label] = match.group("url")
    for match in _PDF_LINK_OLD_RE.finditer(body):
        period_label = f"Q{match.group('q')}-{match.group('y')}"
        # Don't overwrite a newer match found by the primary regex.
        urls.setdefault(period_label, match.group("url"))

    if not urls:
        raise NcaScraperError(
            "NCA listing page contains no Cocoa Grinds PDF links. "
            "Check the listing URL or page structure."
        )

    logger.info(
        "Discovered %d NCA PDFs (range %s..%s)",
        len(urls),
        min(urls),
        max(urls),
    )
    return urls


def fetch_and_parse(period_label: str, pdf_url: str) -> list[NcaRecord]:
    logger.info("Fetching NCA %s from %s", period_label, pdf_url)
    response = _http_get(pdf_url)
    if not response.content:
        raise NcaScraperError(f"NCA PDF body empty: {pdf_url}")
    records = parse_nca_pdf(response.content, expected_period_label=period_label)
    logger.info(
        "Parsed %s: %d records (publication_date=%s)",
        period_label,
        len(records),
        records[0].publication_date if records else "?",
    )
    return records
