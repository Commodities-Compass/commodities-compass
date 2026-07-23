"""Delayed price fetch — pure httpx, no browser (spike 2026-07-23).

Two-step against Barchart:
  1. GET the contract overview page → session cookies incl. XSRF-TOKEN.
  2. GET /proxies/core-api/v1/quotes/get with X-XSRF-TOKEN header and raw=1
     → numeric raw.lastPrice + raw.tradeTime (epoch, staleness signal).

Fail-loud on any drift (non-200, missing cookie, malformed payload,
out-of-range price). No retry, no fallback — Sentry + non-zero exit.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import unquote

import httpx

from scripts.intraday_monitor.config import (
    BARCHART_OVERVIEW_URL,
    BARCHART_QUOTES_API_URL,
    HTTP_TIMEOUT_SECONDS,
    PRICE_RANGE,
    USER_AGENT,
)

logger = logging.getLogger(__name__)

_PAGE_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_API_FIELDS = "symbol,lastPrice,highPrice,lowPrice,previousPrice,volume,tradeTime"


class IntradayFetchError(Exception):
    """Raised when the delayed quote cannot be fetched or validated."""


@dataclass(frozen=True)
class IntradayQuote:
    """One delayed observation of the front-month contract."""

    symbol: str
    last_price: Decimal
    trade_time: datetime | None
    observed_at: datetime


def fetch_delayed_quote(
    contract_code: str,
    transport: httpx.BaseTransport | None = None,
) -> IntradayQuote:
    """Fetch the delayed last price for ``contract_code`` from Barchart."""
    overview_url = BARCHART_OVERVIEW_URL.format(contract=contract_code)

    with httpx.Client(
        follow_redirects=True,
        timeout=HTTP_TIMEOUT_SECONDS,
        transport=transport,
    ) as client:
        page = client.get(overview_url, headers=_PAGE_HEADERS)
        if page.status_code != 200:
            raise IntradayFetchError(
                f"Overview page HTTP {page.status_code} for {contract_code}"
            )
        xsrf = client.cookies.get("XSRF-TOKEN")
        if not xsrf:
            raise IntradayFetchError(
                "No XSRF-TOKEN cookie from overview page — Barchart layout drift?"
            )

        api = client.get(
            BARCHART_QUOTES_API_URL,
            params={"symbols": contract_code, "fields": _API_FIELDS, "raw": "1"},
            headers={
                **_PAGE_HEADERS,
                "Accept": "application/json",
                "Referer": overview_url,
                "X-XSRF-TOKEN": unquote(xsrf),
            },
        )

    if api.status_code != 200:
        raise IntradayFetchError(f"core-api HTTP {api.status_code}")
    try:
        payload = api.json()
    except ValueError as exc:
        raise IntradayFetchError(f"core-api returned non-JSON body: {exc}") from exc

    quotes = payload.get("data") or []
    if not quotes:
        raise IntradayFetchError(f"core-api returned no quote for {contract_code}")

    raw = quotes[0].get("raw") or {}
    symbol = raw.get("symbol") or quotes[0].get("symbol") or ""
    if symbol != contract_code:
        raise IntradayFetchError(
            f"core-api returned symbol {symbol!r}, expected {contract_code!r}"
        )

    last_price_raw = raw.get("lastPrice")
    if not isinstance(last_price_raw, (int, float)):
        raise IntradayFetchError(
            f"raw.lastPrice missing/non-numeric: {last_price_raw!r}"
        )
    last_price = Decimal(str(last_price_raw))

    lo, hi = PRICE_RANGE
    if not (lo <= float(last_price) <= hi):
        raise IntradayFetchError(
            f"lastPrice {last_price} outside sanity range [{lo}, {hi}]"
        )

    trade_time: datetime | None = None
    trade_time_raw = raw.get("tradeTime")
    if isinstance(trade_time_raw, (int, float)) and trade_time_raw > 0:
        trade_time = datetime.fromtimestamp(int(trade_time_raw), tz=timezone.utc)

    quote = IntradayQuote(
        symbol=symbol,
        last_price=last_price,
        trade_time=trade_time,
        observed_at=datetime.now(timezone.utc),
    )
    logger.info(
        "Delayed quote %s: last=%s trade_time=%s",
        quote.symbol,
        quote.last_price,
        quote.trade_time,
    )
    return quote
