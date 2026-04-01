"""
Database models for Commodities Compass.

Legacy model files (technicals, indicator, market_research, weather_data)
are kept for Alembic migration history. They are NOT imported here —
use pl_* tables for all new code.
"""

from .base import Base

# Legacy — only test_range is still used by dashboard (gauge color zones)
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
    PlSeasonalScore,
)

# MVP schema — Audit tables
from .audit import AudPipelineRun, AudLlmCall, AudDataQualityCheck

# MVP schema — Signal tables
from .signal import PlSignalComponent

__all__ = [
    "Base",
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
    "PlSeasonalScore",
    # Audit
    "AudPipelineRun",
    "AudLlmCall",
    "AudDataQualityCheck",
    # Signal
    "PlSignalComponent",
]
