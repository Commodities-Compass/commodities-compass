"""Orchestrator: fetch USD/EUR + GBP/EUR from ECB → compute 4 derived columns.

Pure-fetch + math logic, no DB writes. The DB layer (db_writer.py) is called
separately by main.py to keep the fetch testable in isolation (httpx mock).

Derived values (from docs/user-stories/P1-scraper-fx.md §3.2):
    fx_dxy_proxy = 1 / usd_per_eur          (rises when USD strengthens)
    fx_eurusd    = 1 / usd_per_eur          (alias of dxy_proxy, audit)
    fx_gbpusd    = usd_per_eur / gbp_per_eur (USD per 1 GBP)
    fx_gbpeur    = gbp_per_eur              (raw passthrough, audit)
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

import httpx

from scripts.fx_scraper.config import (
    DEFAULT_START_PERIOD,
    ECB_BASE,
    FETCH_TIMEOUT_SECONDS,
    GBP_EUR_SERIES,
    USD_EUR_SERIES,
    USER_AGENT,
)
from scripts.fx_scraper.parser import EcbObservation, parse_ecb_csv

logger = logging.getLogger(__name__)


class FxScraperError(RuntimeError):
    """Raised when the ECB fetch or parse fails.

    Fail-loud per ``.claude/rules/pipeline-error-handling.md`` — no auto-retry,
    no fallback source (yfinance / FRED / Stooq are NOT acceptable — see the
    R&D doc head for why they were rejected).
    """


@dataclass(frozen=True)
class FxRecord:
    """One day of derived FX values to UPSERT into pl_external_indicator.

    Any of the 4 columns may be ``None`` if the underlying series didn't have a
    value for that date (e.g. only USD/EUR published).
    """

    date: date
    fx_dxy_proxy: float | None
    fx_gbpusd: float | None
    fx_eurusd: float | None
    fx_gbpeur: float | None


def _fetch(series_key: str, start_period: str = DEFAULT_START_PERIOD) -> str:
    """HTTP GET ECB SDMX CSV; fail-loud on network/HTTP/empty errors."""
    url = f"{ECB_BASE}/{series_key}?format=csvdata&startPeriod={start_period}"
    logger.info("Fetching ECB series %s", series_key)

    try:
        response = httpx.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/csv"},
            timeout=FETCH_TIMEOUT_SECONDS,
            follow_redirects=True,
        )
    except httpx.HTTPError as exc:
        raise FxScraperError(f"Network error fetching {url}: {exc}") from exc

    if response.status_code != 200:
        raise FxScraperError(
            f"HTTP {response.status_code} fetching {url}: {response.text[:200]!r}"
        )

    body = response.text
    if not body.strip():
        raise FxScraperError(f"Empty body from {url}")

    return body


def _safe_divide(numerator: float, denominator: float | None) -> float | None:
    """Return numerator/denominator, or None if denominator is missing or ~0."""
    if denominator is None:
        return None
    if abs(denominator) < 1e-12:
        return None
    return numerator / denominator


def combine_to_fx_records(
    usd_eur: Iterable[EcbObservation],
    gbp_eur: Iterable[EcbObservation],
) -> list[FxRecord]:
    """Combine USD/EUR + GBP/EUR observations into FxRecord rows.

    Strategy: union of dates from both series. For each date:
      * usd_per_eur (if available) → fx_dxy_proxy, fx_eurusd
      * gbp_per_eur (if available) → fx_gbpeur
      * both available → fx_gbpusd = usd_per_eur / gbp_per_eur

    Returns FxRecord list sorted ascending by date. Dates where BOTH series are
    missing are not emitted at all.
    """
    usd_by_date: dict[date, float] = {o.date: o.value for o in usd_eur}
    gbp_by_date: dict[date, float] = {o.date: o.value for o in gbp_eur}
    all_dates = sorted(set(usd_by_date) | set(gbp_by_date))

    records: list[FxRecord] = []
    for d in all_dates:
        usd_per_eur = usd_by_date.get(d)
        gbp_per_eur = gbp_by_date.get(d)

        dxy_proxy = _safe_divide(1.0, usd_per_eur)
        eurusd = dxy_proxy  # same formula, kept as alias for audit
        gbpeur = gbp_per_eur

        if usd_per_eur is not None and gbp_per_eur is not None:
            gbpusd = _safe_divide(usd_per_eur, gbp_per_eur)
        else:
            gbpusd = None

        records.append(
            FxRecord(
                date=d,
                fx_dxy_proxy=dxy_proxy,
                fx_gbpusd=gbpusd,
                fx_eurusd=eurusd,
                fx_gbpeur=gbpeur,
            )
        )

    return records


def scrape_all() -> list[FxRecord]:
    """Fetch USD/EUR + GBP/EUR from ECB and combine into FxRecord list.

    Raises FxScraperError on any fetch, parse, or combine error. Returns at
    least one record on success; an empty result raises (defensive — masks
    NOAA-style format changes upstream).
    """
    usd_text = _fetch(USD_EUR_SERIES)
    usd_obs = parse_ecb_csv(usd_text)
    if not usd_obs:
        raise FxScraperError(
            f"ECB USD/EUR fetch returned no parseable rows ({USD_EUR_SERIES}). "
            "Check the source format or ECB outage."
        )
    logger.info(
        "USD/EUR: %d observations (%s → %s)",
        len(usd_obs),
        usd_obs[0].date,
        usd_obs[-1].date,
    )

    gbp_text = _fetch(GBP_EUR_SERIES)
    gbp_obs = parse_ecb_csv(gbp_text)
    if not gbp_obs:
        raise FxScraperError(
            f"ECB GBP/EUR fetch returned no parseable rows ({GBP_EUR_SERIES}). "
            "Check the source format or ECB outage."
        )
    logger.info(
        "GBP/EUR: %d observations (%s → %s)",
        len(gbp_obs),
        gbp_obs[0].date,
        gbp_obs[-1].date,
    )

    records = combine_to_fx_records(usd_obs, gbp_obs)
    logger.info("Combined %d FxRecord rows", len(records))
    return records
