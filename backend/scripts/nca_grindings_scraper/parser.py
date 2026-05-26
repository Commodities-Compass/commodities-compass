"""PDF parser for NCA quarterly grindings reports.

NCA report format (consistent 2009-2026):

    To: <ICE liaison>
    From: <NCA author>
    Date: <Month> <Day>, <Year>
    Subj: Release of <Ordinal> Quarter Cocoa Grindings for <Year>

                                In Metric Tons       Increase (Decrease)
                                <Year>   <Year-1>    Amount      %
    Cocoa Beans Ground          106,087  110,278     (4,191)     (3.80%)

Older PDFs render "Cocoa Beans Ground" as "CocoaBeansGround" (no spaces) due
to PDF font kerning. The parser uses a tolerant regex to match either form.

Yields two records per PDF:
  * ``volume_tonnes`` — current year tonnage (e.g. 106 087).
  * ``yoy_pct`` — derived from ``current / prior * 100`` (e.g. 96.2) so we
    are robust to the various delta formats NCA uses
    (``(4,191)``, ``-5,028``, etc.).
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import date

import pdfplumber

_MONTH_NAMES = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

_ORDINAL_TO_QUARTER = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "1st": 1,
    "2nd": 2,
    "3rd": 3,
    "4th": 4,
}

# "Date: April 16, 2026"
_DATE_RE = re.compile(
    r"Date\s*:\s*(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2}),\s+(?P<year>\d{4})",
    re.IGNORECASE,
)

# "Subj: Release of First Quarter Cocoa Grindings for 2026"
_SUBJECT_RE = re.compile(
    r"Subj\s*:?\s*Release of (?P<ordinal>First|Second|Third|Fourth)\s+Quarter\s+Cocoa\s+Grindings\s+for\s+(?P<year>\d{4})",
    re.IGNORECASE,
)

# Volume line — tolerates "Cocoa Beans Ground" or "CocoaBeansGround"
# (some PDF fonts kern letters together so pdfplumber drops the spaces).
# We capture the current year volume + prior year volume.
_VOLUME_LINE_RE = re.compile(
    r"Cocoa\s*Beans\s*Ground\s+"
    r"(?P<curr>\d{1,3}(?:,\d{3})*|\d+)\s+"
    r"(?P<prior>\d{1,3}(?:,\d{3})*|\d+)",
    re.IGNORECASE,
)


class NcaParseError(ValueError):
    """Raised when an NCA PDF cannot be parsed (drifted format)."""


@dataclass(frozen=True)
class NcaRecord:
    """One value extracted from an NCA PDF."""

    publication_date: date
    period_label: str  # "Q1-2026"
    period_date: date
    metric_name: str  # "volume_tonnes" | "yoy_pct"
    value: float


def _parse_publication_date(text: str) -> date:
    match = _DATE_RE.search(text)
    if not match:
        raise NcaParseError(
            "NCA PDF: cannot find publication date header "
            "(expected 'Date: <Month> <Day>, <Year>')."
        )
    month_name = match.group("month").lower()
    month = _MONTH_NAMES.get(month_name)
    if month is None:
        raise NcaParseError(f"NCA PDF: unknown month {month_name!r}.")
    return date(int(match.group("year")), month, int(match.group("day")))


def _parse_quarter_and_year(text: str) -> tuple[int, int]:
    match = _SUBJECT_RE.search(text)
    if not match:
        raise NcaParseError(
            "NCA PDF: cannot find quarter/year in subject line "
            "(expected 'Subj: Release of <Ordinal> Quarter Cocoa Grindings for <Year>')."
        )
    ordinal = match.group("ordinal").lower()
    quarter = _ORDINAL_TO_QUARTER.get(ordinal)
    if quarter is None:
        raise NcaParseError(f"NCA PDF: unknown ordinal {ordinal!r}.")
    return quarter, int(match.group("year"))


def _parse_volume_line(text: str) -> tuple[float, float]:
    match = _VOLUME_LINE_RE.search(text)
    if not match:
        raise NcaParseError("NCA PDF: cannot find 'Cocoa Beans Ground' volume line.")
    current = float(match.group("curr").replace(",", ""))
    prior = float(match.group("prior").replace(",", ""))
    return current, prior


def parse_nca_pdf(
    pdf_bytes: bytes, *, expected_period_label: str | None = None
) -> list[NcaRecord]:
    """Parse one NCA quarterly PDF.

    Args:
        pdf_bytes: full PDF binary content.
        expected_period_label: optional ``"Q{n}-{YYYY}"`` to assert the PDF
            content matches the URL/listing context. If provided and the
            PDF reports a different period, fail-loud.

    Returns:
        Two records: ``volume_tonnes`` and ``yoy_pct``.

    Raises:
        NcaParseError: if the PDF cannot be parsed or fails consistency.
    """
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            if not pdf.pages:
                raise NcaParseError("NCA PDF: zero pages.")
            page_one_text = pdf.pages[0].extract_text() or ""
    except NcaParseError:
        raise
    except Exception as exc:  # noqa: BLE001 -- wrap pdfplumber / pdfminer errors
        msg = f"NCA PDF: cannot open ({type(exc).__name__}: {exc})"
        raise NcaParseError(msg) from exc

    if not page_one_text.strip():
        raise NcaParseError("NCA PDF: page 1 extracted text is empty.")

    pub_date = _parse_publication_date(page_one_text)
    quarter, year = _parse_quarter_and_year(page_one_text)
    period_label = f"Q{quarter}-{year}"
    period_date = date(year, (quarter - 1) * 3 + 1, 1)

    if expected_period_label is not None and expected_period_label != period_label:
        raise NcaParseError(
            f"NCA PDF: subject reports {period_label} but listing label is "
            f"{expected_period_label}."
        )

    current_volume, prior_volume = _parse_volume_line(page_one_text)

    # Sanity bounds for North America (typical Q range 80k-130k tonnes).
    if not (40_000 <= current_volume <= 250_000):
        raise NcaParseError(
            f"NCA PDF {period_label}: volume={current_volume:.0f} outside 40k-250k range."
        )
    if prior_volume <= 0:
        raise NcaParseError(
            f"NCA PDF {period_label}: prior_volume={prior_volume:.0f} non-positive."
        )

    yoy_pct = round(current_volume / prior_volume * 100, 2)

    return [
        NcaRecord(
            publication_date=pub_date,
            period_label=period_label,
            period_date=period_date,
            metric_name="volume_tonnes",
            value=current_volume,
        ),
        NcaRecord(
            publication_date=pub_date,
            period_label=period_label,
            period_date=period_date,
            metric_name="yoy_pct",
            value=yoy_pct,
        ),
    ]
