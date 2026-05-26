"""Unit tests for the NCA PDF parser against captured fixtures."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from scripts.nca_grindings_scraper.parser import NcaParseError, parse_nca_pdf

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.mark.unit
@pytest.mark.parametrize(
    (
        "filename",
        "period_label",
        "publication_date",
        "volume_tonnes",
        "yoy_pct_expected",
    ),
    [
        # Modern format with "Cocoa Beans Ground" (spaces) + (negative) deltas.
        ("nca_q1_2026.pdf", "Q1-2026", date(2026, 4, 16), 106_087.0, 96.20),
        ("nca_q1_2025.pdf", "Q1-2025", date(2025, 4, 17), 110_278.0, 97.00),
        # Old format with "CocoaBeansGround" (no spaces) + -X.X% deltas.
        ("nca_q1_2023.pdf", "Q1-2023", date(2023, 4, 20), 109_666.0, 95.62),
    ],
)
def test_parse_known_fixtures(
    filename: str,
    period_label: str,
    publication_date: date,
    volume_tonnes: float,
    yoy_pct_expected: float,
) -> None:
    pdf_bytes = (FIXTURES_DIR / filename).read_bytes()
    records = parse_nca_pdf(pdf_bytes, expected_period_label=period_label)

    assert len(records) == 2
    by_metric = {r.metric_name: r for r in records}
    assert by_metric["volume_tonnes"].value == pytest.approx(volume_tonnes, abs=0.5)
    assert by_metric["yoy_pct"].value == pytest.approx(yoy_pct_expected, abs=0.05)
    assert by_metric["volume_tonnes"].publication_date == publication_date


@pytest.mark.unit
def test_period_label_mismatch_fails_loud() -> None:
    pdf_bytes = (FIXTURES_DIR / "nca_q1_2026.pdf").read_bytes()
    with pytest.raises(
        NcaParseError, match="reports Q1-2026 but listing label is Q2-2026"
    ):
        parse_nca_pdf(pdf_bytes, expected_period_label="Q2-2026")


@pytest.mark.unit
def test_bad_pdf_bytes() -> None:
    with pytest.raises(NcaParseError):
        parse_nca_pdf(b"not a pdf", expected_period_label="Q1-2026")
