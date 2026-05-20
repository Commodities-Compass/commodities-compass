"""Configuration constants for the Barchart cmdty Stock EU scraper.

Source: Barchart commodity statistics public page (no auth required).
  URL: https://www.barchart.com/cmdty/data/fundamental/explore/IC345DRW.CS

The page is server-rendered HTML; data lives in two tables of class
``cmdty-quote-table``:

  * Table 1: metadata (Most Recent Value/Date, Frequency, Unit, ...).
  * Table 2: 7-day history (date → value).

Unit is natively "60 Kg Bag" (no conversion needed at write time).
Multiplier is natively 1. Both are validated in the parser — any drift
fails-loud.
"""

from __future__ import annotations

BARCHART_STOCKS_EU_URL = (
    "https://www.barchart.com/cmdty/data/fundamental/explore/IC345DRW.CS"
)

# Use a realistic browser User-Agent — Barchart rejects bare httpx UA.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

FETCH_TIMEOUT_SECONDS = 60

# What the page must say for the scraper to trust the value. If Barchart
# ever changes the unit / multiplier the scraper fails-loud rather than
# silently corrupting data.
EXPECTED_UNIT = "60 Kg Bag"
EXPECTED_MULTIPLIER = "1"
