"""ECB SDMX CSV parser for FX time series.

ECB returns CSV with at least these columns:
    KEY, TIME_PERIOD, OBS_VALUE, OBS_STATUS [, ...]

The parser:
  * Asserts both TIME_PERIOD and OBS_VALUE columns are present (fail-loud).
  * Drops rows where TIME_PERIOD doesn't parse as YYYY-MM-DD.
  * Drops rows where OBS_VALUE is empty / "NaN" / non-numeric.
  * Returns ``list[EcbObservation]`` sorted ascending by date.

Adapted from docs/onboarding/ingest_fx.py (R&D snapshot) — kept dependency-free
(stdlib csv) so this module doesn't pull pandas.
"""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass
from datetime import date, datetime


class EcbCsvParseError(ValueError):
    """Raised when the ECB SDMX CSV text is not parseable."""


@dataclass(frozen=True)
class EcbObservation:
    """One ECB observation = (date, value)."""

    date: date
    value: float


# Required column headers; ECB sometimes adds OBS_CONF, OBS_PRE_BREAK etc.,
# which we simply ignore.
_REQUIRED_COLUMNS = ("TIME_PERIOD", "OBS_VALUE")


def _parse_date(raw: str) -> date | None:
    """Parse YYYY-MM-DD; return None on any error."""
    try:
        return datetime.strptime(raw.strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        return None


def _parse_value(raw: str | None) -> float | None:
    """Parse a numeric value; return None on empty/NaN/error."""
    if raw is None:
        return None
    cleaned = raw.strip()
    if not cleaned or cleaned.lower() == "nan":
        return None
    try:
        value = float(cleaned)
    except ValueError:
        return None
    if math.isnan(value):
        return None
    return value


def parse_ecb_csv(text: str | None) -> list[EcbObservation]:
    """Parse ECB SDMX CSV body into a list of EcbObservation (sorted by date).

    Args:
        text: raw CSV content from ECB. ``None`` → fail-loud.

    Raises:
        EcbCsvParseError: if input is not a string OR the header lacks
            ``TIME_PERIOD`` / ``OBS_VALUE`` columns.

    Returns:
        Observations sorted ascending by date. Rows with non-parseable date
        or value are silently dropped (matches ECB SDMX conventions — ``M``
        status rows have empty OBS_VALUE).
    """
    if not isinstance(text, str):
        msg = f"parse_ecb_csv expects str, got {type(text).__name__}"
        raise EcbCsvParseError(msg)

    if not text.strip():
        return []

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return []

    missing = [c for c in _REQUIRED_COLUMNS if c not in reader.fieldnames]
    if missing:
        msg = (
            "ECB CSV header missing required columns "
            f"{missing!r}. Got headers: {reader.fieldnames!r}"
        )
        raise EcbCsvParseError(msg)

    observations: list[EcbObservation] = []
    for row in reader:
        d = _parse_date(row.get("TIME_PERIOD", ""))
        if d is None:
            continue
        v = _parse_value(row.get("OBS_VALUE", ""))
        if v is None:
            continue
        observations.append(EcbObservation(date=d, value=v))

    observations.sort(key=lambda o: o.date)
    return observations
