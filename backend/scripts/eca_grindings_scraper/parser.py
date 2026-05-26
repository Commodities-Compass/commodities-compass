"""PDF parser for ECA quarterly grindings reports.

Each ECA PDF (https://www.eurococoa.com/grind-stats/) follows a stable
structure:

* Top of page 1:
    ``Date : <Month> <Day><suffix> <Year>``  -- publication date

* "Quarterly Comparison (net change from prior year)" section
    Header row: ``Q4 %  Q3 %  Q2 %  Q1 %  YTD %``
    Data rows: ``{year}/{year-1}  v1  v2 ... vN``
    For a Q{n} publication, the current year's row contains exactly N values
    (Q{n} through Q1), LEFT-justified. The FIRST value is therefore the Q{n}
    YoY %.

* "Quarterly Results" section
    Header row: ``Q4  Q3  Q2  Q1  YTD  (12 mth totals — moving average)``
    Data rows: ``{year}  v1  v2 ... vK``
    For a Q{n} publication, the current year row has K=N+1 or K=N+2 values
    (Q{n} ... Q1, YTD, optional 12mth-avg). The FIRST value is the Q{n}
    volume in tonnes.

Parser strategy: text extraction with ``pdfplumber``, locate the two sections,
read the current year row, the first numeric token in each is the metric for
quarter Q{n}. Fail-loud if structure drifts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

import pdfplumber

# Months recognised in the "Date :" header. ECA uses English month names.
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

# "Date : April 16th 2026" / "Date: October 17th 2024" — month / day / year.
_DATE_RE = re.compile(
    r"Date\s*:\s*(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?\s+(?P<year>\d{4})",
    re.IGNORECASE,
)

# Anchors marking the two relevant sections.
_COMPARISON_ANCHOR = "Quarterly Comparison"
_RESULTS_ANCHOR = "Quarterly Results"

# Page 2 anchor — terminate parsing of page 1 sections.
_YTD_ANCHOR = "YTD Comparison"


class EcaParseError(ValueError):
    """Raised when an ECA PDF cannot be parsed (drifted format, missing data)."""


@dataclass(frozen=True)
class EcaRecord:
    """One value extracted from an ECA PDF."""

    publication_date: date
    period_label: str  # e.g. "Q1-2026"
    period_date: date  # first day of the quarter (2026-01-01 for Q1 2026)
    metric_name: str  # METRIC_VOLUME_TONNES | METRIC_YOY_PCT
    value: float


def _parse_publication_date(text: str) -> date:
    match = _DATE_RE.search(text)
    if not match:
        msg = (
            "ECA PDF: cannot find publication date header "
            "(expected 'Date : <Month> <Day> <Year>')."
        )
        raise EcaParseError(msg)
    month_name = match.group("month").lower()
    month = _MONTH_NAMES.get(month_name)
    if month is None:
        raise EcaParseError(f"ECA PDF: unknown month in date header: {month_name!r}")
    return date(int(match.group("year")), month, int(match.group("day")))


def _parse_period_label(period_label: str) -> tuple[int, int, date]:
    """Validate label format ``Q{n}-{YYYY}``, return (quarter, year, period_date)."""
    match = re.fullmatch(r"Q(\d)-(\d{4})", period_label)
    if not match:
        raise EcaParseError(
            f"Invalid period_label {period_label!r}; expected 'Q{{n}}-{{YYYY}}'."
        )
    quarter = int(match.group(1))
    if quarter not in (1, 2, 3, 4):
        raise EcaParseError(f"Quarter must be 1-4, got {quarter}.")
    year = int(match.group(2))
    period_date = date(year, (quarter - 1) * 3 + 1, 1)
    return quarter, year, period_date


def _extract_section_text(text: str, anchor: str, *, stop_at: str | None = None) -> str:
    """Return the substring starting at ``anchor`` (exclusive) up to ``stop_at``.

    Both anchors must appear in ``text``; fail-loud if missing.
    """
    start = text.find(anchor)
    if start == -1:
        raise EcaParseError(f"ECA PDF: section anchor not found: {anchor!r}")
    start = text.find("\n", start) + 1
    end_pos = len(text)
    if stop_at:
        candidate = text.find(stop_at, start)
        if candidate != -1:
            end_pos = candidate
    return text[start:end_pos]


def _find_year_row(section: str, year: int) -> list[float]:
    """Return the numeric values on the line starting with ``str(year)`` (or ``str(year)/...``).

    Handles both forms used by ECA:
      * ``2026  325,895  325,895  1,299,480`` (results — comma-separated thousands)
      * ``2026/2025  92.2``                    (comparison — slash-prefixed)

    Commas and thousand separators are removed. Returns floats in document order.
    Fail-loud if no matching line is found.
    """
    prefix_volume = f"{year} "
    prefix_pct = f"{year}/{year - 1}"

    for raw_line in section.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if (
            line.startswith(prefix_pct)
            or line.startswith(prefix_volume)
            or line == str(year)
        ):
            # Strip the leading year/comparison prefix and parse all numbers.
            payload = line.split(maxsplit=1)[1] if " " in line else ""
            payload = payload.replace(",", "")
            numbers: list[float] = []
            for token in payload.split():
                # Stop at first non-numeric token (defensive — shouldn't happen
                # in ECA PDFs but protects against trailing notes).
                try:
                    numbers.append(float(token))
                except ValueError:
                    break
            return numbers

    msg = f"ECA PDF: no data row found for year {year} in section."
    raise EcaParseError(msg)


def parse_eca_pdf(pdf_bytes: bytes, *, period_label: str) -> list[EcaRecord]:
    """Parse one ECA quarterly PDF into a list of EcaRecord.

    Args:
        pdf_bytes: full PDF binary content.
        period_label: e.g. ``"Q1-2026"``. Determines which quarter's value
            we read from the PDF tables. The PDF itself does not carry the
            quarter in a structured field — we trust the URL/listing.

    Returns:
        Two records: one ``volume_tonnes``, one ``yoy_pct``.

    Raises:
        EcaParseError: if the PDF structure has drifted (missing anchors,
            missing date header, no year row).
    """
    import io

    quarter, year, period_date = _parse_period_label(period_label)

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            if not pdf.pages:
                raise EcaParseError("ECA PDF: zero pages.")
            page_one_text = pdf.pages[0].extract_text() or ""
    except EcaParseError:
        raise
    except Exception as exc:  # noqa: BLE001 -- wrap any pdfplumber / pdfminer error
        msg = f"ECA PDF: cannot open ({type(exc).__name__}: {exc})"
        raise EcaParseError(msg) from exc

    if not page_one_text.strip():
        raise EcaParseError("ECA PDF: page 1 extracted text is empty.")

    pub_date = _parse_publication_date(page_one_text)

    comparison_section = _extract_section_text(
        page_one_text, _COMPARISON_ANCHOR, stop_at=_RESULTS_ANCHOR
    )
    results_section = _extract_section_text(
        page_one_text, _RESULTS_ANCHOR, stop_at=_YTD_ANCHOR
    )

    yoy_values = _find_year_row(comparison_section, year)
    if not yoy_values:
        raise EcaParseError(
            f"ECA PDF {period_label}: comparison row for {year} has no numbers."
        )
    volume_values = _find_year_row(results_section, year)
    if not volume_values:
        raise EcaParseError(
            f"ECA PDF {period_label}: results row for {year} has no numbers."
        )

    # For Q{n} publication, the current year row's FIRST value is Q{n}.
    yoy_pct = yoy_values[0]
    volume_tonnes = volume_values[0]

    # Sanity: volumes should be in the realistic ECA range (200k-450k tonnes
    # per quarter, ~1.2M-1.5M YTD aggregate; first cell is one quarter).
    if not (100_000 <= volume_tonnes <= 600_000):
        raise EcaParseError(
            f"ECA PDF {period_label}: volume_tonnes={volume_tonnes:.0f} "
            "outside plausible quarterly range (100k-600k)."
        )
    # YoY % typically lives in 70-130 band.
    if not (50.0 <= yoy_pct <= 150.0):
        raise EcaParseError(
            f"ECA PDF {period_label}: yoy_pct={yoy_pct:.1f} outside plausible (50-150)."
        )

    return [
        EcaRecord(
            publication_date=pub_date,
            period_label=period_label,
            period_date=period_date,
            metric_name="volume_tonnes",
            value=volume_tonnes,
        ),
        EcaRecord(
            publication_date=pub_date,
            period_label=period_label,
            period_date=period_date,
            metric_name="yoy_pct",
            value=yoy_pct,
        ),
    ]
