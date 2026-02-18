"""Barchart.com scraper for London cocoa futures data.

Uses Playwright XHR interception to capture API response data directly,
eliminating the fragile regex-based HTML parsing that caused incorrect
data extraction (wrong raw block matched → garbage V/OI values).

Fallback: if no XHR captured, parses rendered HTML picking the data block
with highest volume (main contract always has the most volume).
"""

import html
import logging
import platform
import re
from datetime import datetime
from typing import Any

from playwright.sync_api import Response, sync_playwright

from scripts.barchart_scraper.config import (
    BROWSER_TIMEOUT,
    USER_AGENT,
    get_current_contract_code,
    get_prices_url,
    get_volatility_url,
)

logger = logging.getLogger(__name__)


class BarchartScraperError(Exception):
    pass


# ---------------------------------------------------------------------------
# JSON helpers for XHR interception
# ---------------------------------------------------------------------------


def _find_quote_in_json(data: Any) -> dict | None:
    """Recursively search a parsed JSON structure for a dict with OHLCV fields."""
    if isinstance(data, dict):
        if all(k in data for k in ("lastPrice", "highPrice", "lowPrice")):
            return data
        for value in data.values():
            result = _find_quote_in_json(value)
            if result:
                return result
    elif isinstance(data, list):
        for item in data:
            result = _find_quote_in_json(item)
            if result:
                return result
    return None


def _find_iv_in_json(data: Any) -> float | None:
    """Recursively search for impliedVolatility in parsed JSON."""
    if isinstance(data, dict):
        if "impliedVolatility" in data:
            try:
                return float(data["impliedVolatility"])
            except (ValueError, TypeError):
                pass
        for value in data.values():
            result = _find_iv_in_json(value)
            if result is not None:
                return result
    elif isinstance(data, list):
        for item in data:
            result = _find_iv_in_json(item)
            if result is not None:
                return result
    return None


def _safe_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# HTML fallback extractors (used only when XHR interception captures nothing)
# ---------------------------------------------------------------------------

_FIELD_PATTERNS = {
    "close": r'"lastPrice"\s*:\s*(\d+(?:\.\d+)?)',
    "high": r'"highPrice"\s*:\s*(\d+(?:\.\d+)?)',
    "low": r'"lowPrice"\s*:\s*(\d+(?:\.\d+)?)',
    "volume": r'"volume"\s*:\s*(\d+(?:\.\d+)?)',
    "open_interest": r'"openInterest"\s*:\s*(\d+(?:\.\d+)?)',
}


def _extract_ohlc_from_html(html_content: str) -> dict[str, float | None]:
    """Fallback: find ALL raw blocks in HTML and pick the one with highest volume.

    The old approach took the FIRST raw block, which often matched option chains
    or related contracts instead of the main quote → garbage data.
    """
    decoded = html.unescape(html_content)

    # Find all "raw" blocks containing at least lastPrice
    raw_blocks = list(re.finditer(r'"raw"\s*:\s*\{([^}]{50,})\}', decoded))

    best: dict[str, float | None] | None = None
    best_volume = -1.0

    for block_match in raw_blocks:
        block = block_match.group(1)
        close_m = re.search(_FIELD_PATTERNS["close"], block)
        if not close_m:
            continue

        candidate: dict[str, float | None] = {}
        for field, pattern in _FIELD_PATTERNS.items():
            m = re.search(pattern, block)
            candidate[field] = float(m.group(1)) if m else None

        vol = candidate.get("volume") or 0.0
        if vol > best_volume:
            best_volume = vol
            best = candidate

    if best:
        logger.info(
            f"HTML fallback (best of {len(raw_blocks)} blocks): "
            f"C={best.get('close')} V={best.get('volume')} OI={best.get('open_interest')}"
        )
        return best

    logger.warning("HTML fallback: no raw blocks found, trying direct field search")
    # Last resort: take the LAST occurrence of each field (more likely to be main quote)
    result: dict[str, float | None] = {}
    for field, pattern in _FIELD_PATTERNS.items():
        matches = re.findall(pattern, decoded)
        result[field] = float(matches[-1]) if matches else None

    return result


