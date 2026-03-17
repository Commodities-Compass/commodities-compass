"""Tests for Phase 2 scraper db_writer modules."""

from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.audit import AudLlmCall
from app.models.pipeline import (
    PlContractDataDaily,
    PlFundamentalArticle,
    PlWeatherObservation,
)
from app.models.reference import RefCommodity, RefContract, RefExchange
from scripts.contract_resolver import (
    ContractResolverError,
    resolve_active,
    resolve_by_code,
)


# ---------------------------------------------------------------------------
# Shared fixture: exchange → commodity → contract chain (sync)
# ---------------------------------------------------------------------------


@pytest.fixture()
def ref_chain_sync(sync_db_session):
    """Create reference chain for sync session tests."""
    exchange = RefExchange(
        code="IFEU", name="ICE Futures Europe", timezone="Europe/London"
    )
    sync_db_session.add(exchange)
    sync_db_session.flush()

    commodity = RefCommodity(code="CC", name="London Cocoa #7", exchange_id=exchange.id)
    sync_db_session.add(commodity)
    sync_db_session.flush()

    contract = RefContract(
        commodity_id=commodity.id,
        code="CAK26",
        contract_month="2026-05",
        expiry_date=date(2026, 5, 15),
        is_active=True,
    )
    sync_db_session.add(contract)
    sync_db_session.flush()

    return {"exchange": exchange, "commodity": commodity, "contract": contract}


# ---------------------------------------------------------------------------
# Contract Resolver
# ---------------------------------------------------------------------------


class TestContractResolver:
    def test_resolve_by_code(self, sync_db_session, ref_chain_sync):
        contract_id = resolve_by_code(sync_db_session, "CAK26")
        assert contract_id == ref_chain_sync["contract"].id

    def test_resolve_by_code_not_found(self, sync_db_session, ref_chain_sync):
        with pytest.raises(ContractResolverError, match="Contract not found"):
            resolve_by_code(sync_db_session, "NONEXISTENT")

    def test_resolve_active(self, sync_db_session, ref_chain_sync):
        contract_id = resolve_active(sync_db_session)
        assert contract_id == ref_chain_sync["contract"].id

    def test_resolve_active_none(self, sync_db_session):
        with pytest.raises(ContractResolverError, match="No active contract"):
            resolve_active(sync_db_session)


# ---------------------------------------------------------------------------
# Barchart DB Writer
# ---------------------------------------------------------------------------


class TestBarchartDbWriter:
    def _make_data(self, **overrides):
        defaults = {
            "timestamp": datetime(2026, 3, 17, 21, 0, 0),
            "close": 8500.0,
            "high": 8600.0,
            "low": 8400.0,
            "volume": 5000,
            "open_interest": 40000,
            "implied_volatility": 48.99,
        }
        return {**defaults, **overrides}

    def test_insert_new_row(self, sync_db_session, ref_chain_sync):
        from scripts.barchart_scraper.db_writer import write_ohlcv

        write_ohlcv(sync_db_session, self._make_data(), "CAK26")

        row = sync_db_session.execute(select(PlContractDataDaily)).scalar_one()
        assert row.date == date(2026, 3, 17)
        assert row.close == Decimal("8500.0")
        assert row.high == Decimal("8600.0")
        assert row.low == Decimal("8400.0")
        assert row.volume == 5000
        assert row.oi == 40000
        assert row.implied_volatility == Decimal("48.99") / 100

    def test_upsert_existing_row(self, sync_db_session, ref_chain_sync):
        from scripts.barchart_scraper.db_writer import write_ohlcv

        contract_id = ref_chain_sync["contract"].id
        existing = PlContractDataDaily(
            date=date(2026, 3, 17),
            contract_id=contract_id,
            close=Decimal("8000"),
        )
        sync_db_session.add(existing)
        sync_db_session.flush()

        write_ohlcv(sync_db_session, self._make_data(), "CAK26")

        rows = sync_db_session.execute(select(PlContractDataDaily)).scalars().all()
        assert len(rows) == 1
        assert rows[0].close == Decimal("8500.0")

    def test_dry_run_no_write(self, sync_db_session, ref_chain_sync):
        from scripts.barchart_scraper.db_writer import write_ohlcv

        write_ohlcv(sync_db_session, self._make_data(), "CAK26", dry_run=True)

        rows = sync_db_session.execute(select(PlContractDataDaily)).scalars().all()
        assert len(rows) == 0

    def test_iv_none_handled(self, sync_db_session, ref_chain_sync):
        from scripts.barchart_scraper.db_writer import write_ohlcv

        write_ohlcv(
            sync_db_session,
            self._make_data(implied_volatility=None),
            "CAK26",
        )

        row = sync_db_session.execute(select(PlContractDataDaily)).scalar_one()
        assert row.implied_volatility is None

    def test_invalid_contract_raises(self, sync_db_session, ref_chain_sync):
        from scripts.barchart_scraper.db_writer import write_ohlcv

        with pytest.raises(ContractResolverError):
            write_ohlcv(sync_db_session, self._make_data(), "INVALID")


