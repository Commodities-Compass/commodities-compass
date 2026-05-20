"""ICE COT EU CSV parser.

The ICE COT CSV has 175 columns. We only care about a tight subset (positions
+ open interest + the filter columns). The parser:

  * Asserts required headers exist (fail-loud on schema drift).
  * Filters to cocoa EU FutOnly rows.
  * Drops rows with unparseable date / missing OI / missing position integers.
  * Computes ``release_date = report_date + 3 days`` (ICE/CFTC publication lag).

Returns a list of ``CotEuObservation`` sorted ascending by ``report_date``.
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from scripts.ice_cot_eu_scraper.config import (
    COCOA_EU_MARKET_NAME,
    FUT_ONLY_VARIANT,
    RELEASE_LAG_DAYS,
)

logger = logging.getLogger(__name__)


class CotEuCsvParseError(ValueError):
    """Raised when ICE COT CSV input is malformed or missing required columns."""


@dataclass(frozen=True)
class CotEuObservation:
    """One weekly ICE COT EU observation, ready to be written to DB."""

    report_date: date
    release_date: date
    open_interest: int
    prod_merc_long: int
    prod_merc_short: int
    m_money_long: int
    m_money_short: int
    other_rept_long: int
    other_rept_short: int
    non_rept_long: int
    non_rept_short: int


# Required CSV columns. Anything else is ignored. Drift on any of these
# fails-loud — better to crash than silently produce wrong rows.
_REQUIRED_COLUMNS = (
    "Market_and_Exchange_Names",
    "As_of_Date_Form_MM/DD/YYYY",
    "Open_Interest_All",
    "Prod_Merc_Positions_Long_All",
    "Prod_Merc_Positions_Short_All",
    "M_Money_Positions_Long_All",
    "M_Money_Positions_Short_All",
    "Other_Rept_Positions_Long_All",
    "Other_Rept_Positions_Short_All",
    "NonRept_Positions_Long_All",
    "NonRept_Positions_Short_All",
    "FutOnly_or_Combined",
)


def _parse_int(raw: str | None) -> int | None:
    """Parse an integer; ICE CSV uses bare integers with optional leading spaces."""
    if raw is None:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None


def _parse_mdy(raw: str | None) -> date | None:
    """Parse MM/DD/YYYY (the ICE CSV format for As_of_Date)."""
    if raw is None:
        return None
    try:
        return datetime.strptime(raw.strip(), "%m/%d/%Y").date()
    except (ValueError, AttributeError):
        return None


def parse_ice_cot_csv(text: str | None) -> list[CotEuObservation]:
    """Parse ICE COT history CSV → list of CotEuObservation (sorted by date).

    Filters in this order :
      1. Required headers present → otherwise fail-loud.
      2. Row's market name == 'ICE Cocoa Futures - ICE Futures Europe'.
      3. Row's variant == 'FutOnly' (NOT 'Combined' — CFTC convention).
      4. Date parses (MM/DD/YYYY) → otherwise row dropped.
      5. open_interest + all 8 position integers parse → otherwise row dropped.

    Args:
        text: raw CSV body (may have UTF-8 BOM prefix). ``None`` fails-loud.

    Raises:
        CotEuCsvParseError: bad input type, or header missing required columns.

    Returns:
        Sorted list of CotEuObservation (ascending by ``report_date``).
    """
    if not isinstance(text, str):
        msg = f"parse_ice_cot_csv expects str, got {type(text).__name__}"
        raise CotEuCsvParseError(msg)

    # Strip UTF-8 BOM if present (ICE serves it with one).
    body = text.lstrip("﻿")
    if not body.strip():
        return []

    reader = csv.DictReader(io.StringIO(body))
    if reader.fieldnames is None:
        return []

    missing = [c for c in _REQUIRED_COLUMNS if c not in reader.fieldnames]
    if missing:
        msg = (
            "ICE COT CSV header missing required columns "
            f"{missing!r}. Got {len(reader.fieldnames)} headers; "
            "ICE may have changed format."
        )
        raise CotEuCsvParseError(msg)

    observations: list[CotEuObservation] = []
    dropped = 0
    for row in reader:
        if row.get("Market_and_Exchange_Names", "").strip() != COCOA_EU_MARKET_NAME:
            continue
        if row.get("FutOnly_or_Combined", "").strip() != FUT_ONLY_VARIANT:
            continue

        report_dt = _parse_mdy(row.get("As_of_Date_Form_MM/DD/YYYY"))
        if report_dt is None:
            dropped += 1
            continue

        oi = _parse_int(row.get("Open_Interest_All"))
        if oi is None:
            dropped += 1
            continue

        # All position integers must parse — otherwise the GENERATED net cols
        # in Postgres would be NULL, which we want to avoid silently.
        positions = {
            "prod_merc_long": _parse_int(row.get("Prod_Merc_Positions_Long_All")),
            "prod_merc_short": _parse_int(row.get("Prod_Merc_Positions_Short_All")),
            "m_money_long": _parse_int(row.get("M_Money_Positions_Long_All")),
            "m_money_short": _parse_int(row.get("M_Money_Positions_Short_All")),
            "other_rept_long": _parse_int(row.get("Other_Rept_Positions_Long_All")),
            "other_rept_short": _parse_int(row.get("Other_Rept_Positions_Short_All")),
            "non_rept_long": _parse_int(row.get("NonRept_Positions_Long_All")),
            "non_rept_short": _parse_int(row.get("NonRept_Positions_Short_All")),
        }
        if any(v is None for v in positions.values()):
            dropped += 1
            continue

        release_dt = report_dt + timedelta(days=RELEASE_LAG_DAYS)
        observations.append(
            CotEuObservation(
                report_date=report_dt,
                release_date=release_dt,
                open_interest=oi,
                prod_merc_long=positions["prod_merc_long"],  # type: ignore[arg-type]
                prod_merc_short=positions["prod_merc_short"],  # type: ignore[arg-type]
                m_money_long=positions["m_money_long"],  # type: ignore[arg-type]
                m_money_short=positions["m_money_short"],  # type: ignore[arg-type]
                other_rept_long=positions["other_rept_long"],  # type: ignore[arg-type]
                other_rept_short=positions["other_rept_short"],  # type: ignore[arg-type]
                non_rept_long=positions["non_rept_long"],  # type: ignore[arg-type]
                non_rept_short=positions["non_rept_short"],  # type: ignore[arg-type]
            )
        )

    if dropped > 0:
        logger.warning(
            "Skipped %d cocoa-EU rows with bad/missing data during parse",
            dropped,
        )

    observations.sort(key=lambda o: o.report_date)
    return observations
