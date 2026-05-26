"""Unit tests for the ECA PDF parser against captured fixtures."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from scripts.eca_grindings_scraper.parser import (
    EcaParseError,
    parse_eca_pdf,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("filename", "period_label", "publication_date", "volume_tonnes", "yoy_pct"),
    [
        # Q1 publication: one quarter of data in current year row.
        ("eca_q1_2026.pdf", "Q1-2026", date(2026, 4, 16), 325_895.0, 92.2),
        # Q2 publication: two quarters in current year row.
        ("eca_q2_2025.pdf", "Q2-2025", date(2025, 7, 17), 331_762.0, 92.8),
        # Q3 publication: three quarters in current year row.
        ("eca_q3_2024.pdf", "Q3-2024", date(2024, 10, 17), 354_334.0, 96.7),
    ],
)
def test_parse_known_fixtures(
    filename: str,
    period_label: str,
    publication_date: date,
    volume_tonnes: float,
    yoy_pct: float,
) -> None:
    pdf_bytes = (FIXTURES_DIR / filename).read_bytes()
    records = parse_eca_pdf(pdf_bytes, period_label=period_label)

    assert len(records) == 2, f"Expected 2 records (volume + yoy), got {len(records)}"

    by_metric = {r.metric_name: r for r in records}
    assert by_metric["volume_tonnes"].value == pytest.approx(volume_tonnes, abs=0.5)
    assert by_metric["yoy_pct"].value == pytest.approx(yoy_pct, abs=0.05)
    assert by_metric["volume_tonnes"].publication_date == publication_date
    assert by_metric["yoy_pct"].publication_date == publication_date
    assert by_metric["volume_tonnes"].period_label == period_label
    # Period_date = 1st day of the first month of the quarter.
    quarter = int(period_label[1])
    year = int(period_label.split("-")[1])
    expected_period_date = date(year, (quarter - 1) * 3 + 1, 1)
    assert by_metric["volume_tonnes"].period_date == expected_period_date


@pytest.mark.unit
def test_invalid_period_label() -> None:
    pdf_bytes = (FIXTURES_DIR / "eca_q1_2026.pdf").read_bytes()
    with pytest.raises(EcaParseError, match="Invalid period_label"):
        parse_eca_pdf(pdf_bytes, period_label="2026Q1")


@pytest.mark.unit
def test_quarter_out_of_range() -> None:
    pdf_bytes = (FIXTURES_DIR / "eca_q1_2026.pdf").read_bytes()
    with pytest.raises(EcaParseError, match="Quarter must be 1-4"):
        parse_eca_pdf(pdf_bytes, period_label="Q5-2026")


@pytest.mark.unit
def test_empty_pdf_bytes() -> None:
    # 14-byte minimal PDF that opens but has no pages — pdfplumber will fail
    # to extract text, parser must raise EcaParseError.
    with pytest.raises(EcaParseError):
        parse_eca_pdf(b"not a pdf", period_label="Q1-2026")
