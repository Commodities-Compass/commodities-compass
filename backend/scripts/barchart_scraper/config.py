"""Configuration for Barchart scraper."""

import os

# Barchart URLs
BARCHART_BASE_URL = "https://www.barchart.com/futures/quotes"

# Active contract code (e.g., CAK26) — set via env var, no auto-roll.
# Delivery months: H(Mar), K(May), N(Jul), U(Sep), Z(Dec)
ACTIVE_CONTRACT = os.getenv("ACTIVE_CONTRACT", "")


def get_current_contract_code() -> str:
    """Return the active contract code from ACTIVE_CONTRACT env var."""
    if not ACTIVE_CONTRACT:
        raise RuntimeError(
            "ACTIVE_CONTRACT env var not set. "
            "Set it to the current contract code (e.g., CAK26)."
        )
    return ACTIVE_CONTRACT


def get_prices_url() -> str:
    contract = get_current_contract_code()
    return f"{BARCHART_BASE_URL}/{contract}/overview"


def get_volatility_url() -> str:
    contract = get_current_contract_code()
    return f"{BARCHART_BASE_URL}/{contract}/volatility-greeks?futuresOptionsView=merged"


# Google Sheets configuration
SPREADSHEET_ID = "16VXIrG9ybjjaorTeiR8sh5nrPIj9I7EFGr2iBSAjSSA"
SHEET_NAME_PRODUCTION = "TECHNICALS"
SHEET_NAME_STAGING = "TECHNICALS_STAGING"

# Column indices (0-based) in TECHNICALS sheet
COLUMN_MAPPING = {
    "timestamp": 0,  # Column A
    "close": 1,  # Column B
    "high": 2,  # Column C
    "low": 3,  # Column D
    "volume": 4,  # Column E
    "open_interest": 5,  # Column F
    "implied_volatility": 6,  # Column G
}

# Validation ranges
VALIDATION_RANGES = {
    "close": (1500.0, 20000.0),  # GBP/tonne
    "high": (1500.0, 20000.0),
    "low": (1500.0, 20000.0),
    "volume": (1, 500000),  # Contracts
    "open_interest": (1, 1000000),  # Contracts
    "implied_volatility": (0.0, 200.0),  # Percentage (0-200%)
}

# Playwright browser settings
BROWSER_TIMEOUT = 60000  # 60 seconds
BROWSER_WAIT = 2000  # 2 seconds wait after page load
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Logging
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