# ---------------------------------------------------------------------------
# ICE Stocks DB Writer
# ---------------------------------------------------------------------------


class TestIceStocksDbWriter:
    def test_update_existing_row(self, sync_db_session, ref_chain_sync):
        from scripts.ice_stocks_scraper.db_writer import write_stock_us

        contract_id = ref_chain_sync["contract"].id
        existing = PlContractDataDaily(
            date=date(2026, 3, 17),
            contract_id=contract_id,
            close=Decimal("8500"),
        )
        sync_db_session.add(existing)
        sync_db_session.flush()

        write_stock_us(sync_db_session, 150000)

        row = sync_db_session.execute(select(PlContractDataDaily)).scalar_one()
        assert row.stock_us == Decimal("150000")

    def test_updates_latest_row(self, sync_db_session, ref_chain_sync):
        from scripts.ice_stocks_scraper.db_writer import write_stock_us

        contract_id = ref_chain_sync["contract"].id
        sync_db_session.add(
            PlContractDataDaily(
                date=date(2026, 3, 14), contract_id=contract_id, close=Decimal("8400")
            )
        )
        sync_db_session.add(
            PlContractDataDaily(
                date=date(2026, 3, 17), contract_id=contract_id, close=Decimal("8500")
            )
        )
        sync_db_session.flush()

        write_stock_us(sync_db_session, 160000)

        latest = sync_db_session.execute(
            select(PlContractDataDaily).where(
                PlContractDataDaily.date == date(2026, 3, 17)
            )
        ).scalar_one()
        assert latest.stock_us == Decimal("160000")

        older = sync_db_session.execute(
            select(PlContractDataDaily).where(
                PlContractDataDaily.date == date(2026, 3, 14)
            )
        ).scalar_one()
        assert older.stock_us is None

    def test_no_existing_row_raises(self, sync_db_session, ref_chain_sync):
        from scripts.ice_stocks_scraper.db_writer import DbWriterError, write_stock_us

        with pytest.raises(DbWriterError, match="No existing row"):
            write_stock_us(sync_db_session, 150000)

    def test_dry_run_no_write(self, sync_db_session, ref_chain_sync):
        from scripts.ice_stocks_scraper.db_writer import write_stock_us

        contract_id = ref_chain_sync["contract"].id
        sync_db_session.add(
            PlContractDataDaily(
                date=date(2026, 3, 17), contract_id=contract_id, close=Decimal("8500")
            )
        )
        sync_db_session.flush()

        write_stock_us(sync_db_session, 150000, dry_run=True)

        row = sync_db_session.execute(select(PlContractDataDaily)).scalar_one()
        assert row.stock_us is None


# ---------------------------------------------------------------------------
# CFTC DB Writer
# ---------------------------------------------------------------------------


class TestCftcDbWriter:
    def test_update_existing_row(self, sync_db_session, ref_chain_sync):
        from scripts.cftc_scraper.db_writer import write_com_net_us

        contract_id = ref_chain_sync["contract"].id
        sync_db_session.add(
            PlContractDataDaily(
                date=date(2026, 3, 17), contract_id=contract_id, close=Decimal("8500")
            )
        )
        sync_db_session.flush()

        write_com_net_us(sync_db_session, -5000.0)

        row = sync_db_session.execute(select(PlContractDataDaily)).scalar_one()
        assert row.com_net_us == Decimal("-5000.0")

    def test_no_existing_row_raises(self, sync_db_session, ref_chain_sync):
        from scripts.cftc_scraper.db_writer import DbWriterError, write_com_net_us

        with pytest.raises(DbWriterError, match="No existing row"):
            write_com_net_us(sync_db_session, -5000.0)

    def test_dry_run_no_write(self, sync_db_session, ref_chain_sync):
        from scripts.cftc_scraper.db_writer import write_com_net_us

        contract_id = ref_chain_sync["contract"].id
        sync_db_session.add(
            PlContractDataDaily(
                date=date(2026, 3, 17), contract_id=contract_id, close=Decimal("8500")
            )
        )
        sync_db_session.flush()

        write_com_net_us(sync_db_session, -5000.0, dry_run=True)

        row = sync_db_session.execute(select(PlContractDataDaily)).scalar_one()
        assert row.com_net_us is None


# ---------------------------------------------------------------------------
# Press Review DB Writer
# ---------------------------------------------------------------------------


