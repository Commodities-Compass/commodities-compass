"""Open-Meteo API weather data fetcher for cocoa-growing regions."""

import json
import logging

import httpx

from scripts.meteo_agent.config import (
    DAILY_PARAMS,
    FORECAST_DAYS,
    HOURLY_PARAMS,
    HTTP_TIMEOUT,
    LOCATIONS,
    PAST_DAYS,
)

logger = logging.getLogger(__name__)

OPEN_METEO_BASE = "https://api.open-meteo.com/v1/forecast"


class WeatherFetcherError(Exception):
    pass


def _build_url() -> str:
    """Build Open-Meteo API URL from configured locations and parameters."""
    latitudes = ",".join(str(loc.latitude) for loc in LOCATIONS)
    longitudes = ",".join(str(loc.longitude) for loc in LOCATIONS)
    daily = ",".join(DAILY_PARAMS)
    hourly = ",".join(HOURLY_PARAMS)
    return (
        f"{OPEN_METEO_BASE}"
        f"?latitude={latitudes}"
        f"&longitude={longitudes}"
        f"&daily={daily}"
        f"&hourly={hourly}"
        f"&past_days={PAST_DAYS}"
        f"&forecast_days={FORECAST_DAYS}"
    )


def _annotate_with_location_names(raw_data: list[dict]) -> list[dict]:
    """Add location names to Open-Meteo response arrays.

    Open-Meteo returns indexed arrays without location names.
    We inject name/country for LLM clarity.
    """
    annotated = []
    for i, entry in enumerate(raw_data):
        loc = LOCATIONS[i] if i < len(LOCATIONS) else None
        enriched = dict(entry)
        if loc:
            enriched["location_name"] = loc.name
            enriched["country"] = loc.country
        annotated.append(enriched)
    return annotated


def fetch_weather() -> str:
    """Fetch weather data from Open-Meteo API for all 6 locations.

    Returns:
        Formatted JSON string with location names injected.

    Raises:
        WeatherFetcherError: On API call failure or empty response.
    """
    url = _build_url()
    logger.info("Fetching Open-Meteo data for %d locations...", len(LOCATIONS))
    logger.debug("URL: %s", url)

    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            response = client.get(url)
            response.raise_for_status()
    except httpx.TimeoutException as e:
        raise WeatherFetcherError(
            f"Open-Meteo API timeout after {HTTP_TIMEOUT}s"
        ) from e
    except httpx.HTTPStatusError as e:
        raise WeatherFetcherError(
            f"Open-Meteo API error: HTTP {e.response.status_code}"
        ) from e
    except httpx.HTTPError as e:
        raise WeatherFetcherError(f"Open-Meteo API request failed: {e}") from e

    data = response.json()

    # Open-Meteo returns a list of objects when querying multiple locations
    if isinstance(data, list):
        annotated = _annotate_with_location_names(data)
    elif isinstance(data, dict):
        # Single location fallback (shouldn't happen with 6 coords)
        annotated = _annotate_with_location_names([data])
    else:
        raise WeatherFetcherError(f"Unexpected API response type: {type(data)}")

    formatted = json.dumps(annotated, indent=2, ensure_ascii=False)
    logger.info(
        "Open-Meteo: received data for %d locations (%d chars)",
        len(annotated),
        len(formatted),
    )
    return formatted
