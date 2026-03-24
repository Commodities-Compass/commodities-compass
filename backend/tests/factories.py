"""Factory functions for creating test model instances."""

from datetime import date, datetime
from decimal import Decimal

from app.models.indicator import Indicator
from app.models.market_research import MarketResearch
from app.models.technicals import Technicals
from app.models.test_range import TestRange
from app.models.weather_data import WeatherData

# MVP schema models
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


def make_technicals(**overrides) -> Technicals:
    """Create a Technicals instance with sensible defaults."""
    defaults = {
        "timestamp": datetime(2026, 1, 15, 21, 0),
        "commodity_symbol": "CC",
        "close": Decimal("8500.000000"),
        "high": Decimal("8600.000000"),
        "low": Decimal("8400.000000"),
        "volume": 5000,
        "open_interest": 40000,
        "r3": Decimal("9000.000000"),
        "r2": Decimal("8800.000000"),
        "r1": Decimal("8700.000000"),
        "pivot": Decimal("8500.000000"),
        "s1": Decimal("8300.000000"),
        "s2": Decimal("8200.000000"),
        "s3": Decimal("8000.000000"),
        "ema12": Decimal("8450.000000"),
        "ema26": Decimal("8420.000000"),
        "macd": Decimal("30.000000"),
        "bollinger": Decimal("8500.000000"),
        "bollinger_upper": Decimal("8700.000000"),
        "bollinger_lower": Decimal("8300.000000"),
        "bollinger_width": Decimal("400.000000"),
        "volume_oi_ratio": Decimal("0.125000"),
        "row_number": 1,
    }
    return Technicals(**(defaults | overrides))


def make_indicator(**overrides) -> Indicator:
    """Create an Indicator instance with sensible defaults."""
    defaults = {
        "date": datetime(2026, 1, 15),
        "commodity_symbol": "CC",
        "close_pivot": Decimal("1.000000"),
        "close_pivot_norm": Decimal("0.500000"),
        "macroeco_bonus": Decimal("0.000000"),
        "eco": "",
    }
    return Indicator(**(defaults | overrides))


def make_market_research(**overrides) -> MarketResearch:
    """Create a MarketResearch instance with sensible defaults."""
    defaults = {
        "date": datetime(2026, 1, 15),
        "author": "Test Author",
        "summary": "Test summary content",
        "impact_synthesis": "Test impact synthesis",
        "date_text": "2026-01-15",
    }
    return MarketResearch(**(defaults | overrides))


def make_weather_data(**overrides) -> WeatherData:
    """Create a WeatherData instance with sensible defaults."""
    defaults = {
        "date": datetime(2026, 1, 15),
        "text": "Test weather report",
        "summary": "Test weather summary",
        "keywords": "rain, cocoa, ghana",
        "impact_synthesis": "Test weather impact",
    }
    return WeatherData(**(defaults | overrides))


def make_test_range(**overrides) -> TestRange:
    """Create a TestRange instance with sensible defaults."""
    defaults = {
        "indicator": "RSI",
        "range_low": Decimal("0.000000"),
        "range_high": Decimal("0.300000"),
        "area": "RED",
    }
    return TestRange(**(defaults | overrides))


# === MVP Schema Factories ===


def make_ref_exchange(**overrides) -> RefExchange:
    defaults = {
        "code": "ICE_EU",
        "name": "ICE Futures Europe",
        "timezone": "Europe/London",
    }
    return RefExchange(**(defaults | overrides))


def make_ref_commodity(exchange_id, **overrides) -> RefCommodity:
    defaults = {
        "code": "CC",
        "name": "London Cocoa",
        "exchange_id": exchange_id,
    }
    return RefCommodity(**(defaults | overrides))


def make_ref_contract(commodity_id, **overrides) -> RefContract:
    defaults = {
        "commodity_id": commodity_id,
        "code": "CAK26",
        "contract_month": "K26",
        "is_active": True,
    }
    return RefContract(**(defaults | overrides))


def make_ref_trading_calendar(exchange_id, **overrides) -> RefTradingCalendar:
    defaults = {
        "exchange_id": exchange_id,
        "date": date(2026, 3, 13),
        "is_trading_day": True,
        "session_type": "regular",
        "reason": None,
    }
    return RefTradingCalendar(**(defaults | overrides))


