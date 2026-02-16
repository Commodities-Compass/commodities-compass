"""Barchart.com scraper for London cocoa futures data."""

import html
import logging
import re
from datetime import datetime
from typing import Dict, Optional

from playwright.sync_api import sync_playwright

from scripts.barchart_scraper.config import (
    PRICES_URL,
    get_volatility_url,
    BROWSER_TIMEOUT,
    BROWSER_WAIT,
    USER_AGENT,
)

logger = logging.getLogger(__name__)


class BarchartScraperError(Exception):
    """Base exception for scraper errors."""

    pass


def extract_ohlc_data(html_content: str) -> Optional[Dict]:
    """
    Extract OHLC data from Barchart HTML content.
    Adapted from backend/scraper.py (proven working patterns).

    Args:
        html_content: HTML content from Barchart page

    Returns:
        Dict with OHLC data or None if extraction failed
    """
    # Decode HTML entities (Barchart uses &quot; instead of ")
    decoded_content = html.unescape(html_content)

    ohlc = {}

    # First, try to find the "raw" data block which contains OHLC data
    # The raw block with OHLC data contains fields like lowPrice, openPrice, highPrice, volume, openInterest
    raw_block_pattern = r'"raw"\s*:\s*\{([^}]*"lowPrice"\s*:\s*\d+[^}]*)\}'
    raw_match = re.search(raw_block_pattern, decoded_content)

    if raw_match:
        raw_block = raw_match.group(1)

        # Extract individual fields from the raw block
        field_patterns = {
            "high": r'"highPrice"\s*:\s*(\d+(?:\.\d+)?)',
            "low": r'"lowPrice"\s*:\s*(\d+(?:\.\d+)?)',
            "close": r'"lastPrice"\s*:\s*(\d+(?:\.\d+)?)',
            "volume": r'"volume"\s*:\s*(\d+(?:\.\d+)?)',
            "open_interest": r'"openInterest"\s*:\s*(\d+(?:\.\d+)?)',
        }

        for field, pattern in field_patterns.items():
            match = re.search(pattern, raw_block)
            if match:
                try:
                    ohlc[field] = float(match.group(1))
                except (ValueError, IndexError):
                    ohlc[field] = None

        if ohlc.get("close"):
            logger.debug(
                f"Extracted from raw block: H={ohlc.get('high')} L={ohlc.get('low')} "
                f"C={ohlc.get('close')} V={ohlc.get('volume')} OI={ohlc.get('open_interest')}"
            )
            return ohlc

    # Fallback: try to find OHLC patterns directly in the decoded content
    logger.debug("Raw block not found, trying direct patterns...")

    direct_patterns = {
        "high": r'"highPrice"\s*:\s*(\d+(?:\.\d+)?)',
        "low": r'"lowPrice"\s*:\s*(\d+(?:\.\d+)?)',
        "close": r'"lastPrice"\s*:\s*(\d+(?:\.\d+)?)',
        "volume": r'"volume"\s*:\s*(\d+(?:\.\d+)?)',
        "open_interest": r'"openInterest"\s*:\s*(\d+(?:\.\d+)?)',
    }

    for field, pattern in direct_patterns.items():
        matches = re.findall(pattern, decoded_content)
        if matches:
            try:
                ohlc[field] = float(matches[0])
            except (ValueError, IndexError):
                ohlc[field] = None

    # Check if we have at least the close price
    if ohlc.get("close") is None:
        return None

    logger.debug(
        f"Extracted via fallback: H={ohlc.get('high')} L={ohlc.get('low')} "
        f"C={ohlc.get('close')} V={ohlc.get('volume')} OI={ohlc.get('open_interest')}"
    )
    return ohlc


