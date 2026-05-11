"""Extended Open-Meteo fetcher for the backtest.

`scripts.meteo_agent.seasonal_memory.fetch_season_weather` only fetches the
three fields used by `compute_season_stats` (precip, et0, tmax). The backtest
also needs tmin, sunshine, and dominant wind direction for the cross-check
CSV — fetched here in a single call, in a shape that remains 100% compatible
with `compute_season_stats` (it only reads the three fields it cares about).
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import httpx

from scripts.meteo_agent.config import HTTP_TIMEOUT, LOCATIONS

logger = logging.getLogger(__name__)

OPEN_METEO_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"

EXTENDED_DAILY_PARAMS = (
    "precipitation_sum",
    "et0_fao_evapotranspiration",
    "temperature_2m_max",
    "temperature_2m_min",
    "sunshine_duration",
    "winddirection_10m_dominant",
)


class ArchiveFetchError(RuntimeError):
    """Raised when Open-Meteo archive returns a non-2xx response."""


def fetch_extended_season_weather(start_date: date, end_date: date) -> list[dict]:
    """Fetch extended daily weather (6 fields) for all locations from Open-Meteo Archive.

    The returned shape is identical to `fetch_season_weather`'s output — a list
    of dicts, one per location, each with a `daily` block. The only difference
    is that `daily` now contains 6 series instead of 3. Fully compatible with
    `compute_season_stats`, which reads only the 3 fields it needs.

    Caps end_date to today-5d (archive publication lag). Raises if the resulting
    range is empty (start_date > capped end_date).
    """
    today = date.today()
    capped_end = min(end_date, today - timedelta(days=5))
    if capped_end < start_date:
        raise ArchiveFetchError(
            f"Archive range empty after lag cap: start={start_date}, "
            f"end={end_date}, capped_end={capped_end}. "
            "Backtest target date is too recent for archive coverage."
        )

    latitudes = ",".join(str(loc.latitude) for loc in LOCATIONS)
    longitudes = ",".join(str(loc.longitude) for loc in LOCATIONS)
    daily = ",".join(EXTENDED_DAILY_PARAMS)

    url = (
        f"{OPEN_METEO_ARCHIVE}"
        f"?latitude={latitudes}"
        f"&longitude={longitudes}"
        f"&daily={daily}"
        f"&start_date={start_date.isoformat()}"
        f"&end_date={capped_end.isoformat()}"
        f"&timezone=auto"
    )

    logger.info(
        "Fetching extended weather %s → %s (capped from %s)",
        start_date,
        capped_end,
        end_date,
    )
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        response = client.get(url)
        response.raise_for_status()

    data = response.json()
    return data if isinstance(data, list) else [data]
