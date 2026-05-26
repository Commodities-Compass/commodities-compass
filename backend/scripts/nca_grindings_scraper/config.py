"""Configuration constants for the NCA grindings scraper.

Source: National Confectioners Association (NCA) — North-American quarterly
cocoa grindings. Currently ~13 reporting plants. Supplied to ICE Futures US.

The list of all historical PDFs is served by Chocolate Council:
    https://chocolatecouncil.org/cocoa-grinds-report

PDFs live on candyusa.com WordPress uploads with INCONSISTENT filenames
(``Q1-2026-Cocoa-Grinds.pdf``, ``Q1_2025_Cocoa_Grinds_REV0421.pdf``,
``Q1_2023_CocoaGrinds_NCA.pdf``, etc.). The scraper therefore discovers the
canonical URL via the listing page rather than predicting it.
"""

from __future__ import annotations

LISTING_URL = "https://chocolatecouncil.org/cocoa-grinds-report"

FETCH_TIMEOUT_SECONDS = 60

USER_AGENT = "commodities-compass/nca-grindings-scraper (https://com-compass.com)"

# Source / category / region tags written to pl_supply_demand_observation.
SOURCE = "nca"
CATEGORY = "grindings"
REGION = "north_america"

# Metrics produced per PDF.
METRIC_VOLUME_TONNES = "volume_tonnes"
METRIC_YOY_PCT = "yoy_pct"

PARSER_VERSION = "1.0.0"
