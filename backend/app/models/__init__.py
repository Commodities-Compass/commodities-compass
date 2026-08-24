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
from .reference import (
    RefExchange,
    RefCommodity,
    RefContract,
    RefTradingCalendar,
    RefAlertRule,
)

# MVP schema — Pipeline tables
from .pipeline import (
    PlContractDataDaily,
    PlContractDataIntraday,
    PlDerivedIndicators,
    PlDashboardGauge,
    PlAlgorithmVersion,
    PlAlgorithmConfig,
    PlIndicatorDaily,
    PlFundamentalArticle,
    PlWeatherObservation,
    PlSeasonalScore,
)

# MVP schema — Origin physical flows (WatchAI ingestion)
from .origin import (
    PlOriginIngestBatch,
    RefOriginEntity,
    PlOriginExportDeclaration,
    PlOriginPurchaseMonthly,
    PlOriginGrindingMonthly,
    PlOriginFlowMonthly,
)

# MVP schema — Audit tables
from .audit import AudPipelineRun, AudLlmCall, AudDataQualityCheck, AudAlertEvent

# MVP schema — Signal tables
from .signal import PlSignalComponent

# Tenant schema — per-client accounts, seats, entitlements (serving-layer only)
from .tenant import TenantAccount, TenantUser, TenantEntitlement

# Billing — recurring EUR collection. Never writes tenant_entitlement.
from .billing import (
    AudBillingEvent,
    TenantBillingInvoice,
    TenantBillingSubscription,
)

__all__ = [
    "Base",
    "TestRange",
    # Reference
    "RefExchange",
    "RefCommodity",
    "RefContract",
    "RefTradingCalendar",
    "RefAlertRule",
    # Pipeline
    "PlContractDataDaily",
    "PlContractDataIntraday",
    "PlDerivedIndicators",
    "PlDashboardGauge",
    "PlAlgorithmVersion",
    "PlAlgorithmConfig",
    "PlIndicatorDaily",
    "PlFundamentalArticle",
    "PlWeatherObservation",
    "PlSeasonalScore",
    # Origin physical flows
    "PlOriginIngestBatch",
    "RefOriginEntity",
    "PlOriginExportDeclaration",
    "PlOriginPurchaseMonthly",
    "PlOriginGrindingMonthly",
    "PlOriginFlowMonthly",
    # Audit
    "AudPipelineRun",
    "AudLlmCall",
    "AudDataQualityCheck",
    "AudAlertEvent",
    # Signal
    "PlSignalComponent",
    # Tenant
    "TenantAccount",
    "TenantUser",
    "TenantEntitlement",
    # Billing
    "TenantBillingSubscription",
    "TenantBillingInvoice",
    "AudBillingEvent",
]
