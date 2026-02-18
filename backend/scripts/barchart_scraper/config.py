"""Configuration for Barchart scraper."""

import calendar
from datetime import date, timedelta

# Barchart URLs
BARCHART_BASE_URL = "https://www.barchart.com/futures/quotes"
FRONT_MONTH_SYMBOL = (
    "CA*0"  # Barchart continuous symbol (used only for logging/reference, not for URLs)
)

# ICE London cocoa #7 contract months: H(Mar), K(May), N(Jul), U(Sep), Z(Dec)
# Expiry ≈ last business day of the delivery month
CONTRACT_MONTHS = [
    ("H", 3),  # March
    ("K", 5),  # May
    ("N", 7),  # July
    ("U", 9),  # September
    ("Z", 12),  # December
]

# Roll to next contract 15 days before expiry to avoid near-expiry bias
ROLL_DAYS_BEFORE_EXPIRY = 15


def _last_business_day(year: int, month: int) -> date:
    """Last weekday of a given month."""
    last_day = calendar.monthrange(year, month)[1]
    d = date(year, month, last_day)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def get_current_contract_code() -> str:
    """Get front-month London cocoa contract code, rolling 15 days before expiry.

    Example: on March 10 returns 'CAH26', on March 17 returns 'CAK26'
    (because CAH26 expires ~March 31, roll date ~March 16).
    """
    today = date.today()

    # Build schedule for current year + next year (covers Dec→Mar roll)
    schedule: list[tuple[str, date]] = []
    for year in (today.year, today.year + 1):
        suffix = str(year)[-2:]
        for code, month in CONTRACT_MONTHS:
            expiry = _last_business_day(year, month)
            roll = expiry - timedelta(days=ROLL_DAYS_BEFORE_EXPIRY)
            schedule.append((f"CA{code}{suffix}", roll))

    for contract_code, roll_date in schedule:
        if today < roll_date:
            return contract_code

    return schedule[-1][0]


# URLs — both use our 15-day roll logic, never Barchart's CA*0 alias
def get_prices_url() -> str:
    """Get prices URL for current front-month contract (with 15-day roll)."""
    contract = get_current_contract_code()
    return f"{BARCHART_BASE_URL}/{contract}/overview"


def get_volatility_url() -> str:
    """Get IV URL for current front-month contract (with 15-day roll)."""
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
    "volume": (1, 500000),  # Contracts
    "open_interest": (1, 1000000),  # Contracts
    "implied_volatility": (0.0, 200.0),  # Percentage (0-200%)
}

# Playwright browser settings
BROWSER_TIMEOUT = 60000  # 60 seconds
BROWSER_WAIT = 2000  # 2 seconds wait after page load
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Logging
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
