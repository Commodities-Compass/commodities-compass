"""CFTC scraper - Simple version."""

import logging
import re

import httpx

from scripts.cftc_scraper.config import (
    AGRICULTURE_URL,
    COCOA_CODE,
    COCOA_PATTERN,
    VALIDATION_RANGE,
)

logger = logging.getLogger(__name__)


class CFTCScraperError(Exception):
    """Base exception for CFTC scraper errors."""

    pass


class CFTCScraper:
    """Simple scraper for CFTC Commitments of Traders data."""

    AGRICULTURE_URL = AGRICULTURE_URL
    COCOA_CODE = COCOA_CODE
    COCOA_PATTERN = COCOA_PATTERN
    VALIDATION_RANGE = VALIDATION_RANGE

    def __init__(self):
        """Initialize CFTC scraper."""
        self.timeout = 60

    def download_report(self) -> str:
        """
        Download latest CFTC Agriculture report.

        Returns:
            Report content as text

        Raises:
            CFTCScraperError: If download fails
        """
        logger.info(f"Downloading CFTC report from {self.AGRICULTURE_URL}")

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(self.AGRICULTURE_URL)
                response.raise_for_status()

            content = response.text
            logger.info(f"Downloaded report ({len(content)} characters)")
            return content

        except httpx.HTTPError as e:
            raise CFTCScraperError(f"Failed to download report: {e}") from e

    def parse_cocoa_section(self, report_text: str) -> tuple[int, int]:
        """
        Parse cocoa section and extract Producer/Merchant Long/Short.

        Args:
            report_text: Full report text

        Returns:
            Tuple of (long, short) positions

        Raises:
            CFTCScraperError: If parsing fails
        """
        # Find COCOA section
        cocoa_match = re.search(
            rf"{self.COCOA_PATTERN}.*?Code-{self.COCOA_CODE}",
            report_text,
            re.DOTALL | re.IGNORECASE,
        )

        if not cocoa_match:
            raise CFTCScraperError(f"COCOA section not found (code {self.COCOA_CODE})")

        # Extract lines after cocoa header
        start_pos = cocoa_match.end()
        section_text = report_text[start_pos : start_pos + 5000]

        # Find the "All" row with positions
        # Format: "All  :   162,798:    38,801     54,153     34,222..."
        all_row_pattern = r"All\s+:\s+[\d,]+:\s+([\d,]+)\s+([\d,]+)"
        match = re.search(all_row_pattern, section_text)

        if not match:
            raise CFTCScraperError("Could not parse Producer/Merchant Long/Short")

        # Extract and clean values
        long_str = match.group(1).replace(",", "")
        short_str = match.group(2).replace(",", "")

        long_pos = int(long_str)
        short_pos = int(short_str)

        logger.info(
            f"Parsed COCOA positions - Long: {long_pos:,}, Short: {short_pos:,}"
        )

        return long_pos, short_pos

    def scrape(self) -> float:
        """
        Scrape CFTC and return COM NET US value.

        Returns:
            COM NET US value (Long - Short)

        Raises:
            CFTCScraperError: If scraping fails
        """
        logger.info("Starting CFTC scrape")

        # Download report
        report_text = self.download_report()

        # Parse positions
        long_pos, short_pos = self.parse_cocoa_section(report_text)

        # Calculate net
        net_position = long_pos - short_pos

        # Validate range
        min_val, max_val = self.VALIDATION_RANGE
        if not (min_val <= net_position <= max_val):
            raise CFTCScraperError(
                f"COM NET US {net_position:,} outside valid range [{min_val:,}, {max_val:,}]"
            )

        logger.info(f"COM NET US: {net_position:,}")

        return float(net_position)
