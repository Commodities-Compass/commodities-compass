"""Delayed price fetch — one contract overview page, read through the WAF.

The last price comes from the server-rendered inline JSON ``"raw"`` block,
selected by exact symbol match. Parsing (``parse_delayed_quote``) is pure and
holds every rule; fetching only wires a transport to it — Barchart changed
its posture twice in three days and the split keeps the blast radius in one
function:

  2026-09-01  CloudFront ``public, s-maxage=300`` stripped ``Set-Cookie``, so
              the ``core-api`` XSRF token became unobtainable → read the HTML.
  2026-09-03  AWS WAF JS challenge (HTTP 202) → httpx cannot pass it at all;
              transport moved to a headless browser. Parser untouched.

Staleness to keep in mind: Barchart's own delay is ~10-12 min, and the page
may be CDN-cached up to 300s on top. ``trade_time`` carries the real age and
is logged on every run.

Fail-loud on any drift (WAF not cleared, no block for the contract, malformed
payload, out-of-range price). No retry, no fallback — Sentry + non-zero exit.
"""

from __future__ import annotations

import html
import json
import logging
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from scripts._shared.barchart_browser import BarchartBrowser, BarchartWafError
from scripts.intraday_monitor.config import (
    BARCHART_OVERVIEW_URL,
    PRICE_RANGE,
)

logger = logging.getLogger(__name__)

# The overview page embeds one such object per quoted symbol. Only the block
# whose "symbol" matches the contract we asked for is ours — never the first
# one found (that is Bug 1 of the daily scraper, see barchart_scraper/README).
_RAW_BLOCK_RE = re.compile(r'"raw"\s*:\s*\{')

# A raw block runs ~540 chars. The cap bounds the brace scan if the page is
# truncated mid-object rather than letting it walk the whole document.
_MAX_BLOCK_CHARS = 8192


class IntradayFetchError(Exception):
    """Raised when the delayed quote cannot be fetched or validated."""


@dataclass(frozen=True)
class IntradayQuote:
    """One delayed observation of the front-month contract."""

    symbol: str
    last_price: Decimal
    trade_time: datetime | None
    observed_at: datetime


def _extract_json_object(text: str, start: int) -> str | None:
    """Return the JSON object literal starting at ``start`` (a ``{``).

    Brace counting that honours string literals and their escapes — a naive
    ``[^}]*`` regex truncates on any nested object.
    """
    depth = 0
    in_string = False
    escaped = False
    end = min(len(text), start + _MAX_BLOCK_CHARS)

    for i in range(start, end):
        char = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _iter_raw_blocks(page_text: str) -> Iterator[dict[str, Any]]:
    """Yield every parseable inline ``"raw"`` object on the page."""
    for match in _RAW_BLOCK_RE.finditer(page_text):
        literal = _extract_json_object(page_text, match.end() - 1)
        if literal is None:
            continue
        try:
            block = json.loads(literal)
        except ValueError:
            continue
        if isinstance(block, dict):
            yield block


def _select_block(page_text: str, contract_code: str) -> dict[str, Any]:
    """Return the raw block for ``contract_code``, or fail loud.

    The page carries ~18 raw blocks: three identical ones for the quoted
    contract and a dozen symbol-less ones for the sidebar widgets (other
    markets, at other prices). Selection is an exact symbol match — never
    "the first block with a lastPrice", which is how the daily scraper once
    published an option chain as the front-month close.

    The duplicates agree today. If they ever stop agreeing, first-match would
    be a coin flip, so a divergence is an error rather than a silent pick.
    """
    matches: list[dict[str, Any]] = []
    seen: list[str] = []
    for block in _iter_raw_blocks(page_text):
        symbol = block.get("symbol")
        if symbol == contract_code:
            matches.append(block)
        elif isinstance(symbol, str):
            seen.append(symbol)

    if not matches:
        raise IntradayFetchError(
            f"No inline quote block for {contract_code} "
            f"(found: {seen or 'none'}) — Barchart layout drift?"
        )

    prices = {repr(block.get("lastPrice")) for block in matches}
    if len(prices) > 1:
        raise IntradayFetchError(
            f"{len(matches)} inline blocks for {contract_code} disagree on "
            f"lastPrice: {sorted(prices)} — refusing to guess"
        )
    return matches[0]


def _parse_last_price(block: dict[str, Any]) -> Decimal:
    """Validate and convert ``raw.lastPrice`` into a Decimal."""
    raw_price = block.get("lastPrice")
    if isinstance(raw_price, bool) or not isinstance(raw_price, (int, float)):
        raise IntradayFetchError(f"raw.lastPrice missing/non-numeric: {raw_price!r}")

    try:
        last_price = Decimal(str(raw_price))
    except InvalidOperation as exc:  # pragma: no cover — guarded by isinstance
        raise IntradayFetchError(f"raw.lastPrice unconvertible: {raw_price!r}") from exc

    lo, hi = PRICE_RANGE
    if not (lo <= float(last_price) <= hi):
        raise IntradayFetchError(
            f"lastPrice {last_price} outside sanity range [{lo}, {hi}]"
        )
    return last_price


def _parse_trade_time(block: dict[str, Any]) -> datetime | None:
    """Convert ``raw.tradeTime`` (epoch seconds) to UTC, or None if absent."""
    raw_time = block.get("tradeTime")
    if isinstance(raw_time, bool) or not isinstance(raw_time, (int, float)):
        return None
    if raw_time <= 0:
        return None
    return datetime.fromtimestamp(int(raw_time), tz=timezone.utc)


def parse_delayed_quote(page_html: str, contract_code: str) -> IntradayQuote:
    """Turn an overview page into a validated quote. Pure — no I/O."""
    page_text = html.unescape(page_html)
    block = _select_block(page_text, contract_code)

    observed_at = datetime.now(timezone.utc)
    quote = IntradayQuote(
        symbol=contract_code,
        last_price=_parse_last_price(block),
        trade_time=_parse_trade_time(block),
        observed_at=observed_at,
    )

    age = (
        f"{(observed_at - quote.trade_time).total_seconds():.0f}s"
        if quote.trade_time
        else "unknown"
    )
    logger.info(
        "Delayed quote %s: last=%s trade_time=%s (age %s)",
        quote.symbol,
        quote.last_price,
        quote.trade_time,
        age,
    )
    return quote


def fetch_delayed_quote(
    contract_code: str,
    fetch_html: Callable[[str], str] | None = None,
) -> IntradayQuote:
    """Fetch the delayed last price for ``contract_code`` from Barchart.

    ``fetch_html`` is injected by the tests; in production it is one headless
    browser load that clears the AWS WAF challenge. One fetch, no retry.

    The readiness marker is the contract's own symbol: it proves both that the
    page rendered AND that it is the page for this contract. Waiting merely for
    the challenge to vanish let a WAF block page through on 2026-09-03.
    """
    overview_url = BARCHART_OVERVIEW_URL.format(contract=contract_code)
    ready_marker = f'"symbol":"{contract_code}"'

    try:
        if fetch_html is not None:
            page_html = fetch_html(overview_url)
        else:
            with BarchartBrowser() as browser:
                page_html = browser.fetch_html(overview_url, ready_marker=ready_marker)
    except BarchartWafError as exc:
        raise IntradayFetchError(f"Could not load {overview_url}: {exc}") from exc

    return parse_delayed_quote(page_html, contract_code)
