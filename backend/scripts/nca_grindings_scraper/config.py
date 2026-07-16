"""Configuration constants for the NCA grindings scraper.

Source: National Confectioners Association (NCA) — North-American quarterly
cocoa grindings. Currently ~13 reporting plants. Supplied to ICE Futures US.

The listing of all historical PDFs is served by candyusa.com:
    https://candyusa.com/cocoa-grinds-report/

WAF history — why we fetch through a headless browser
-----------------------------------------------------
candyusa.com sits behind a SiteGround anti-bot WAF that serves an HTTP 202
``sgcaptcha`` JS-challenge to datacenter / Cloud Run egress IPs. Residential IPs
pass with plain httpx; Cloud Run does not (Sentry ``NcaScraperError`` HTTP 202,
2026-07-09/10). The challenge is IP-reputation based, not User-Agent based (the
identifying bot UA passes fine from a residential IP), so swapping the host or
the UA does not help — chocolatecouncil.org (the former listing host, now a 302
to here) has the same posture.

The durable fix is to execute the challenge JS in a real headless browser
(Playwright/Chromium), which receives the clearance cookie and can then load the
listing HTML and download the PDFs through the same browser context. Plain httpx
has no JS engine and cannot pass. See ``browser.py``. History: chocolatecouncil.org
WAF → candyusa.com direct (PR #57, assumed Cloudflare-permissive — wrong, it is
SiteGround/nginx) → Playwright.

PDFs live on candyusa.com WordPress uploads with INCONSISTENT filenames
(``Q1-2026-Cocoa-Grinds.pdf``, ``Q1_2025_Cocoa_Grinds_REV0421.pdf``,
``Q1_2023_CocoaGrinds_NCA.pdf``, etc.). The scraper therefore discovers the
canonical URL via the listing page rather than predicting it.
"""

from __future__ import annotations

LISTING_URL = "https://candyusa.com/cocoa-grinds-report/"

# Per-navigation / per-request budget for the headless browser (ms).
BROWSER_TIMEOUT_MS = 60_000

# Identity string, kept for reference / logging. NOT forced onto the browser:
# the sgcaptcha WAF is IP-reputation based, and a real (default) Chromium UA
# maximises the odds the JS-challenge clears — a "bot" UA on a real browser can
# only hurt.
USER_AGENT = "commodities-compass/nca-grindings-scraper (https://com-compass.com)"

# Source / category / region tags written to pl_supply_demand_observation.
SOURCE = "nca"
CATEGORY = "grindings"
REGION = "north_america"

# Metrics produced per PDF.
METRIC_VOLUME_TONNES = "volume_tonnes"
METRIC_YOY_PCT = "yoy_pct"

PARSER_VERSION = "1.0.0"
