"""
Database models for Commodities Compass.

Legacy models (technicals, indicator, market_research, weather_data, test_range)
remain for backward compatibility. New MVP schema models use prefixed names
(ref_, pl_, aud_) and UUID primary keys.
"""

from .base import Base

# Legacy models
from .technicals import Technicals
from .indicator import Indicator
from .market_research import MarketResearch
from .weather_data import WeatherData
from .test_range import TestRange

# MVP schema — Reference tables
from .reference import RefExchange, RefCommodity, RefContract, RefTradingCalendar

# MVP schema — Pipeline tables
from .pipeline import (
    PlContractDataDaily,
    PlDerivedIndicators,
    PlAlgorithmVersion,
    PlAlgorithmConfig,
    PlIndicatorDaily,
    PlFundamentalArticle,
    PlWeatherObservation,
)

# MVP schema — Audit tables
from .audit import AudPipelineRun, AudLlmCall, AudDataQualityCheck

# MVP schema — Signal tables
from .signal import PlSignalComponent

__all__ = [
    "Base",
    # Legacy
    "Technicals",
    "Indicator",
    "MarketResearch",
    "WeatherData",
    "TestRange",
    # Reference
    "RefExchange",
    "RefCommodity",
    "RefContract",
    "RefTradingCalendar",
    # Pipeline
    "PlContractDataDaily",
    "PlDerivedIndicators",
    "PlAlgorithmVersion",
    "PlAlgorithmConfig",
    "PlIndicatorDaily",
    "PlFundamentalArticle",
    "PlWeatherObservation",
    # Audit
    "AudPipelineRun",
    "AudLlmCall",
    "AudDataQualityCheck",
    # Signal
    "PlSignalComponent",
]
