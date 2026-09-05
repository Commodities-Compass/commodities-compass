"""Tests for the official farmgate price feature (T1b).

Covers:
- farmgate_service: focus season (the most recent one announced by either
  origin), price in force within it, forthcoming price before it starts, and
  the pending state of an origin that has not announced that season yet.
- /dashboard/farmgate-price endpoint: auth-gated, returns CIV + Ghana.
- set-farmgate-price CLI: insert, dry-run, validation.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from datetime import date as date_cls
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.config import settings
from app.main import app
from app.models.pipeline import PlOfficialFarmgatePrice
from app.services.farmgate_service import get_farmgate_prices
from scripts import set_farmgate_price

_FARMGATE_URL = f"{settings.API_V1_STR}/dashboard/farmgate-price"

_USER = {"sub": "auth0|t", "email": "t@example.com", "name": "T", "permissions": []}


@pytest.fixture
def _auth_override():
    app.dependency_overrides[get_current_user] = lambda: _USER
    yield
    app.dependency_overrides.pop(get_current_user, None)


# --------------------------------------------------------------------------- #
# Service
# --------------------------------------------------------------------------- #


@pytest.mark.integration
@pytest.mark.asyncio
async def test_service_latest_effective_and_revision(db_session: AsyncSession) -> None:
    db_session.add_all(
        [
            # CIV: older season, then a revision of the current season
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
                announced_date=date_cls(2025, 9, 15),
                price_native=Decimal("1800"),
                currency="XOF",
                unit="per_kg",
                source="ccc",
            ),
            # a later-announced revision, same effective date → must win
            PlOfficialFarmgatePrice(
                region="civ",
                season_label="2025/26",
                effective_date=date_cls(2025, 10, 1),
                announced_date=date_cls(2026, 1, 20),
                price_native=Decimal("2200"),
                currency="XOF",
                unit="per_kg",
                source="ccc",
            ),
            PlOfficialFarmgatePrice(
                region="ghana",
                season_label="2025/26",
                effective_date=date_cls(2025, 9, 1),
                price_native=Decimal("3100"),
                currency="GHS",
                unit="per_bag_64kg",
                source="cocobod",
            ),
        ]
    )
    await db_session.flush()

    out = await get_farmgate_prices(db_session, date_cls(2026, 7, 1))

    # 2024/25 exists but is not the focus season — it is never published.
    assert out["season"] == "2025/26"
    assert out["civ"]["season_label"] == "2025/26"
    assert out["civ"]["price_native"] == 2200.0  # latest revision wins
    assert out["civ"]["unit"] == "per_kg"
    assert out["ghana"]["price_native"] == 3100.0
    assert out["ghana"]["unit"] == "per_bag_64kg"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_service_publishes_forthcoming_price(db_session: AsyncSession) -> None:
    """A season announced but not yet started is published, not hidden."""
    db_session.add(
        PlOfficialFarmgatePrice(
            region="civ",
            season_label="2025/26",
            effective_date=date_cls(2025, 10, 1),
            price_native=Decimal("1800"),
            currency="XOF",
            unit="per_kg",
            source="ccc",
        )
    )
    await db_session.flush()

    # Asked before the effective date → the announced price, with its own
    # season label and effective date saying it is forthcoming.
    out = await get_farmgate_prices(db_session, date_cls(2025, 1, 1))
    assert out["season"] == "2025/26"
    assert out["civ"]["price_native"] == 1800.0
    assert out["civ"]["effective_date"] == "2025-10-01"
    assert out["ghana"] is None  # never set → pending


@pytest.mark.integration
@pytest.mark.asyncio
async def test_service_empty_table(db_session: AsyncSession) -> None:
    out = await get_farmgate_prices(db_session, date_cls(2026, 9, 4))
    assert out["season"] is None
    assert out["civ"] is None
    assert out["ghana"] is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_service_pending_origin_on_new_season(db_session: AsyncSession) -> None:
    """The production case: CCC announces 2026/27, COCOBOD has not yet.

    Ghana must go pending rather than keep printing its 2025/26 price under a
    2026/27 dashboard — an origin that has not spoken is reported as silent.
    """
    db_session.add_all(
        [
            PlOfficialFarmgatePrice(
                region="civ",
                campaign_type="principale",
                season_label="2026/27",
                effective_date=date_cls(2026, 9, 4),
                price_native=Decimal("1200"),
                currency="XOF",
                unit="per_kg",
                source="ccc",
            ),
            PlOfficialFarmgatePrice(
                region="ghana",
                campaign_type="principale",
                season_label="2025/26",
                effective_date=date_cls(2026, 6, 18),
                price_native=Decimal("2587"),
                currency="GHS",
                unit="per_bag_64kg",
                source="cocobod",
            ),
        ]
    )
    await db_session.flush()

    out = await get_farmgate_prices(db_session, date_cls(2026, 9, 5))
    assert out["season"] == "2026/27"
    assert out["civ"]["price_native"] == 1200.0
    assert out["ghana"] is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_service_serves_the_sub_campaign_in_force(
    db_session: AsyncSession,
) -> None:
    """One card per origin: the mid-crop takes over from its effective date."""
    db_session.add_all(
        [
            PlOfficialFarmgatePrice(
                region="civ",
                campaign_type="principale",
                season_label="2025/26",
                effective_date=date_cls(2025, 10, 1),
                price_native=Decimal("2800"),
                currency="XOF",
                unit="per_kg",
                source="ccc",
            ),
            PlOfficialFarmgatePrice(
                region="civ",
                campaign_type="intermediaire",
                season_label="2025/26",
                effective_date=date_cls(2026, 4, 1),
                price_native=Decimal("1200"),
                currency="XOF",
                unit="per_kg",
                source="ccc",
            ),
        ]
    )
    await db_session.flush()

    # Mid-crop window → the mid-crop price is the one being paid.
    out = await get_farmgate_prices(db_session, date_cls(2026, 8, 1))
    assert out["civ"]["price_native"] == 1200.0
    assert out["civ"]["campaign_type"] == "intermediaire"

    # Main-crop window → the main-crop price, same season.
    out = await get_farmgate_prices(db_session, date_cls(2026, 1, 15))
    assert out["civ"]["price_native"] == 2800.0
    assert out["civ"]["campaign_type"] == "principale"


# --------------------------------------------------------------------------- #
# Endpoint
# --------------------------------------------------------------------------- #


@pytest.mark.integration
@pytest.mark.asyncio
async def test_endpoint_returns_regions(
    client: AsyncClient, db_session: AsyncSession, _auth_override
) -> None:
    db_session.add_all(
        [
            PlOfficialFarmgatePrice(
                region="civ",
                season_label="2025/26",
                effective_date=date_cls(2025, 10, 1),
                price_native=Decimal("1800"),
                currency="XOF",
                unit="per_kg",
                source="ccc",
            ),
            PlOfficialFarmgatePrice(
                region="ghana",
                season_label="2025/26",
                effective_date=date_cls(2025, 9, 1),
                price_native=Decimal("3100"),
                currency="GHS",
                unit="per_bag_64kg",
                source="cocobod",
            ),
        ]
    )
    await db_session.flush()

    r = await client.get(_FARMGATE_URL)
    assert r.status_code == 200
    body = r.json()
    assert body["season"] == "2025/26"
    assert body["civ"]["currency"] == "XOF"
    assert body["civ"]["price_native"] == 1800.0
    assert body["ghana"]["currency"] == "GHS"
    assert body["ghana"]["unit"] == "per_bag_64kg"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _run_cli(monkeypatch, session: Session, argv: list[str]) -> int:
    @contextmanager
    def _fake_session(url=None):
        yield session  # test transaction owns rollback — CLI's commit is a no-op here

    monkeypatch.setattr(set_farmgate_price, "get_session", _fake_session)
    monkeypatch.setattr(sys, "argv", ["set-farmgate-price", *argv])
    return set_farmgate_price.main()


@pytest.mark.integration
def test_cli_inserts_row(monkeypatch, sync_db_session: Session) -> None:
    rc = _run_cli(
        monkeypatch,
        sync_db_session,
        [
            "--region",
            "civ",
            "--price",
            "1800",
            "--unit",
            "per_kg",
            "--season",
            "2025/26",
            "--effective-date",
            "2025-10-01",
        ],
    )
    assert rc == 0
    row = sync_db_session.execute(
        select(PlOfficialFarmgatePrice).where(PlOfficialFarmgatePrice.region == "civ")
    ).scalar_one()
    assert row.price_native == Decimal("1800")
    assert row.currency == "XOF"  # region default
    assert row.source == "ccc"  # region default


@pytest.mark.integration
def test_cli_dry_run_writes_nothing(monkeypatch, sync_db_session: Session) -> None:
    rc = _run_cli(
        monkeypatch,
        sync_db_session,
        [
            "--region",
            "ghana",
            "--price",
            "3100",
            "--unit",
            "per_bag_64kg",
            "--season",
            "2025/26",
            "--effective-date",
            "2025-09-01",
            "--dry-run",
        ],
    )
    assert rc == 0
    count = sync_db_session.execute(select(PlOfficialFarmgatePrice)).scalars().all()
    assert count == []


@pytest.mark.integration
def test_cli_rejects_negative_price(monkeypatch, sync_db_session: Session) -> None:
    rc = _run_cli(
        monkeypatch,
        sync_db_session,
        [
            "--region",
            "civ",
            "--price",
            "-5",
            "--unit",
            "per_kg",
            "--season",
            "2025/26",
            "--effective-date",
            "2025-10-01",
        ],
    )
    assert rc == 1