def extract_implied_volatility(html_content: str) -> Optional[float]:
    """
    Extract Implied Volatility from volatility-greeks page.

    Args:
        html_content: HTML content from Barchart volatility-greeks page

    Returns:
        IV as float percentage, or None if extraction failed
    """
    decoded_content = html.unescape(html_content)

    # Try multiple patterns for IV extraction
    iv_patterns = [
        r'"impliedVolatility"\s*:\s*(\d+(?:\.\d+)?)',
        r'"iv"\s*:\s*(\d+(?:\.\d+)?)',
        r"Implied Volatility[^>]*>(\d+(?:\.\d+)?)%",
    ]

    for pattern in iv_patterns:
        match = re.search(pattern, decoded_content, re.IGNORECASE)
        if match:
            try:
                iv = float(match.group(1))
                logger.debug(f"Extracted IV: {iv}")
                return iv
            except (ValueError, IndexError):
                continue

    logger.warning("Could not extract Implied Volatility from page")
    return None


class BarchartScraper:
    """Scraper for Barchart.com London cocoa futures data using Playwright."""

    def __init__(self, headless: bool = True):
        """
        Initialize scraper.

        Args:
            headless: Run browser in headless mode (invisible)
        """
        self.headless = headless
        self.playwright = None
        self.browser = None
        self.page = None

    def __enter__(self):
        """Context manager entry."""
        self._launch_browser()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self._close_browser()

    def _launch_browser(self):
        """Launch Playwright browser."""
        logger.info("Launching Playwright browser...")
        self.playwright = sync_playwright().start()

        # Use WebKit (Safari engine) for macOS, Chromium for others
        import platform

        if platform.system() == "Darwin":
            self.browser = self.playwright.webkit.launch(headless=self.headless)
        else:
            self.browser = self.playwright.chromium.launch(headless=self.headless)

        self.page = self.browser.new_page()
        self.page.set_extra_http_headers({"User-Agent": USER_AGENT})
        logger.info("Browser launched successfully")

    def _close_browser(self):
        """Close Playwright browser."""
        if self.page:
            self.page.close()
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()
        logger.info("Browser closed")

    def _fetch_page(self, url: str) -> str:
        """
        Fetch page HTML using Playwright.

        Args:
            url: URL to fetch

        Returns:
            HTML content as string

        Raises:
            BarchartScraperError: If fetch fails
        """
        try:
            logger.info(f"Fetching {url}")
            self.page.goto(url, wait_until="load", timeout=BROWSER_TIMEOUT)
            self.page.wait_for_timeout(BROWSER_WAIT)  # Wait for content to load
            html_content = self.page.content()
            logger.info(f"Successfully fetched {url} ({len(html_content)} bytes)")
            return html_content
        except Exception as e:
            logger.error(f"Failed to fetch {url}: {e}")
            raise BarchartScraperError(f"Failed to fetch {url}: {e}") from e

    def scrape_prices(self) -> Dict[str, Optional[float]]:
        """
        Scrape OHLC + Volume + OI from prices page.

        Returns:
            Dict with price data fields
        """
        html = self._fetch_page(PRICES_URL)
        data = extract_ohlc_data(html)

        if not data:
            raise BarchartScraperError("Failed to extract OHLC data from prices page")

        # Volume conversion: Barchart shows contracts, we need tonnage (1 contract = 10 tonnes)
        if data.get("volume") is not None:
            data["volume"] = data["volume"] * 10
            logger.debug(f"Converted volume to tonnage: {data['volume']}")

        return data

    def scrape_implied_volatility(self) -> Optional[float]:
        """
        Scrape Implied Volatility from volatility-greeks page.

        Returns:
            IV as float percentage, or None if extraction failed
        """
        url = get_volatility_url()
        html = self._fetch_page(url)
        iv = extract_implied_volatility(html)

        if iv is None:
            logger.warning("Failed to extract Implied Volatility")

        return iv

    def scrape_all(self) -> Dict[str, Optional[float]]:
        """
        Scrape all 6 fields (OHLC + Volume + OI + IV).

        Returns:
            Dict with all data fields + timestamp
        """
        logger.info("Starting Barchart scrape for London cocoa (CC*0)")

        # Scrape prices page
        data = self.scrape_prices()

        # Scrape IV page
        data["implied_volatility"] = self.scrape_implied_volatility()

        # Add timestamp
        data["timestamp"] = datetime.now()

        logger.info(f"Scrape complete: {data}")
        return data