def make_pl_contract_data_daily(contract_id, **overrides) -> PlContractDataDaily:
    defaults = {
        "date": date(2026, 3, 13),
        "contract_id": contract_id,
        "close": Decimal("8500.000000"),
        "high": Decimal("8600.000000"),
        "low": Decimal("8400.000000"),
        "volume": 5000,
        "oi": 40000,
    }
    return PlContractDataDaily(**(defaults | overrides))


def make_pl_derived_indicators(contract_id, **overrides) -> PlDerivedIndicators:
    defaults = {
        "date": date(2026, 3, 13),
        "contract_id": contract_id,
        "ema12": Decimal("8450.000000"),
        "ema26": Decimal("8420.000000"),
        "macd": Decimal("30.000000"),
        "rsi_14d": Decimal("55.000000"),
    }
    return PlDerivedIndicators(**(defaults | overrides))


def make_pl_algorithm_version(**overrides) -> PlAlgorithmVersion:
    defaults = {
        "name": "composite_v1",
        "version": "1.0.0",
        "horizon": "short_term",
        "is_active": True,
    }
    return PlAlgorithmVersion(**(defaults | overrides))


def make_pl_algorithm_config(algorithm_version_id, **overrides) -> PlAlgorithmConfig:
    defaults = {
        "algorithm_version_id": algorithm_version_id,
        "parameter_name": "decision_threshold_open",
        "value": "0.9",
    }
    return PlAlgorithmConfig(**(defaults | overrides))


def make_pl_indicator_daily(
    contract_id, algorithm_version_id, **overrides
) -> PlIndicatorDaily:
    defaults = {
        "date": date(2026, 3, 13),
        "contract_id": contract_id,
        "algorithm_version_id": algorithm_version_id,
        "final_indicator": Decimal("1.250000"),
        "decision": "OPEN",
        "confidence": Decimal("75.00"),
        "direction": "BULLISH",
    }
    return PlIndicatorDaily(**(defaults | overrides))


def make_pl_fundamental_article(**overrides) -> PlFundamentalArticle:
    defaults = {
        "date": date(2026, 3, 13),
        "category": "macro",
        "source": "Test Author",
        "summary": "Test summary content",
        "impact_synthesis": "Test impact synthesis",
    }
    return PlFundamentalArticle(**(defaults | overrides))


def make_pl_weather_observation(**overrides) -> PlWeatherObservation:
    defaults = {
        "date": date(2026, 3, 13),
        "observation": "Test weather report",
        "summary": "Test weather summary",
        "keywords": "rain, cocoa, ghana",
        "impact_assessment": "Test weather impact",
    }
    return PlWeatherObservation(**(defaults | overrides))


def make_aud_pipeline_run(**overrides) -> AudPipelineRun:
    defaults = {
        "pipeline_name": "test_pipeline",
        "started_at": datetime(2026, 3, 13, 21, 0),
        "status": "completed",
    }
    return AudPipelineRun(**(defaults | overrides))


def make_aud_llm_call(pipeline_run_id=None, **overrides) -> AudLlmCall:
    defaults = {
        "pipeline_run_id": pipeline_run_id,
        "provider": "openai",
        "model": "gpt-4-turbo",
    }
    return AudLlmCall(**(defaults | overrides))


def make_aud_data_quality_check(
    pipeline_run_id=None, **overrides
) -> AudDataQualityCheck:
    defaults = {
        "pipeline_run_id": pipeline_run_id,
        "check_name": "null_check",
        "passed": True,
    }
    return AudDataQualityCheck(**(defaults | overrides))


def make_pl_signal_component(
    contract_id, algorithm_version_id=None, **overrides
) -> PlSignalComponent:
    defaults = {
        "date": date(2026, 3, 13),
        "contract_id": contract_id,
        "indicator_name": "rsi_14d",
        "raw_value": Decimal("55.000000"),
        "normalized_value": Decimal("0.650000"),
        "weighted_contribution": Decimal("0.120000"),
        "algorithm_version_id": algorithm_version_id,
    }
    return PlSignalComponent(**(defaults | overrides))
