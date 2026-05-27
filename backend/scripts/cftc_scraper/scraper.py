"""CFTC Disaggregated Commitments of Traders scraper — Cocoa (ICE Futures U.S.).

Refactored 2026-05-27 to:
  * Extract ``report_date`` from the per-section header line
    ("Disaggregated Commitments of Traders - Futures Only, <Month> <Day>, <Year>")
    and derive ``release_date = report_date + 3 days`` (CFTC Tuesday→Friday
    convention, mirrors ICE EU parser).
  * Parse the "All" row to extract not just Producer/Merchant Long/Short
    (which was the old behavior) but ALSO Open Interest, Swap Dealers,
    **Managed Money Long/Short** (parity with the ICE EU R&D signal),
    Other Reportables, and Non-Reportable positions.
  * Return a frozen ``CocoaCotUsObservation`` dataclass instead of a single
    float, so the writer can populate ``pl_cot_us_weekly`` with the full
    decomposition.

Per ``.claude/rules/pipeline-error-handling.md``: fails loud on any drift
(missing header, malformed All row, unexpected column count, value out of
range, stale report).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

import httpx

from scripts.cftc_scraper.config import (
    AGRICULTURE_URL,
    COCOA_CODE,
    COCOA_PATTERN,
    VALIDATION_RANGE,
)

logger = logging.getLogger(__name__)


# CFTC publication lag: snapshot Tuesday → release Friday (3 days).
RELEASE_LAG_DAYS = 3

# All 14 numeric fields on the "All" row, in source column order.
_DISAGG_FIELDS = (
    "open_interest",
    "prod_merc_long",
    "prod_merc_short",
    "swap_long",
    "swap_short",
    "swap_spreading",
    "m_money_long",
    "m_money_short",
    "m_money_spreading",
    "other_rept_long",
    "other_rept_short",
    "other_rept_spreading",
    "non_rept_long",
    "non_rept_short",
)


class CFTCScraperError(Exception):
    """Base exception for CFTC scraper errors."""


@dataclass(frozen=True)
class CocoaCotUsObservation:
    """Frozen snapshot of one CFTC US cocoa COT publication.

    All position fields are integer contract counts. ``prod_merc_net`` and
    ``m_money_net`` are computed (not stored here) and persisted as
    GENERATED columns in ``pl_cot_us_weekly``.
    """

    release_date: date  # Friday CFTC publishes
    report_date: date  # Tuesday snapshot covered

    open_interest: int

    prod_merc_long: int
    prod_merc_short: int

    swap_long: int
    swap_short: int
    swap_spreading: int

    m_money_long: int
    m_money_short: int
    m_money_spreading: int

    other_rept_long: int
    other_rept_short: int
    other_rept_spreading: int

    non_rept_long: int
    non_rept_short: int

    @property
    def prod_merc_net(self) -> int:
        return self.prod_merc_long - self.prod_merc_short

    @property
    def m_money_net(self) -> int:
        return self.m_money_long - self.m_money_short


# Header line that carries the report date, e.g.:
#   "Disaggregated Commitments of Traders - Futures Only, May 19, 2026"
# Allow trailing whitespace; the source pads to 200+ chars.
_REPORT_DATE_RE = re.compile(
    r"Disaggregated\s+Commitments\s+of\s+Traders\s*-\s*Futures\s+Only,\s+"
    r"(?P<month>[A-Z][a-z]+)\s+(?P<day>\d{1,2}),\s+(?P<year>\d{4})",
    re.IGNORECASE,
)


def _parse_report_date(section_text: str) -> date:
    match = _REPORT_DATE_RE.search(section_text)
    if not match:
        raise CFTCScraperError(
            "Could not extract report date from CFTC section header — "
            "expected line like 'Disaggregated Commitments of Traders - "
            "Futures Only, <Month> <Day>, <Year>'."
        )
    raw = f"{match['month']} {match['day']}, {match['year']}"
    try:
        return datetime.strptime(raw, "%B %d, %Y").date()
    except ValueError as exc:
        raise CFTCScraperError(f"Unparseable CFTC report date {raw!r}") from exc


# "All" row: 14 numeric tokens separated by whitespace, with the Open
# Interest field after the first colon and the rest of the fields after the
# second colon (then a final colon separating Non-Reportable).
#
# Real example (whitespace collapsed):
# All  :   162,798:    38,801     54,153     34,222 ... :   12,345    23,456
_NUMBER_RE = re.compile(r"-?[\d,]+")
_ALL_LINE_RE = re.compile(r"^\s*All\s*:.*$", re.MULTILINE)


def _parse_all_row(section_text: str) -> dict[str, int]:
    """Parse the "All" line of a Disaggregated section.

    Extracts the 14 numeric fields in column order and returns them as a
    dict keyed by ``_DISAGG_FIELDS``. Fails loud on any deviation (line
    missing, fewer/more tokens than expected, unparseable token).
    """
    line_match = _ALL_LINE_RE.search(section_text)
    if not line_match:
        raise CFTCScraperError(
            "Could not locate 'All :' aggregate row in cocoa section."
        )

    tokens = _NUMBER_RE.findall(line_match.group(0))
    if len(tokens) != len(_DISAGG_FIELDS):
        raise CFTCScraperError(
            f"Expected {len(_DISAGG_FIELDS)} numeric tokens on 'All' row, "
            f"got {len(tokens)}: {tokens!r}. CFTC format may have drifted."
        )

    parsed: dict[str, int] = {}
    for name, raw in zip(_DISAGG_FIELDS, tokens):
        try:
            parsed[name] = int(raw.replace(",", ""))
        except ValueError as exc:
            raise CFTCScraperError(
                f"Unparseable {name} value {raw!r} on cocoa 'All' row."
            ) from exc
    return parsed


class CFTCScraper:
    """Scraper for the CFTC Disaggregated COT — Cocoa section."""

    AGRICULTURE_URL = AGRICULTURE_URL
    COCOA_CODE = COCOA_CODE
    COCOA_PATTERN = COCOA_PATTERN
    VALIDATION_RANGE = VALIDATION_RANGE

    def __init__(self) -> None:
        self.timeout = 60

    def download_report(self) -> str:
        logger.info("Downloading CFTC report from %s", self.AGRICULTURE_URL)
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(self.AGRICULTURE_URL)
                response.raise_for_status()
            content = response.text
            logger.info("Downloaded report (%d characters)", len(content))
            return content
        except httpx.HTTPError as exc:
            raise CFTCScraperError(f"Failed to download report: {exc}") from exc

    def _extract_cocoa_section(self, report_text: str) -> str:
        """Slice the report down to the cocoa section.

        We anchor on the COCOA pattern (with code 073732) and capture all
        text up to the next commodity section or end-of-document — large
        enough to include the 'All' row + header but bounded so the regex
        doesn't drift into another commodity.
        """
        cocoa_match = re.search(
            rf"{self.COCOA_PATTERN}.*?Code-{self.COCOA_CODE}",
            report_text,
            re.DOTALL | re.IGNORECASE,
        )
        if not cocoa_match:
            raise CFTCScraperError(f"COCOA section not found (code {self.COCOA_CODE})")
        # ~5KB after the header is plenty to capture the section's All row
        # and metadata without bleeding into the next commodity (~10KB
        # spacing in the real report).
        return report_text[cocoa_match.end() : cocoa_match.end() + 5000]

    def scrape(self, max_stale_days: Optional[int] = None) -> CocoaCotUsObservation:
        """Full scrape: download → slice cocoa → parse date + All row →
        validate. Returns a frozen observation. ``max_stale_days`` if set,
        raises when the parsed report_date is older than that — useful
        downstream to fail-loud on a publisher freeze.
        """
        logger.info("Starting CFTC scrape")
        report_text = self.download_report()
        section = self._extract_cocoa_section(report_text)

        report_date = _parse_report_date(section)
        release_date = _adjust_release_date(report_date)

        if max_stale_days is not None:
            age = (date.today() - report_date).days
            if age > max_stale_days:
                raise CFTCScraperError(
                    f"CFTC report_date {report_date.isoformat()} is {age} "
                    f"days old (> {max_stale_days}j). Publisher may have "
                    "stopped or scraper is hitting a stale cache."
                )

        fields = _parse_all_row(section)
        net = fields["prod_merc_long"] - fields["prod_merc_short"]
        min_val, max_val = self.VALIDATION_RANGE
        if not (min_val <= net <= max_val):
            raise CFTCScraperError(
                f"prod_merc_net {net:,} outside valid range [{min_val:,}, {max_val:,}]"
            )

        obs = CocoaCotUsObservation(
            release_date=release_date,
            report_date=report_date,
            **fields,
        )
        logger.info(
            "Parsed cocoa COT: report_date=%s release_date=%s "
            "prod_merc_net=%d m_money_net=%d open_interest=%d",
            obs.report_date,
            obs.release_date,
            obs.prod_merc_net,
            obs.m_money_net,
            obs.open_interest,
        )
        return obs


def _adjust_release_date(report_date: date) -> date:
    """Derive Friday release_date from Tuesday report_date.

    Standard convention: report_date is Tuesday, release_date is Friday
    (+3 days). Holidays may shift the actual release by one day but the
    UNIQUE constraint on (release_date, contract_market) tolerates UPSERTs
    that re-classify a row.
    """
    from datetime import timedelta

    return report_date + timedelta(days=RELEASE_LAG_DAYS)
