"""Configuration for CFTC scraper."""

# CFTC URLs and codes
CFTC_BASE_URL = "https://www.cftc.gov/dea/futures"
AGRICULTURE_URL = f"{CFTC_BASE_URL}/ag_lf.htm"
COCOA_CODE = "073732"
COCOA_PATTERN = r"COCOA - ICE FUTURES U\.S\."

# Validation ranges
VALIDATION_RANGE = (-100000, 100000)  # COM NET US range
