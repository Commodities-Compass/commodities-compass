"""Configuration constants for the FX scraper.

Source: ECB Statistical Data Warehouse (SDMX 2.1, free, no auth).
We fetch two daily series and compute four derived values:

    USD/EUR (USD per 1 EUR) — series D.USD.EUR.SP00.A
    GBP/EUR (GBP per 1 EUR) — series D.GBP.EUR.SP00.A

Derived:
    fx_dxy_proxy = 1 / usd_per_eur   (rises when USD strengthens)
    fx_eurusd    = 1 / usd_per_eur   (alias of dxy_proxy for audit)
    fx_gbpusd    = usd_per_eur / gbp_per_eur   (USD per 1 GBP)
    fx_gbpeur    = gbp_per_eur       (raw passthrough for audit)
"""

from __future__ import annotations

ECB_BASE = "https://data-api.ecb.europa.eu/service/data/EXR"

USD_EUR_SERIES = "D.USD.EUR.SP00.A"
GBP_EUR_SERIES = "D.GBP.EUR.SP00.A"

# ECB exposes a "startPeriod" filter — set to a generous lower bound; the
# scraper UPSERT semantics make it cheap to re-pull the full window each day.
DEFAULT_START_PERIOD = "2014-01-01"

FETCH_TIMEOUT_SECONDS = 60
USER_AGENT = "commodities-compass/fx-scraper (https://com-compass.com)"
