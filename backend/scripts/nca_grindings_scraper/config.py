"""Configuration constants for the NCA grindings scraper.

Source: National Confectioners Association (NCA) — North-American quarterly
cocoa grindings. Currently ~13 reporting plants. Supplied to ICE Futures US.

The listing of all historical PDFs is served by candyusa.com:
    https://candyusa.com/cocoa-grinds-report/

We target candyusa.com DIRECTLY (final canonical URL, skips 2 redirect hops).
The former host chocolatecouncil.org now only 302-redirects here and sits behind
a SiteGround anti-bot WAF that INTERMITTENTLY serves an HTTP 202 ``sgcaptcha``
challenge to datacenter / Cloud Run egress IPs (Sentry NcaScraperError,
2026-07-02: challenged one day, passed the next on the same NAT IP). candyusa.com
(Cloudflare) is permissive to datacenter IPs, so hitting it directly removes that
WAF from the path. Do NOT revert to chocolatecouncil.org.

PDFs live on candyusa.com WordPress uploads with INCONSISTENT filenames
(``Q1-2026-Cocoa-Grinds.pdf``, ``Q1_2025_Cocoa_Grinds_REV0421.pdf``,
``Q1_2023_CocoaGrinds_NCA.pdf``, etc.). The scraper therefore discovers the
canonical URL via the listing page rather than predicting it.
"""

from __future__ import annotations

LISTING_URL = "https://candyusa.com/cocoa-grinds-report/"

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
