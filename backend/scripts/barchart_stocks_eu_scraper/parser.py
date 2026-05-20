"""Barchart cmdty Stock EU HTML parser.

Parses the two ``cmdty-quote-table`` blocks on the page:
  * Table 1 → metadata + Most Recent Value/Date (the value we store).
  * Table 2 → 7-day history (kept for backfill / partial-recovery use cases).

Fails-loud on any drift in unit/multiplier or missing fields, per the
project's ``pipeline-error-handling.md`` rule.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from bs4 import BeautifulSoup

from scripts.barchart_stocks_eu_scraper.config import (
    EXPECTED_MULTIPLIER,
    EXPECTED_UNIT,
)

logger = logging.getLogger(__name__)


class BarchartStocksEuParseError(ValueError):
    """Raised when the Barchart cmdty page HTML is malformed or unexpected."""


@dataclass(frozen=True)
class StockEuObservation:
    """One snapshot of ICE Europe certified cocoa stocks (in 60kg bags)."""

    date: date
    value_bags60kg: Decimal
    history: list[tuple[date, Decimal]] = field(default_factory=list)


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
    history: list[tuple[date, Decimal]] = []
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
            history.append((d, v))
        history.sort(key=lambda pair: pair[0], reverse=True)

    return StockEuObservation(
        date=most_recent_date,
        value_bags60kg=most_recent_value,
        history=history,
    )
