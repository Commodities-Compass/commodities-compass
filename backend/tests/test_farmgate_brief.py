"""Tests for the shared farmgate brief helper (read + FR/EN formatting)."""

from __future__ import annotations

from datetime import date as date_cls
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.models.pipeline import PlOfficialFarmgatePrice
from scripts._shared.farmgate_brief import format_farmgate_lines, read_farmgate


def test_format_fr_includes_both_regions_and_disclaimer() -> None:
    farmgate = {
        "civ": {
            "season_label": "2025/26",
            "price_native": 2200.0,
            "currency": "XOF",
            "unit": "per_kg",
        },
        "ghana": {
            "season_label": "2025/26",
            "price_native": 3100.0,
            "currency": "GHS",
            "unit": "per_bag_64kg",
        },
    }
    lines = format_farmgate_lines(farmgate, "fr")
    text = "\n".join(lines)
    assert "PRIX GARANTI OFFICIEL" in lines[0]
    assert "2 200 FCFA/kg" in text
    assert "3 100 GHS/sac 64 kg" in text
    assert "distinct du prix réel terrain" in text


def test_format_en_uses_english_scaffolding() -> None:
    farmgate = {
        "civ": {
            "season_label": "2025/26",
            "price_native": 2200.0,
            "currency": "XOF",
            "unit": "per_kg",
        },
        "ghana": None,
    }
    farmgate["season"] = "2025/26"
    lines = format_farmgate_lines(farmgate, "en")
    text = "\n".join(lines)
    assert "OFFICIAL GUARANTEED FARMGATE PRICE" in lines[0]
    # Ghana silent on the published season → named as pending, with the season
    assert "awaiting announcement (campaign 2025/26)" in text
    assert "distinct from the real terrain price" in text


def test_format_empty_returns_no_lines() -> None:
    assert format_farmgate_lines(None, "fr") == []
    assert format_farmgate_lines({"civ": None, "ghana": None}, "fr") == []


@pytest.mark.integration
def test_read_farmgate_picks_focus_season(sync_db_session: Session) -> None:
    sync_db_session.add_all(
        [
            PlOfficialFarmgatePrice(
                region="civ",
                season_label="2024/25",
                effective_date=date_cls(2024, 10, 1),
                price_native=Decimal("1500"),
                currency="XOF",
                unit="per_kg",
                source="ccc",
            ),
            PlOfficialFarmgatePrice(
                region="civ",
                season_label="2025/26",
                effective_date=date_cls(2025, 10, 1),
                price_native=Decimal("2200"),
                currency="XOF",
                unit="per_kg",
                source="ccc",
            ),
        ]
    )
    sync_db_session.flush()

    out = read_farmgate(sync_db_session, date_cls(2026, 7, 1))
    civ = out["civ"]
    assert out["season"] == "2025/26"  # 2024/25 is history, never published
    assert civ is not None
    assert civ["price_native"] == 2200.0
    assert civ["season_label"] == "2025/26"
    assert out["ghana"] is None


@pytest.mark.integration
def test_read_farmgate_pending_origin(sync_db_session: Session) -> None:
    """Ghana holds only last season → pending once CCC announces the next one.

    Same rule as the dashboard service: the brief and the card must never
    disagree on the guaranteed price a client reads the same morning.
    """
    sync_db_session.add_all(
        [
            PlOfficialFarmgatePrice(
                region="civ",
                season_label="2026/27",
                effective_date=date_cls(2026, 9, 4),
                price_native=Decimal("1200"),
                currency="XOF",
                unit="per_kg",
                source="ccc",
            ),
            PlOfficialFarmgatePrice(
                region="ghana",
                season_label="2025/26",
                effective_date=date_cls(2026, 6, 18),
                price_native=Decimal("2587"),
                currency="GHS",
                unit="per_bag_64kg",
                source="cocobod",
            ),
        ]
    )
    sync_db_session.flush()

    out = read_farmgate(sync_db_session, date_cls(2026, 9, 5))
    assert out["season"] == "2026/27"
    assert out["civ"]["price_native"] == 1200.0
    assert out["ghana"] is None

    text = "\n".join(format_farmgate_lines(out, "fr"))
    assert "1 200 FCFA/kg" in text
    assert "Ghana : en attente d'annonce (campagne 2026/27)" in text
