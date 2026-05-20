"""NOAA PSL ASCII parser for ENSO indices.

Format:
    Header line with year range (skipped).
    Then rows: ``year jan feb mar ... dec`` (13 tokens, floats).
    Trailing rows contain the missing-value flag (e.g. ``-99.9``) + metadata;
    parser stops at the first non-numeric or out-of-range year token.

Adapted from docs/onboarding/ingest_enso.py (R&D snapshot).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

from scripts.enso_scraper.config import VALUE_NAME_NINO34, VALUE_NAME_ONI

# Sentinel used by NOAA PSL for missing months. The exact magnitude varies
# slightly across PSL files (-99.9 vs -99.99); we detect either via a tight
# absolute window.
_MISSING_VALUE_SENTINEL_ABS = 99.0

# Defensive year bounds — anything outside this range is treated as metadata.
_MIN_YEAR = 1900
_MAX_YEAR = 2100

# Expected token count per data row: year + 12 monthly values.
_TOKENS_PER_ROW = 13


class EnsoParseError(ValueError):
    """Raised when the PSL text input is not parseable as ENSO data."""


@dataclass(frozen=True)
class EnsoRecord:
    """One ENSO observation = (date, value, value_name)."""

    date: date
    value: float
    value_name: str


def _is_missing(value: float) -> bool:
    """Detect PSL's missing-value sentinel (-99.9 or -99.99 family)."""
    return abs(value) >= _MISSING_VALUE_SENTINEL_ABS or math.isnan(value)


def parse_psl_text(text: str | None, *, value_name: str) -> list[EnsoRecord]:
    """Parse PSL ASCII into a list of EnsoRecord (sorted by date ascending).

    Behaviour:
        * Skips the first header line (year range).
        * Stops at the first non-numeric / out-of-range year token.
        * Drops rows with token count != 13 (year + 12 months) silently.
        * Drops missing-flag values (``|x| >= 99``) silently.
        * Output is sorted ascending by date.

    Args:
        text: raw PSL ASCII content as a string. ``None`` → fail-loud.
        value_name: which ENSO index this data represents (``"oni"`` or
            ``"nino34_anomaly"``). Carried into each record so the db_writer
            can route to the correct column.

    Raises:
        EnsoParseError: if ``text`` is not a string (defensive).
    """
    if not isinstance(text, str):
        msg = f"parse_psl_text expects str, got {type(text).__name__}"
        raise EnsoParseError(msg)

    if value_name not in (VALUE_NAME_ONI, VALUE_NAME_NINO34):
        # Caller bug — fail-loud here so the scraper-level test catches it.
        msg = f"Unknown value_name: {value_name!r}"
        raise EnsoParseError(msg)

    lines = text.strip().splitlines()
    if not lines:
        return []

    records: list[EnsoRecord] = []
    # Skip the first non-empty line (header with year range).
    for line in lines[1:]:
        tokens = line.split()
        if not tokens:
            continue

        # First token MUST parse as a 4-digit year.
        try:
            year = int(tokens[0])
        except ValueError:
            break  # Metadata reached.

        if year < _MIN_YEAR or year > _MAX_YEAR:
            break  # Out of plausible range → metadata.

        if len(tokens) < _TOKENS_PER_ROW:
            # Malformed row — skip silently (matches R&D behaviour).
            continue

        try:
            month_values = [float(tok) for tok in tokens[1:_TOKENS_PER_ROW]]
        except ValueError:
            continue

        for month_index, value in enumerate(month_values, start=1):
            if _is_missing(value):
                continue
            records.append(
                EnsoRecord(
                    date=date(year, month_index, 1),
                    value=value,
                    value_name=value_name,
                )
            )

    records.sort(key=lambda r: r.date)
    return records
