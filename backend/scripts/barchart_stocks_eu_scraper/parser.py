"""Barchart cmdty Stock EU HTML parser.

Parses the two ``cmdty-quote-table`` blocks on the page:
  * Table 1 → metadata + Most Recent Value/Date (the value we store).
  * Table 2 → 7-day history (kept for backfill / partial-recovery use cases).

Fails-loud on any drift in unit/multiplier or missing fields, per the
project's ``pipeline-error-handling.md`` rule.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from bs4 import BeautifulSoup

from scripts.barchart_stocks_eu_scraper.config import (
    EXPECTED_MULTIPLIER,
    EXPECTED_UNIT,
)

logger = logging.getLogger(__name__)


class BarchartStocksEuParseError(ValueError):
    """Raised when the Barchart cmdty page HTML is malformed or unexpected."""


# Regex to extract the Highcharts chart data series. The page embeds ~18
# months of (timestamp_ms, value) pairs in the format:
#     options.series[0].data = [ [1731369600000,283696],[1731456000000,283404],... ];
#
# Highcharts can also emit 3-tuple data points (e.g., marker config on the
# most recent entry: [ts, val, {marker: {...}}]). The pair regex tolerates
# any trailing comma + content before the closing `]` so the most-recent
# entry isn't silently dropped if Barchart enables markers.
_CHART_DATA_RE = re.compile(
    r"options\.series\[0\]\.data\s*=\s*\[(?P<body>[^;]+)\]\s*;",
    re.DOTALL,
)
_PAIR_RE = re.compile(
    r"\[\s*(?P<ts>\d+)\s*,\s*(?P<val>-?\d+(?:\.\d+)?)\s*(?:,[^\]]*)?\]"
)


@dataclass(frozen=True)
class StockEuObservation:
    """One snapshot of ICE Europe certified cocoa stocks (in 60kg bags).

    ``history`` is a tuple (not list) so the frozen contract holds at every
    level — callers cannot mutate the captured history.
    """

    date: date
    value_bags60kg: Decimal
    history: tuple[tuple[date, Decimal], ...] = field(default_factory=tuple)


def _parse_mdy(raw: str) -> date:
    """Parse MM-DD-YYYY (Barchart's date format)."""
    try:
        return datetime.strptime(raw.strip(), "%m-%d-%Y").date()
    except (ValueError, AttributeError) as exc:
        raise BarchartStocksEuParseError(
            f"Unparseable date {raw!r} (expected MM-DD-YYYY)"
        ) from exc


def _parse_int_with_commas(raw: str) -> Decimal:
    """Parse '621,116' → Decimal('621116'). Fails-loud on garbage."""
    cleaned = raw.strip().replace(",", "")
    if not cleaned:
        raise BarchartStocksEuParseError(f"Empty value {raw!r}")
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError) as exc:
        raise BarchartStocksEuParseError(
            f"Unparseable value {raw!r} (expected integer with commas)"
        ) from exc


def _table_to_dict(table) -> dict[str, str]:
    """Convert a <th>key</th><td>value</td> table into a dict."""
    rows = {}
    for tr in table.find_all("tr"):
        th = tr.find("th")
        td = tr.find("td")
        if th is None or td is None:
            continue
        rows[th.get_text(strip=True)] = td.get_text(strip=True)
    return rows


def parse_barchart_stocks_eu_html(html: str | None) -> StockEuObservation:
    """Parse the Barchart cmdty IC345DRW page → StockEuObservation.

    Raises BarchartStocksEuParseError on any drift in structure (missing
    tables, missing fields, unexpected unit/multiplier, unparseable
    value/date).
    """
    if not isinstance(html, str):
        raise BarchartStocksEuParseError(
            f"parse_barchart_stocks_eu_html expects str, got {type(html).__name__}"
        )

    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table", class_="cmdty-quote-table")
    if not tables:
        raise BarchartStocksEuParseError(
            "Found no cmdty-quote-table on the page — Barchart may have "
            "changed the page structure."
        )

    # ---- Table 1: metadata (always the first quote-table on the page) ----
    meta = _table_to_dict(tables[0])

    if "Most Recent Value" not in meta:
        raise BarchartStocksEuParseError(
            "Missing 'Most Recent Value' in metadata table — Barchart format drift."
        )
    if "Most Recent Date" not in meta:
        raise BarchartStocksEuParseError(
            "Missing 'Most Recent Date' in metadata table — Barchart format drift."
        )

    unit = meta.get("Unit", "").strip()
    if unit != EXPECTED_UNIT:
        raise BarchartStocksEuParseError(
            f"Unexpected Unit {unit!r} (expected {EXPECTED_UNIT!r}). "
            "Refusing to write — data may be in tonnes or another unit."
        )

    multiplier = meta.get("Multiplier", "").strip()
    if multiplier and multiplier != EXPECTED_MULTIPLIER:
        raise BarchartStocksEuParseError(
            f"Unexpected Multiplier {multiplier!r} (expected {EXPECTED_MULTIPLIER!r})."
        )

    most_recent_value = _parse_int_with_commas(meta["Most Recent Value"])
    most_recent_date = _parse_mdy(meta["Most Recent Date"])

    # ---- Table 2 (optional): 7-day history ----
    history_rows: list[tuple[date, Decimal]] = []
    if len(tables) >= 2:
        for tr in tables[1].find_all("tr"):
            th = tr.find("th")
            td = tr.find("td")
            if th is None or td is None:
                continue
            try:
                d = _parse_mdy(th.get_text(strip=True))
                v = _parse_int_with_commas(td.get_text(strip=True))
            except BarchartStocksEuParseError:
                logger.warning(
                    "Skipping unparseable history row: %r / %r",
                    th.get_text(strip=True),
                    td.get_text(strip=True),
                )
                continue
            history_rows.append((d, v))

    history = tuple(sorted(history_rows, key=lambda pair: pair[0], reverse=True))
    return StockEuObservation(
        date=most_recent_date,
        value_bags60kg=most_recent_value,
        history=history,
    )


def parse_barchart_history_series(html: str) -> list[tuple[date, Decimal]]:
    """Extract the Highcharts chart data series from the cmdty page HTML.

    Barchart embeds ~18 months of history as
    ``options.series[0].data = [[timestamp_ms, value], ...]``. This is the
    cheap source for the one-shot backfill (single HTTP request).

    Returns a list of ``(date, Decimal)`` sorted ascending by date.

    Raises:
        BarchartStocksEuParseError: if the chart data block isn't found, or
        if it contains no parseable pairs (Barchart format change → fail-loud).
    """
    if not isinstance(html, str):
        raise BarchartStocksEuParseError(
            f"parse_barchart_history_series expects str, got {type(html).__name__}"
        )

    match = _CHART_DATA_RE.search(html)
    if match is None:
        raise BarchartStocksEuParseError(
            "Highcharts series data block not found in HTML "
            "(`options.series[0].data = [...]`). Barchart format drift."
        )

    body = match.group("body")
    rows: list[tuple[date, Decimal]] = []
    for pair_match in _PAIR_RE.finditer(body):
        ts_ms = int(pair_match.group("ts"))
        value = pair_match.group("val")
        d = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).date()
        rows.append((d, Decimal(value)))

    if not rows:
        raise BarchartStocksEuParseError(
            "Highcharts series block found but contained no (timestamp,value) pairs."
        )

    rows.sort(key=lambda pair: pair[0])
    return rows
