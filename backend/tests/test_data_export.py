"""Tests for the CSV data-export service + endpoint (T4).

Covers:
- export_service.stream_series_csv: header from result keys, date-range filter,
  roll-safe OHLCV via v_contract_data_chained.
- /v1/data/export endpoint: auth-gated, input validation (400s), CSV download
  headers on the happy path.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import date as date_cls
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.config import settings
from app.main import app
from app.models.pipeline import PlContractDataDaily, PlExternalIndicator
from app.models.reference import RefCommodity, RefContract, RefExchange
from app.services.export_service import available_series, stream_series_csv

# Derive the route prefix from settings — it differs per environment
# (default "/v1", overridden to "/api/v1" locally via .env).
_EXPORT_URL = f"{settings.API_V1_STR}/data/export"

# The chained view is created by an Alembic migration, not by metadata.create_all,
# so tests that read through it must materialize it in the test schema first.
_CHAINED_VIEW_DDL = """
CREATE OR REPLACE VIEW v_contract_data_chained AS
SELECT DISTINCT ON (date)
    date, display_date, contract_id, open, high, low, close, volume, oi,
    implied_volatility
FROM pl_contract_data_daily
WHERE close IS NOT NULL
ORDER BY date ASC, COALESCE(oi, 0) DESC, COALESCE(volume, 0) DESC, contract_id ASC
"""

_USER = {
    "sub": "auth0|test",
    "email": "test@example.com",
    "name": "Test",
    "permissions": [],
}


async def _seed_contract(db: AsyncSession, code: str = "CAK26") -> uuid.UUID:
    exchange = RefExchange(code=f"ICE-{code}", name="ICE", timezone="UTC")
    db.add(exchange)
    await db.flush()
    commodity = RefCommodity(
        code=f"COCOA-{code}", name="Cocoa", exchange_id=exchange.id
    )
    db.add(commodity)
    await db.flush()
    contract = RefContract(
        commodity_id=commodity.id,
        code=code,
        contract_month=code[-3:],
        is_active=False,
    )
    db.add(contract)
    await db.flush()
    return contract.id


async def _collect(agen) -> list[list[str]]:
    body = "".join([chunk async for chunk in agen])
    return list(csv.reader(io.StringIO(body)))


@pytest.mark.integration
@pytest.mark.asyncio
async def test_stream_fx_csv_header_and_date_filter(db_session: AsyncSession) -> None:
    db_session.add_all(
        [
            PlExternalIndicator(
                date=date_cls(2026, 5, 1),
                fx_dxy_proxy=Decimal("0.95"),
                fx_gbpusd=Decimal("1.27"),
                fx_eurusd=Decimal("0.95"),
                fx_gbpeur=Decimal("0.85"),
            ),
            PlExternalIndicator(
                date=date_cls(2026, 5, 2),
                fx_dxy_proxy=Decimal("0.96"),
                fx_gbpusd=Decimal("1.28"),
                fx_eurusd=Decimal("0.96"),
                fx_gbpeur=Decimal("0.86"),
            ),
            # outside the requested window — must not appear
            PlExternalIndicator(
                date=date_cls(2026, 6, 15),
                fx_dxy_proxy=Decimal("0.99"),
                fx_gbpusd=Decimal("1.30"),
                fx_eurusd=Decimal("0.99"),
                fx_gbpeur=Decimal("0.88"),
            ),
        ]
    )
    await db_session.flush()

    rows = await _collect(
        stream_series_csv(db_session, "fx", date_cls(2026, 5, 1), date_cls(2026, 5, 31))
    )

    assert rows[0] == ["date", "fx_dxy_proxy", "fx_gbpusd", "fx_eurusd", "fx_gbpeur"]
    assert len(rows) == 3  # header + 2 in-range rows
    assert [r[0] for r in rows[1:]] == ["2026-05-01", "2026-05-02"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_stream_ohlcv_reads_chained_view(db_session: AsyncSession) -> None:
    await db_session.execute(text(_CHAINED_VIEW_DDL))
    cid = await _seed_contract(db_session)
    db_session.add_all(
        [
            PlContractDataDaily(
                date=date_cls(2026, 5, 1),
                contract_id=cid,
                open=Decimal("2000"),
                high=Decimal("2100"),
                low=Decimal("1990"),
                close=Decimal("2050"),
                volume=1000,
                oi=5000,
            ),
            PlContractDataDaily(
                date=date_cls(2026, 5, 2),
                contract_id=cid,
                open=Decimal("2050"),
                high=Decimal("2120"),
                low=Decimal("2040"),
                close=Decimal("2100"),
                volume=1200,
                oi=5100,
            ),
        ]
    )
    await db_session.flush()

    rows = await _collect(
        stream_series_csv(
            db_session, "ohlcv", date_cls(2026, 5, 1), date_cls(2026, 5, 2)
        )
    )

    assert rows[0][:6] == ["date", "display_date", "open", "high", "low", "close"]
    assert len(rows) == 3  # header + 2 sessions
    assert rows[1][0] == "2026-05-01"
    assert rows[1][5] == "2050.000000"  # close, DECIMAL(15,6)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_available_series_is_stable() -> None:
    assert available_series() == [
        "cot_eu",
        "cot_us",
        "fx",
        "indicators",
        "ohlcv",
        "stocks",
        "weather",
    ]


# --------------------------------------------------------------------------- #
# Endpoint validation (auth-gated)
# --------------------------------------------------------------------------- #


@pytest.fixture
def _auth_override():
    app.dependency_overrides[get_current_user] = lambda: _USER
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_export_rejects_unknown_series(
    client: AsyncClient, _auth_override
) -> None:
    r = await client.get(
        _EXPORT_URL,
        params={"series": "nope", "from": "2026-01-01", "to": "2026-02-01"},
    )
    assert r.status_code == 400
    assert "Unknown series" in r.json()["detail"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_export_rejects_bad_date(client: AsyncClient, _auth_override) -> None:
    r = await client.get(
        _EXPORT_URL,
        params={"series": "fx", "from": "2026-13-99", "to": "2026-02-01"},
    )
    assert r.status_code == 400


@pytest.mark.integration
@pytest.mark.asyncio
async def test_export_rejects_from_after_to(
    client: AsyncClient, _auth_override
) -> None:
    r = await client.get(
        _EXPORT_URL,
        params={"series": "fx", "from": "2026-03-01", "to": "2026-02-01"},
    )
    assert r.status_code == 400


@pytest.mark.integration
@pytest.mark.asyncio
async def test_export_rejects_non_csv_format(
    client: AsyncClient, _auth_override
) -> None:
    r = await client.get(
        _EXPORT_URL,
        params={
            "series": "fx",
            "from": "2026-01-01",
            "to": "2026-02-01",
            "format": "json",
        },
    )
    assert r.status_code == 400


@pytest.mark.integration
@pytest.mark.asyncio
async def test_export_happy_path_returns_csv_attachment(
    client: AsyncClient, db_session: AsyncSession, _auth_override
) -> None:
    db_session.add(
        PlExternalIndicator(
            date=date_cls(2026, 5, 1),
            fx_dxy_proxy=Decimal("0.95"),
            fx_gbpusd=Decimal("1.27"),
            fx_eurusd=Decimal("0.95"),
            fx_gbpeur=Decimal("0.85"),
        )
    )
    await db_session.flush()

    r = await client.get(
        _EXPORT_URL,
        params={"series": "fx", "from": "2026-05-01", "to": "2026-05-31"},
    )

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    assert "compass-fx-2026-05-01-to-2026-05-31.csv" in r.headers["content-disposition"]
    body = r.text.splitlines()
    assert body[0] == "date,fx_dxy_proxy,fx_gbpusd,fx_eurusd,fx_gbpeur"
    assert body[1].startswith("2026-05-01")
