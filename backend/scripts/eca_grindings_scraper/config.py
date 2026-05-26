"""Configuration constants for the ECA grindings scraper.

Source: European Cocoa Association — public quarterly grindings statistics
compiled by Statser (Leusden, Netherlands). 19 reporting companies cover
Western Europe (~40% of world cocoa grindings).

URLs on the official site have INCONSISTENT suffixes (`-1`, `-2`, no suffix,
sometimes a year-month folder prefix). The scraper therefore discovers the
canonical PDF URL by scraping the listing page rather than predicting it.
"""

from __future__ import annotations

# Listing page that links to every quarterly PDF. Source of truth for URLs.
LISTING_URL = "https://www.eurococoa.com/grind-stats/"

# HTTP fetch timeout (seconds). Conservative — Eurococoa is sometimes slow
# when serving large PDFs.
FETCH_TIMEOUT_SECONDS = 60

# User-Agent: identifies our requests without being deceptive.
USER_AGENT = "commodities-compass/eca-grindings-scraper (https://com-compass.com)"

# Source / category / region tags written to pl_supply_demand_observation.
SOURCE = "eca"
CATEGORY = "grindings"
REGION = "europe"

# Metrics extracted per PDF.
METRIC_VOLUME_TONNES = "volume_tonnes"
METRIC_YOY_PCT = "yoy_pct"

# Parser version — bumped when the parser logic changes (stored in
# metadata_json so backfills can be selectively re-run for a parser version).
PARSER_VERSION = "1.0.0"
