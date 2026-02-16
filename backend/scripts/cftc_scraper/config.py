"""Configuration for CFTC scraper."""

# CFTC URLs and codes
CFTC_BASE_URL = "https://www.cftc.gov/dea/futures"
AGRICULTURE_URL = f"{CFTC_BASE_URL}/ag_lf.htm"
COCOA_CODE = "073732"
COCOA_PATTERN = r"COCOA - ICE FUTURES U\.S\."

# Google Sheets configuration
SPREADSHEET_ID = "16VXIrG9ybjjaorTeiR8sh5nrPIj9I7EFGr2iBSAjSSA"
SHEET_NAME_PRODUCTION = "TECHNICALS"
SHEET_NAME_STAGING = "TECHNICALS_STAGING"

# Column configuration
COM_NET_US_COLUMN_INDEX = 8  # Column I (0-based)

# Validation ranges
VALIDATION_RANGE = (-100000, 100000)  # COM NET US range

# Logging
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
