"""Configuration for Barchart scraper."""

from datetime import datetime

# Barchart URLs
BARCHART_BASE_URL = "https://www.barchart.com/futures/quotes"
FRONT_MONTH_SYMBOL = "CC*0"  # London cocoa front-month continuous contract

# London cocoa front-month contract mapping (ICE expiries: March/May/Jul/Sep/Dec)
# Map: month → nearest expiry contract code prefix
LONDON_CONTRACT_MAP = {
    1: "CAH",  # Jan → March
    2: "CAH",  # Feb → March
    3: "CAK",  # Mar → May (after H expires)
    4: "CAK",  # Apr → May
    5: "CAN",  # May → July (after K expires)
    6: "CAN",  # Jun → July
    7: "CAU",  # Jul → September (after N expires)
    8: "CAU",  # Aug → September
    9: "CAZ",  # Sep → December (after U expires)
    10: "CAZ",  # Oct → December
    11: "CAZ",  # Nov → December
    12: "CAH",  # Dec → March next year (after Z expires)
}


def get_current_contract_code() -> str:
    """Get current front-month London cocoa contract code (e.g., CAK26)."""
    now = datetime.now()
    month = now.month
    year_suffix = str(now.year)[-2:]  # "26" from "2026"
    contract_prefix = LONDON_CONTRACT_MAP.get(month, "CAZ")
    return f"{contract_prefix}{year_suffix}"


# URLs
PRICES_URL = f"{BARCHART_BASE_URL}/{FRONT_MONTH_SYMBOL}/overview"


def get_volatility_url() -> str:
    """Get IV URL for current front-month contract."""
    contract = get_current_contract_code()
    return f"{BARCHART_BASE_URL}/{contract}/volatility-greeks?futuresOptionsView=merged"


# Google Sheets configuration
SPREADSHEET_ID = "16VXIrG9ybjjaorTeiR8sh5nrPIj9I7EFGr2iBSAjSSA"
SHEET_NAME_PRODUCTION = "TECHNICALS"
SHEET_NAME_STAGING = "TECHNICALS_STAGING"

# Column indices (0-based) in TECHNICALS sheet
# From daily-process-documentation.md Section 3.3
COLUMN_MAPPING = {
    "timestamp": 0,  # Column A
    "close": 1,  # Column B
    "high": 2,  # Column C
    "low": 3,  # Column D
    "volume": 4,  # Column E
    "open_interest": 5,  # Column F
    "implied_volatility": 6,  # Column G
}

# Validation ranges (from backend/scraper.py)
VALIDATION_RANGES = {
    "close": (1500.0, 20000.0),  # GBP/tonne
    "high": (1500.0, 20000.0),
    "low": (1500.0, 20000.0),
    "volume": (1, 500000),  # Contracts (after ×10 conversion to tonnes)
    "open_interest": (1, 1000000),  # Contracts
    "implied_volatility": (0.0, 200.0),  # Percentage (0-200%)
}

# Playwright browser settings
BROWSER_TIMEOUT = 60000  # 60 seconds
BROWSER_WAIT = 2000  # 2 seconds wait after page load
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Logging
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
