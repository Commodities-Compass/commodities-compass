"""Configuration constants for the ICE COT EU scraper.

Source: ICE public CSV (free, no auth).
  URL template: https://www.theice.com/publicdocs/futures/COTHistYYYY.csv

One file per calendar year, ~52 weeks × 5 markets per file. We filter for
'ICE Cocoa Futures - ICE Futures Europe' + FutOnly variant.
"""

from __future__ import annotations

ICE_COT_HISTORY_URL_TEMPLATE = (
    "https://www.theice.com/publicdocs/futures/COTHist{year}.csv"
)

# Exact filter strings from the CSV. Keep these tight — any drift in ICE's
# naming format must fail-loud (in scraper.py) rather than silently match
# nothing.
COCOA_EU_MARKET_NAME = "ICE Cocoa Futures - ICE Futures Europe"
FUT_ONLY_VARIANT = "FutOnly"

# Conventional ICE publication lag: snapshot is Tuesday, published Friday.
RELEASE_LAG_DAYS = 3

# HTTP fetch timeout (seconds).
FETCH_TIMEOUT_SECONDS = 60
USER_AGENT = "commodities-compass/ice-cot-eu-scraper (https://com-compass.com)"

# Default contract_market value. The schema supports multi-market (sugar,
# coffee) but for MVP we only scrape cocoa.
DEFAULT_CONTRACT_MARKET = "cocoa"
