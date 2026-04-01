"""Configuration for ICE Certified Cocoa Stocks scraper (Report 41)."""

# ICE public XLS download base URL
ICE_XLS_BASE_URL = "https://www.ice.com/publicdocs/futures_us_reports/cocoa"

# Validation range for certified stock total (bags)
VALIDATION_RANGE = (1_000, 10_000_000)

# HTTP settings
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
