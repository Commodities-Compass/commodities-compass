"""Contract-code provenance on /indicators-grid.

The Section II rail shows one stratum at a time; the Technique panel carries a
socle stating WHICH contract and session the readings come from. That caption is
display-only, so a missing code must degrade the caption and never the
indicators response — these tests pin both halves of that contract.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.dashboard_transformers import (
    transform_to_indicators_grid_response,
)
from app.utils.contract_resolver import _cache, get_contract_code_by_id
from tests.factories import make_ref_commodity, make_ref_contract, make_ref_exchange


INDICATORS_FIXTURE = {
    "rsi": {
        "value": 1.0,
        "min": -2.0,
        "max": 2.0,
        "label": "RSI",
        "ranges": [{"range_low": -2.0, "range_high": 2.0, "area": "ORANGE"}],
    }
}


class TestTransformerPassesContractCode:
    """The transformer mirrors what it is given — it never invents a code."""

    def test_contract_code_is_carried_into_the_response(self) -> None:
        response = transform_to_indicators_grid_response(
            indicators_data=INDICATORS_FIXTURE,
            response_date=date(2026, 7, 31),
            source_algorithm="ensemble_v1_softgate_wrapper",
            contract_code="CAU26",
        )
        assert response.contract_code == "CAU26"

    def test_contract_code_defaults_to_none(self) -> None:
        # Callers that cannot resolve a code omit it; the field stays null
        # rather than carrying a placeholder string the socle would render.
        response = transform_to_indicators_grid_response(
            indicators_data=INDICATORS_FIXTURE,
            response_date=date(2026, 7, 31),
            source_algorithm="legacy",
        )
        assert response.contract_code is None


class TestGetContractCodeById:
    """Resolution for an arbitrary contract id, not just the active one."""

    @pytest.fixture(autouse=True)
    def _clear_resolver_cache(self):
        # The resolver caches by id for 5 min; tests must not leak into
        # each other through it.
        _cache.clear()
        yield
        _cache.clear()

    async def _seed_contract(self, db: AsyncSession, code: str) -> uuid.UUID:
        exchange = make_ref_exchange()
        db.add(exchange)
        await db.flush()

        commodity = make_ref_commodity(exchange.id)
        db.add(commodity)
        await db.flush()

        # Deliberately NOT the active contract — that is the whole point.
        contract = make_ref_contract(
            commodity.id, code=code, contract_month="U26", is_active=False
        )
        db.add(contract)
        await db.flush()
        return contract.id

    @pytest.mark.asyncio
    async def test_resolves_the_code_of_a_non_active_contract(
        self, db_session: AsyncSession
    ) -> None:
        # Across a roll the dashboard asks for the front-month of the requested
        # DATE, which is precisely not the active contract.
        contract_id = await self._seed_contract(db_session, "CAU26")
        assert await get_contract_code_by_id(db_session, contract_id) == "CAU26"

    @pytest.mark.asyncio
    async def test_returns_none_for_an_unknown_id(
        self, db_session: AsyncSession
    ) -> None:
        # Non-fatal by design: the endpoint logs the miss and serves the
        # indicators without a socle caption.
        assert await get_contract_code_by_id(db_session, uuid.uuid4()) is None
