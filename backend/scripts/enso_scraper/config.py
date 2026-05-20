"""Configuration constants for the ENSO scraper.

Source: NOAA Physical Sciences Laboratory (free, no auth, no rate limit).
"""

from __future__ import annotations

# NOAA PSL URLs — plain ASCII format, parser stops at first non-numeric year row.
ONI_URL = "https://psl.noaa.gov/data/correlation/oni.data"
NINO34_URL = "https://psl.noaa.gov/data/correlation/nina34.anom.data"

# HTTP fetch timeout (seconds). Conservative — NOAA is sometimes slow.
FETCH_TIMEOUT_SECONDS = 60

# User-Agent: identifies our requests for NOAA logging without being deceptive.
USER_AGENT = "commodities-compass/enso-scraper (https://com-compass.com)"

# Value names accepted in EnsoRecord — keep in sync with the DB column mapping
# in db_writer.py:_VALUE_NAME_TO_COLUMN.
VALUE_NAME_ONI = "oni"
VALUE_NAME_NINO34 = "nino34_anomaly"