class TestPressReviewDbWriter:
    def test_insert_article(self, sync_db_session):
        from scripts.press_review_agent.config import Provider
        from scripts.press_review_agent.db_writer import write_article

        parsed = {
            "resume": "Le marche du cacao reste sous pression",
            "mots_cle": "cocoa; rally; 8500 GBP/t",
            "impact_synthetiques": "Impact haussier modere",
        }
        article_id = write_article(
            sync_db_session, Provider.OPENAI, parsed, article_date=date(2026, 3, 17)
        )
        assert article_id is not None

        row = sync_db_session.execute(select(PlFundamentalArticle)).scalar_one()
        assert row.summary == "Le marche du cacao reste sous pression"
        assert row.keywords == "cocoa; rally; 8500 GBP/t"
        assert row.impact_synthesis == "Impact haussier modere"
        assert row.llm_provider == "openai"
        assert row.source == "LLM Agent (o4-mini)"
        assert row.category == "macro"

    def test_insert_llm_call(self, sync_db_session):
        from scripts.press_review_agent.config import Provider
        from scripts.press_review_agent.db_writer import write_llm_call

        write_llm_call(
            sync_db_session,
            Provider.CLAUDE,
            usage={"input_tokens": 5000, "output_tokens": 1200},
            latency_ms=3400,
        )

        row = sync_db_session.execute(select(AudLlmCall)).scalar_one()
        assert row.provider == "claude"
        assert row.model == "claude-sonnet-4-5-20250929"
        assert row.input_tokens == 5000
        assert row.output_tokens == 1200
        assert row.latency_ms == 3400

    def test_multiple_providers(self, sync_db_session):
        from scripts.press_review_agent.config import Provider
        from scripts.press_review_agent.db_writer import write_article

        parsed = {"resume": "Test", "mots_cle": "test", "impact_synthetiques": "test"}
        write_article(
            sync_db_session, Provider.CLAUDE, parsed, article_date=date(2026, 3, 17)
        )
        write_article(
            sync_db_session, Provider.OPENAI, parsed, article_date=date(2026, 3, 17)
        )
        write_article(
            sync_db_session, Provider.GEMINI, parsed, article_date=date(2026, 3, 17)
        )

        rows = sync_db_session.execute(select(PlFundamentalArticle)).scalars().all()
        assert len(rows) == 3
        providers = {r.llm_provider for r in rows}
        assert providers == {"claude", "openai", "gemini"}

    def test_dry_run_no_write(self, sync_db_session):
        from scripts.press_review_agent.config import Provider
        from scripts.press_review_agent.db_writer import write_article

        parsed = {"resume": "Test", "mots_cle": "test", "impact_synthetiques": "test"}
        result = write_article(sync_db_session, Provider.OPENAI, parsed, dry_run=True)
        assert result is None

        rows = sync_db_session.execute(select(PlFundamentalArticle)).scalars().all()
        assert len(rows) == 0


# ---------------------------------------------------------------------------
# Meteo DB Writer
# ---------------------------------------------------------------------------


class TestMeteoDbWriter:
    def test_insert_observation(self, sync_db_session):
        from scripts.meteo_agent.db_writer import write_observation

        parsed = {
            "texte": "Analyse complete des conditions meteorologiques",
            "resume": "Pluies abondantes a Daloa, stress hydrique a Kumasi",
            "mots_cle": "pluie, stress hydrique, Daloa, Kumasi",
            "impact_synthetiques": "7/10; conditions globalement favorables",
        }
        obs_id = write_observation(
            sync_db_session, parsed, observation_date=date(2026, 3, 17)
        )
        assert obs_id is not None

        row = sync_db_session.execute(select(PlWeatherObservation)).scalar_one()
        assert row.observation == "Analyse complete des conditions meteorologiques"
        assert row.summary == "Pluies abondantes a Daloa, stress hydrique a Kumasi"
        assert row.keywords == "pluie, stress hydrique, Daloa, Kumasi"
        assert row.impact_assessment == "7/10; conditions globalement favorables"
        assert row.date == date(2026, 3, 17)

    def test_insert_llm_call(self, sync_db_session):
        from scripts.meteo_agent.db_writer import write_llm_call

        write_llm_call(
            sync_db_session,
            usage={"input_tokens": 3000, "output_tokens": 800},
            latency_ms=2100,
        )

        row = sync_db_session.execute(select(AudLlmCall)).scalar_one()
        assert row.provider == "openai"
        assert row.model == "gpt-4.1"
        assert row.input_tokens == 3000
        assert row.output_tokens == 800
        assert row.latency_ms == 2100

    def test_dry_run_no_write(self, sync_db_session):
        from scripts.meteo_agent.db_writer import write_observation

        parsed = {
            "texte": "Test",
            "resume": "Test",
            "mots_cle": "test",
            "impact_synthetiques": "test",
        }
        result = write_observation(sync_db_session, parsed, dry_run=True)
        assert result is None

        rows = sync_db_session.execute(select(PlWeatherObservation)).scalars().all()
        assert len(rows) == 0
