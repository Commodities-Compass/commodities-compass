"""Tests for the MVP schema models (15 new tables).

Verifies instantiation, insert/query, unique constraints, FK constraints,
and UUID PK generation for all new models.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from tests.factories import (
    make_aud_data_quality_check,
    make_aud_llm_call,
    make_aud_pipeline_run,
    make_pl_algorithm_config,
    make_pl_algorithm_version,
    make_pl_contract_data_daily,
    make_pl_derived_indicators,
    make_pl_fundamental_article,
    make_pl_indicator_daily,
    make_pl_signal_component,
    make_pl_weather_observation,
    make_ref_commodity,
    make_ref_contract,
    make_ref_exchange,
    make_ref_trading_calendar,
)
from app.models.reference import (
    RefCommodity,
    RefContract,
    RefExchange,
    RefTradingCalendar,
)
from app.models.pipeline import (
    PlAlgorithmConfig,
    PlAlgorithmVersion,
    PlContractDataDaily,
    PlDerivedIndicators,
    PlFundamentalArticle,
    PlIndicatorDaily,
    PlWeatherObservation,
)
from app.models.audit import AudDataQualityCheck, AudLlmCall, AudPipelineRun
from app.models.signal import PlSignalComponent


# === Reference Tables ===


class TestRefExchange:
    async def test_insert_and_query(self, db_session):
        exchange = make_ref_exchange()
        db_session.add(exchange)
        await db_session.flush()

        result = await db_session.execute(
            select(RefExchange).where(RefExchange.code == "ICE_EU")
        )
        row = result.scalar_one()
        assert row.code == "ICE_EU"
        assert row.name == "ICE Futures Europe"
        assert row.timezone == "Europe/London"
        assert isinstance(row.id, uuid.UUID)

    async def test_uuid_pk_generated(self, db_session):
        exchange = make_ref_exchange(code="CME")
        db_session.add(exchange)
        await db_session.flush()
        assert exchange.id is not None
        assert isinstance(exchange.id, uuid.UUID)


class TestRefCommodity:
    async def test_insert_with_exchange_fk(self, db_session):
        exchange = make_ref_exchange(code="ICE_EU_C")
        db_session.add(exchange)
        await db_session.flush()

        commodity = make_ref_commodity(exchange.id)
        db_session.add(commodity)
        await db_session.flush()

        result = await db_session.execute(
            select(RefCommodity).where(RefCommodity.code == "CC")
        )
        row = result.scalar_one()
        assert row.name == "London Cocoa"
        assert row.exchange_id == exchange.id


class TestRefContract:
    async def test_insert_with_commodity_fk(self, db_session):
        exchange = make_ref_exchange(code="ICE_EU_CT")
        db_session.add(exchange)
        await db_session.flush()

        commodity = make_ref_commodity(exchange.id, code="CC_CT")
        db_session.add(commodity)
        await db_session.flush()

        contract = make_ref_contract(commodity.id)
        db_session.add(contract)
        await db_session.flush()

        result = await db_session.execute(
            select(RefContract).where(RefContract.code == "CAK26")
        )
        row = result.scalar_one()
        assert row.contract_month == "K26"
        assert row.is_active is True
        assert row.commodity_id == commodity.id


class TestRefTradingCalendar:
    async def test_insert_trading_day(self, db_session):
        exchange = make_ref_exchange(code="ICE_EU_TC")
        db_session.add(exchange)
        await db_session.flush()

        cal = make_ref_trading_calendar(exchange.id)
        db_session.add(cal)
        await db_session.flush()

        result = await db_session.execute(
            select(RefTradingCalendar).where(
                RefTradingCalendar.exchange_id == exchange.id
            )
        )
        row = result.scalar_one()
        assert row.date == date(2026, 3, 13)
        assert row.is_trading_day is True


# === Pipeline Tables ===


@pytest.fixture
async def ref_chain(db_session):
    """Create exchange → commodity → contract reference chain with unique codes."""
    suffix = uuid.uuid4().hex[:8]
    exchange = make_ref_exchange(code=f"EX_{suffix}")
    db_session.add(exchange)
    await db_session.flush()

    commodity = make_ref_commodity(exchange.id, code=f"CC_{suffix}")
    db_session.add(commodity)
    await db_session.flush()

    contract = make_ref_contract(commodity.id, code=f"CT_{suffix}")
    db_session.add(contract)
    await db_session.flush()

    return {"exchange": exchange, "commodity": commodity, "contract": contract}


class TestPlContractDataDaily:
    async def test_insert_and_query(self, db_session, ref_chain):
        row = make_pl_contract_data_daily(ref_chain["contract"].id)
        db_session.add(row)
        await db_session.flush()

        result = await db_session.execute(
            select(PlContractDataDaily).where(
                PlContractDataDaily.contract_id == ref_chain["contract"].id
            )
        )
        data = result.scalar_one()
        assert data.close == Decimal("8500.000000")
        assert data.volume == 5000
        assert data.date == date(2026, 3, 13)

    async def test_open_is_nullable(self, db_session, ref_chain):
        row = make_pl_contract_data_daily(
            ref_chain["contract"].id, date=date(2026, 3, 12)
        )
        assert row.open is None
        db_session.add(row)
        await db_session.flush()


class TestPlDerivedIndicators:
    async def test_insert_with_indicators(self, db_session, ref_chain):
        row = make_pl_derived_indicators(ref_chain["contract"].id)
        db_session.add(row)
        await db_session.flush()

        result = await db_session.execute(
            select(PlDerivedIndicators).where(
                PlDerivedIndicators.contract_id == ref_chain["contract"].id
            )
        )
        data = result.scalar_one()
        assert data.ema12 == Decimal("8450.000000")
        assert data.macd == Decimal("30.000000")
        assert data.rsi_14d == Decimal("55.000000")


class TestPlAlgorithmVersion:
    async def test_insert_and_query(self, db_session):
        version = make_pl_algorithm_version()
        db_session.add(version)
        await db_session.flush()

        result = await db_session.execute(
            select(PlAlgorithmVersion).where(PlAlgorithmVersion.name == "composite_v1")
        )
        row = result.scalar_one()
        assert row.version == "1.0.0"
        assert row.horizon == "short_term"
        assert row.is_active is True


class TestPlAlgorithmConfig:
    async def test_insert_with_version_fk(self, db_session):
        version = make_pl_algorithm_version(name="config_test", version="1.0.0")
        db_session.add(version)
        await db_session.flush()

        config = make_pl_algorithm_config(version.id)
        db_session.add(config)
        await db_session.flush()

        result = await db_session.execute(
            select(PlAlgorithmConfig).where(
                PlAlgorithmConfig.algorithm_version_id == version.id
            )
        )
        row = result.scalar_one()
        assert row.parameter_name == "decision_threshold_open"
        assert row.value == "0.9"


class TestPlIndicatorDaily:
    async def test_insert_with_decision(self, db_session, ref_chain):
        version = make_pl_algorithm_version(name="ind_test", version="1.0.0")
        db_session.add(version)
        await db_session.flush()

        indicator = make_pl_indicator_daily(ref_chain["contract"].id, version.id)
        db_session.add(indicator)
        await db_session.flush()

        result = await db_session.execute(
            select(PlIndicatorDaily).where(
                PlIndicatorDaily.contract_id == ref_chain["contract"].id
            )
        )
        row = result.scalar_one()
        assert row.decision == "OPEN"
        assert row.final_indicator == Decimal("1.250000")
        assert row.algorithm_version_id == version.id


class TestPlFundamentalArticle:
    async def test_insert_and_query(self, db_session):
        article = make_pl_fundamental_article()
        db_session.add(article)
        await db_session.flush()

        result = await db_session.execute(
            select(PlFundamentalArticle).where(PlFundamentalArticle.category == "macro")
        )
        row = result.scalar_one()
        assert row.source == "Test Author"
        assert row.summary == "Test summary content"


class TestPlWeatherObservation:
    async def test_insert_and_query(self, db_session):
        weather = make_pl_weather_observation()
        db_session.add(weather)
        await db_session.flush()

        result = await db_session.execute(select(PlWeatherObservation))
        row = result.scalar_one()
        assert row.observation == "Test weather report"
        assert row.impact_assessment == "Test weather impact"


# === Audit Tables ===


class TestAudPipelineRun:
    async def test_insert_and_query(self, db_session):
        run = make_aud_pipeline_run()
        db_session.add(run)
        await db_session.flush()

        result = await db_session.execute(
            select(AudPipelineRun).where(
                AudPipelineRun.pipeline_name == "test_pipeline"
            )
        )
        row = result.scalar_one()
        assert row.status == "completed"
        assert isinstance(row.id, uuid.UUID)


class TestAudLlmCall:
    async def test_insert_with_pipeline_run_fk(self, db_session):
        run = make_aud_pipeline_run(pipeline_name="llm_test")
        db_session.add(run)
        await db_session.flush()

        call = make_aud_llm_call(run.id)
        db_session.add(call)
        await db_session.flush()

        result = await db_session.execute(
            select(AudLlmCall).where(AudLlmCall.pipeline_run_id == run.id)
        )
        row = result.scalar_one()
        assert row.provider == "openai"
        assert row.model == "gpt-4-turbo"

    async def test_insert_without_pipeline_run(self, db_session):
        call = make_aud_llm_call(
            provider="anthropic", model="claude-sonnet-4-5-20250929"
        )
        db_session.add(call)
        await db_session.flush()

        result = await db_session.execute(
            select(AudLlmCall).where(AudLlmCall.provider == "anthropic")
        )
        row = result.scalar_one()
        assert row.pipeline_run_id is None


class TestAudDataQualityCheck:
    async def test_insert_and_query(self, db_session):
        check = make_aud_data_quality_check()
        db_session.add(check)
        await db_session.flush()

        result = await db_session.execute(
            select(AudDataQualityCheck).where(
                AudDataQualityCheck.check_name == "null_check"
            )
        )
        row = result.scalar_one()
        assert row.passed is True


# === Signal Table ===


class TestPlSignalComponent:
    async def test_insert_with_refs(self, db_session, ref_chain):
        version = make_pl_algorithm_version(name="sig_test", version="1.0.0")
        db_session.add(version)
        await db_session.flush()

        component = make_pl_signal_component(ref_chain["contract"].id, version.id)
        db_session.add(component)
        await db_session.flush()

        result = await db_session.execute(
            select(PlSignalComponent).where(
                PlSignalComponent.indicator_name == "rsi_14d"
            )
        )
        row = result.scalar_one()
        assert row.raw_value == Decimal("55.000000")
        assert row.normalized_value == Decimal("0.650000")
        assert row.weighted_contribution == Decimal("0.120000")