def _extract_iv_from_html(html_content: str) -> float | None:
    """Fallback: extract IV from rendered HTML via regex."""
    decoded = html.unescape(html_content)
    patterns = [
        r'"impliedVolatility"\s*:\s*(\d+(?:\.\d+)?)',
        r'"iv"\s*:\s*(\d+(?:\.\d+)?)',
        r"Implied Volatility[^>]*>(\d+(?:\.\d+)?)%",
    ]
    for pattern in patterns:
        match = re.search(pattern, decoded, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except (ValueError, IndexError):
                continue
    return None


# ---------------------------------------------------------------------------
# Main scraper class
# ---------------------------------------------------------------------------


class BarchartScraper:
    """Scraper using Playwright XHR interception for reliable data extraction."""

    def __init__(self, headless: bool = True):
        self.headless = headless
        self.playwright = None
        self.browser = None
        self.page = None

    def __enter__(self):
        self._launch_browser()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._close_browser()

    def _launch_browser(self):
        logger.info("Launching Playwright browser...")
        self.playwright = sync_playwright().start()
        if platform.system() == "Darwin":
            self.browser = self.playwright.webkit.launch(headless=self.headless)
        else:
            self.browser = self.playwright.chromium.launch(headless=self.headless)
        self.page = self.browser.new_page()
        self.page.set_extra_http_headers({"User-Agent": USER_AGENT})
        logger.info("Browser launched successfully")

    def _close_browser(self):
        if self.page:
            self.page.close()
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()
        logger.info("Browser closed")

    # ------------------------------------------------------------------
    # XHR interception
    # ------------------------------------------------------------------

    def _navigate_and_capture(self, url: str, extractor) -> list:
        """Navigate to URL, intercept JSON responses, apply extractor to each.

        Args:
            url: Page URL to load.
            extractor: Callable(json_body) → value | None.

        Returns:
            List of non-None extracted values.
        """
        captured: list = []

        def on_response(response: Response):
            if response.status != 200:
                return
            content_type = response.headers.get("content-type", "")
            if "json" not in content_type:
                return
            try:
                body = response.json()
                result = extractor(body)
                if result is not None:
                    logger.debug(f"XHR match from {response.url}")
                    captured.append(result)
            except Exception:
                pass

        self.page.on("response", on_response)
        try:
            logger.info(f"Fetching {url}")
            self.page.goto(url, wait_until="load", timeout=BROWSER_TIMEOUT)
            # Wait for XHR calls to complete (Barchart never reaches networkidle
            # due to analytics/ad polling, so we use a fixed wait after load)
            self.page.wait_for_timeout(5000)
        except Exception as e:
            # If we already captured data before timeout, don't fail
            if captured:
                logger.warning("Page timeout but XHR data captured — continuing")
            else:
                raise BarchartScraperError(f"Failed to fetch {url}: {e}") from e
        finally:
            self.page.remove_listener("response", on_response)

        return captured

    # ------------------------------------------------------------------
    # Public scrape methods
    # ------------------------------------------------------------------

    def scrape_prices(self) -> dict[str, float | None]:
        """Scrape OHLC + Volume + OI.

        Strategy: Barchart's XHR API omits openInterest, but the server-rendered
        HTML contains inline JSON raw blocks with ALL fields. So:
          1. Primary: extract from rendered HTML (max-volume raw block → complete data)
          2. Backup: XHR-captured data for C/H/L/V (no OI)
        """
        # Navigate + capture XHR (as backup)
        prices_url = get_prices_url()
        captured = self._navigate_and_capture(prices_url, _find_quote_in_json)

        # Primary: extract from rendered HTML (has OI)
        html_content = self.page.content()
        data = _extract_ohlc_from_html(html_content)

        # If HTML extraction got a close price, use it
        if data.get("close") is not None:
            logger.info("Using HTML-extracted data (complete with OI)")
        elif captured:
            # Fallback: use XHR data (no OI)
            quote = captured[0]
            raw = quote.get("raw", quote)
            logger.warning("HTML extraction failed — using XHR data (no OI)")
            data = {
                "close": _safe_float(raw.get("lastPrice")),
                "high": _safe_float(raw.get("highPrice")),
                "low": _safe_float(raw.get("lowPrice")),
                "volume": _safe_float(raw.get("volume")),
                "open_interest": None,
            }
        else:
            raise BarchartScraperError("Failed to extract data from both HTML and XHR")

        if data.get("close") is None:
            raise BarchartScraperError("Close price is None after extraction")

        logger.info(
            f"Prices: C={data['close']} H={data.get('high')} L={data.get('low')} "
            f"V={data.get('volume')} OI={data.get('open_interest')}"
        )
        return data

    def scrape_implied_volatility(self) -> float | None:
        """Scrape IV. XHR interception → HTML fallback."""
        url = get_volatility_url()
        logger.info(f"IV contract: {url.split('/quotes/')[1].split('/')[0]}")

        captured = self._navigate_and_capture(url, _find_iv_in_json)

        if captured:
            logger.info(f"IV from XHR: {captured[0]}")
            return captured[0]

        logger.warning("No IV from XHR — falling back to HTML regex")
        html_content = self.page.content()
        iv = _extract_iv_from_html(html_content)
        if iv is not None:
            logger.info(f"IV from HTML fallback: {iv}")
        else:
            logger.warning("Failed to extract IV from both XHR and HTML")
        return iv

    def scrape_all(self) -> dict:
        """Scrape all 6 fields (OHLC + Volume + OI + IV)."""
        contract = get_current_contract_code()
        logger.info(f"Starting Barchart scrape for London cocoa #7 ({contract})")
        data = self.scrape_prices()
        data["implied_volatility"] = self.scrape_implied_volatility()
        data["timestamp"] = datetime.now()
        logger.info(f"Scrape complete: {data}")
        return data
