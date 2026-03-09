"""Factory functions for creating test model instances."""

from datetime import datetime
from decimal import Decimal

from app.models.indicator import Indicator
from app.models.market_research import MarketResearch
from app.models.technicals import Technicals
from app.models.test_range import TestRange
from app.models.weather_data import WeatherData


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
