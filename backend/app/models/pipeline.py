"""Pipeline tables for the MVP schema.

Raw market data, derived indicators, algorithm config, daily signals,
fundamentals, and weather. All in public schema with pl_ prefix.
Wide columns for indicators (36 columns, not EAV).
Contract-centric keying: (date, contract_id).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    DATE,
    DECIMAL,
    INTEGER,
    TEXT,
    TIMESTAMP,
    VARCHAR,
    Boolean,
    CheckConstraint,
    Computed,
    ForeignKey,
    Index,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import DOUBLE_PRECISION, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class PlContractDataDaily(Base):
    """Raw OHLCV + fundamentals per contract per day.

    Replaces columns A-I of the TECHNICALS Google Sheet.
    Contract-centric: keyed on (date, contract_id), not commodity.
    """

    __tablename__ = "pl_contract_data_daily"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    date: Mapped[date] = mapped_column(DATE, nullable=False)
    contract_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ref_contract.id"), nullable=False
    )

    # OHLCV
    open: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    high: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    low: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    close: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    volume: Mapped[Optional[int]] = mapped_column(INTEGER)
    oi: Mapped[Optional[int]] = mapped_column(INTEGER)

    # Additional market data.
    # Weekly stocks (US + EU) and CFTC US commercial net live in dedicated
    # tables (pl_stock_observation, pl_cot_us_weekly) since 2026-05-27 —
    # they're weekly cadence with their own report_date provenance and don't
    # belong on the daily OHLCV row.
    implied_volatility: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))

    # Display date = next trading day after session date.
    # Dashboard queries filter by this column. NULL for pre-calendar historical data.
    display_date: Mapped[Optional[date]] = mapped_column(DATE)

    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("date", "contract_id", name="uq_contract_data_daily"),
        Index("ix_contract_data_daily_date", "date"),
        Index("ix_contract_data_daily_display_date", "display_date"),
    )


class PlDerivedIndicators(Base):
    """Wide columns for 27+ technical indicators per contract per day.

    Replaces columns J-AT of the TECHNICALS Google Sheet.
    Mirrors the existing Technicals model indicator columns.
    """

    __tablename__ = "pl_derived_indicators"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    date: Mapped[date] = mapped_column(DATE, nullable=False)
    contract_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ref_contract.id"), nullable=False
    )

    # Pivot points
    r3: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    r2: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    r1: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    pivot: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    s1: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    s2: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    s3: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))

    # Moving averages + MACD
    ema12: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    ema26: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    macd: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    macd_signal: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))

    # RSI + Stochastic
    rsi_14d: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    stochastic_k_14: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    stochastic_d_14: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))

    # Volatility
    atr: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    atr_14d: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))

    # Bollinger Bands
    bollinger: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    bollinger_upper: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    bollinger_lower: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    bollinger_width: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))

    # Ratios
    close_pivot_ratio: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    volume_oi_ratio: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))

    # RSI internals
    gain_14d: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    loss_14d: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    rs: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))

    # Daily return (new — not in legacy)
    daily_return: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))

    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("date", "contract_id", name="uq_derived_indicators"),
        Index("ix_derived_indicators_date", "date"),
    )


class PlAlgorithmVersion(Base):
    """Algorithm version tracking. Today's CONFIG columns become rows here."""

    __tablename__ = "pl_algorithm_version"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(VARCHAR(100), nullable=False)
    version: Mapped[str] = mapped_column(VARCHAR(50), nullable=False)
    horizon: Mapped[str] = mapped_column(
        VARCHAR(50), nullable=False, default="short_term"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    compute_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    description: Mapped[Optional[str]] = mapped_column(TEXT)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())

    __table_args__ = (UniqueConstraint("name", "version", name="uq_algorithm_version"),)


class PlAlgorithmConfig(Base):
    """Coefficients per algorithm version. Config as data, not code."""

    __tablename__ = "pl_algorithm_config"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    algorithm_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pl_algorithm_version.id"), nullable=False
    )
    parameter_name: Mapped[str] = mapped_column(VARCHAR(100), nullable=False)
    value: Mapped[str] = mapped_column(TEXT, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(TEXT)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "algorithm_version_id",
            "parameter_name",
            name="uq_algorithm_config_param",
        ),
    )


class PlIndicatorDaily(Base):
    """Z-scores, composite score, and trading decision per contract per day.

    Replaces the INDICATOR Google Sheet.
    Keyed on (date, contract_id, algorithm_version_id) to enable
    multi-version algorithm comparison.
    """

    __tablename__ = "pl_indicator_daily"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    date: Mapped[date] = mapped_column(DATE, nullable=False)
    contract_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ref_contract.id"), nullable=False
    )
    algorithm_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pl_algorithm_version.id"), nullable=False
    )

    # Raw indicator scores (-6 to +6 range)
    rsi_score: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    macd_score: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    stochastic_score: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    atr_score: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    close_pivot: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    volume_oi: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))

    # Normalized z-scores (0-1 scale)
    rsi_norm: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    macd_norm: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    stoch_k_norm: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    atr_norm: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    close_pivot_norm: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    vol_oi_norm: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))

    # Composites
    indicator_value: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    momentum: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    macroeco_bonus: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    macroeco_score: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    final_indicator: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))

    # Decision
    decision: Mapped[Optional[str]] = mapped_column(VARCHAR(50))
    confidence: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(5, 2))
    confidence_rationale: Mapped[Optional[str]] = mapped_column(TEXT)
    direction: Mapped[Optional[str]] = mapped_column(VARCHAR(50))
    eco: Mapped[Optional[str]] = mapped_column(TEXT)
    conclusion: Mapped[Optional[str]] = mapped_column(TEXT)

    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "date",
            "contract_id",
            "algorithm_version_id",
            name="uq_indicator_daily",
        ),
        Index("ix_indicator_daily_date", "date"),
    )


class PlFundamentalArticle(Base):
    """Press review + fundamentals. Replaces BIBLIO_ALL / market_research."""

    __tablename__ = "pl_fundamental_article"
    __table_args__ = (
        UniqueConstraint(
            "date", "llm_provider", name="uq_fundamental_article_date_provider"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    date: Mapped[date] = mapped_column(DATE, nullable=False, index=True)
    category: Mapped[str] = mapped_column(VARCHAR(50), nullable=False, default="macro")
    source: Mapped[Optional[str]] = mapped_column(VARCHAR(200))
    title: Mapped[Optional[str]] = mapped_column(VARCHAR(500))
    summary: Mapped[Optional[str]] = mapped_column(TEXT)
    keywords: Mapped[Optional[str]] = mapped_column(TEXT)
    sentiment: Mapped[Optional[str]] = mapped_column(VARCHAR(50))
    impact_synthesis: Mapped[Optional[str]] = mapped_column(TEXT)
    llm_provider: Mapped[str] = mapped_column(VARCHAR(50), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=False, server_default="false")
    source_count: Mapped[Optional[int]] = mapped_column()
    total_sources: Mapped[Optional[int]] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())


class PlWeatherObservation(Base):
    """Weather data. Replaces METEO_ALL / weather_data."""

    __tablename__ = "pl_weather_observation"
    __table_args__ = (UniqueConstraint("date", name="uq_weather_observation_date"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    date: Mapped[date] = mapped_column(DATE, nullable=False, index=True)
    region: Mapped[Optional[str]] = mapped_column(VARCHAR(100))
    observation: Mapped[Optional[str]] = mapped_column(TEXT)
    summary: Mapped[Optional[str]] = mapped_column(TEXT)
    keywords: Mapped[Optional[str]] = mapped_column(TEXT)
    impact_assessment: Mapped[Optional[str]] = mapped_column(TEXT)
    diagnostics: Mapped[Optional[dict]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())


class PlSeasonalScore(Base):
    """Per-location seasonal score for campaign memory.

    One row per (campaign, season, location). Computed from Open-Meteo
    historical data at each season transition. Injected into the meteo
    agent prompt to provide cumulative context.
    """

    __tablename__ = "pl_seasonal_score"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    campaign: Mapped[str] = mapped_column(VARCHAR(20), nullable=False)
    season_name: Mapped[str] = mapped_column(VARCHAR(50), nullable=False)
    location_name: Mapped[str] = mapped_column(VARCHAR(100), nullable=False)
    months_covered: Mapped[str] = mapped_column(VARCHAR(50), nullable=False)
    start_date: Mapped[date] = mapped_column(DATE, nullable=False)
    end_date: Mapped[date] = mapped_column(DATE, nullable=False)
    total_precip_mm: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(8, 1))
    total_et0_mm: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(8, 1))
    cumulative_balance_mm: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(8, 1))
    days_rain: Mapped[Optional[int]] = mapped_column(INTEGER)
    days_stress_temp: Mapped[Optional[int]] = mapped_column(INTEGER)
    avg_tmax: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(4, 1))
    harmattan_days: Mapped[Optional[int]] = mapped_column(INTEGER)
    score: Mapped[Decimal] = mapped_column(DECIMAL(2, 1), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "campaign", "season_name", "location_name", name="uq_seasonal_score"
        ),
        Index("ix_seasonal_score_campaign", "campaign"),
    )


class PlArticleSegment(Base):
    """Structured segment extracted from a press review article.

    MODEL-ONLY — the extraction pipeline and API endpoints live on
    feat/pattern-extractor. This model is on main solely because the
    migration was applied to prod before the branch was merged. The table
    and its data exist in GCP; this model lets Alembic and SQLAlchemy
    stay in sync. If the branch is never merged, the model and migration
    can be dropped together with a down-migration.

    Each row represents one zone x theme segment. An article can produce
    0-8 segments (2 zones x 4 themes). Segments are immutable — re-extraction
    with a new prompt creates rows with a different extraction_version.
    """

    __tablename__ = "pl_article_segment"
    __table_args__ = (
        UniqueConstraint(
            "article_id",
            "zone",
            "theme",
            "extraction_version",
            name="uq_article_segment",
        ),
        Index("ix_article_segment_zone_theme", "zone", "theme"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    article_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("pl_fundamental_article.id"), nullable=False, index=True
    )
    article_date: Mapped[date] = mapped_column(DATE, nullable=False, index=True)
    zone: Mapped[str] = mapped_column(VARCHAR(30), nullable=False)
    theme: Mapped[str] = mapped_column(VARCHAR(30), nullable=False)

    # Extracted content
    facts: Mapped[Optional[str]] = mapped_column(TEXT)
    causal_chains: Mapped[Optional[str]] = mapped_column(TEXT)
    sentiment: Mapped[Optional[str]] = mapped_column(VARCHAR(20))
    sentiment_score: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(3, 2))
    entities: Mapped[Optional[str]] = mapped_column(TEXT)
    confidence: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(3, 2))

    # Metadata
    llm_provider: Mapped[str] = mapped_column(VARCHAR(50), nullable=False)
    llm_model: Mapped[str] = mapped_column(VARCHAR(100), nullable=False)
    extraction_version: Mapped[str] = mapped_column(
        VARCHAR(20), nullable=False, default="v1"
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())


class PlSentimentFeature(Base):
    """Daily z-score delta features derived from pl_article_segment sentiment.

    Shadow mode: computed and stored daily but NOT injected into the trading
    engine composite score. Will be activated when n > 250 (~October 2026).

    Pipeline: pl_article_segment (inline_v1) → aggregate by (date, theme)
    → rolling z-score (21 days) → delta 3 days → this table.
    """

    __tablename__ = "pl_sentiment_feature"
    __table_args__ = (
        UniqueConstraint("date", "theme", name="uq_sentiment_feature_date_theme"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    date: Mapped[date] = mapped_column(DATE, nullable=False, index=True)
    theme: Mapped[str] = mapped_column(VARCHAR(30), nullable=False)
    raw_score: Mapped[Optional[float]] = mapped_column(DECIMAL(6, 3))
    zscore: Mapped[Optional[float]] = mapped_column(DECIMAL(6, 3))
    zscore_delta: Mapped[Optional[float]] = mapped_column(DECIMAL(6, 3))
    min_periods_met: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())


class PlExternalIndicator(Base):
    """ENSO + FX time series, commodity-agnostic, keyed on date only.

    Shared by 2 scrapers (cc-enso-scraper monthly + cc-fx-scraper daily). Each
    scraper writes its own columns via UPSERT; ENSO writes monthly rows at
    YYYY-MM-01, FX writes daily rows at business-day dates. No conflict — the
    engine ensemble joins this table via merge_asof.

    Lag policy (applied at compute-time, not here):
      * ENSO: 14 days (NOAA publishes mid-month for prior month).
      * FX: none (ECB publishes ~16:00 CET, business days).
    """

    __tablename__ = "pl_external_indicator"
    __table_args__ = (
        UniqueConstraint("date", name="uq_external_indicator_date"),
        Index("ix_external_indicator_date", "date"),
    )

    # server_default required because db_writer.py uses raw INSERT VALUES
    # without specifying id (partial UPSERT pattern). Python-side default
    # only fires through the ORM.
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    date: Mapped[date] = mapped_column(DATE, nullable=False)

    # ENSO (monthly publication, date = 1st of month, lag applied at compute-time)
    enso_oni_month: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(8, 4))
    enso_nino34_anomaly: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(8, 4))

    # FX (daily business-days — written by cc-fx-scraper, see P1-scraper-fx.md)
    fx_dxy_proxy: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    fx_gbpusd: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    fx_eurusd: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    fx_gbpeur: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))

    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())


class PlCotEuWeekly(Base):
    """ICE COT Europe weekly positioning (cocoa London #7 + multi-market ready).

    Source: ICE public CSV ``publicdocs/futures/COTHistYYYY.csv`` (one file
    per year, ~250 rows for ~52 weeks × 5 markets). Each row is one weekly
    snapshot. We filter for "ICE Cocoa Futures - ICE Futures Europe" rows
    where ``FutOnly_or_Combined='FutOnly'`` (standard CFTC convention).

    Schema chosen per docs/user-stories/P1-scrapers-stock-cot-eu.md §4.1
    (revised 2026-05-19): dedicated table rather than columns on
    ``pl_contract_data_daily`` because the data is weekly, not daily.

    ``prod_merc_net`` and ``m_money_net`` are GENERATED columns (Postgres
    auto-computed) — never write to them directly.

    Z-scores (26w) and percentiles are computed at engine time (rolling
    normalization, not stored here).
    """

    __tablename__ = "pl_cot_eu_weekly"
    __table_args__ = (
        UniqueConstraint("release_date", "contract_market", name="uq_cot_eu_weekly"),
        Index("ix_cot_eu_weekly_report_date", "report_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    # When ICE published the report (Friday for Tuesday snapshot, conventionally).
    release_date: Mapped[date] = mapped_column(DATE, nullable=False)
    # The Tuesday the report covers (CSV column "As_of_Date_Form_MM/DD/YYYY").
    report_date: Mapped[date] = mapped_column(DATE, nullable=False)
    # Multi-market ready (default 'cocoa', extensible to coffee/sugar later).
    contract_market: Mapped[str] = mapped_column(
        VARCHAR(50), nullable=False, server_default="cocoa"
    )

    # Producer / Merchant / Processor / User (commercial hedgers)
    prod_merc_long: Mapped[Optional[int]] = mapped_column(INTEGER)
    prod_merc_short: Mapped[Optional[int]] = mapped_column(INTEGER)
    prod_merc_net: Mapped[Optional[int]] = mapped_column(
        INTEGER,
        Computed("prod_merc_long - prod_merc_short", persisted=True),
    )

    # Managed Money (non-commercial speculative — the R&D signal driver)
    m_money_long: Mapped[Optional[int]] = mapped_column(INTEGER)
    m_money_short: Mapped[Optional[int]] = mapped_column(INTEGER)
    m_money_net: Mapped[Optional[int]] = mapped_column(
        INTEGER,
        Computed("m_money_long - m_money_short", persisted=True),
    )

    # Other Reportables + Non-Reportable (audit-only categories)
    other_rept_long: Mapped[Optional[int]] = mapped_column(INTEGER)
    other_rept_short: Mapped[Optional[int]] = mapped_column(INTEGER)
    non_rept_long: Mapped[Optional[int]] = mapped_column(INTEGER)
    non_rept_short: Mapped[Optional[int]] = mapped_column(INTEGER)

    # Total OI on the report — used for %OI normalization downstream
    open_interest: Mapped[Optional[int]] = mapped_column(INTEGER)

    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())


class PlCotUsWeekly(Base):
    """CFTC US COT weekly positioning (mirrors ``pl_cot_eu_weekly``).

    Source: CFTC Agriculture Long Format report
    ``https://www.cftc.gov/dea/futures/ag_lf.htm``, COCOA - ICE FUTURES U.S.
    section. Weekly snapshot Tuesday, release Friday ~21:30 CET.

    Schema future-proofs the table with Managed Money / Other Reportable /
    Non-Reportable columns even though the current scraper only extracts
    Producer/Merchant — backfilled historical rows leave them NULL.
    ``prod_merc_net`` and ``m_money_net`` are GENERATED columns
    (long − short) — never write to them directly.
    """

    __tablename__ = "pl_cot_us_weekly"
    __table_args__ = (
        UniqueConstraint("release_date", "contract_market", name="uq_cot_us_weekly"),
        Index("ix_cot_us_weekly_report_date", "report_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    release_date: Mapped[date] = mapped_column(DATE, nullable=False)
    report_date: Mapped[date] = mapped_column(DATE, nullable=False)
    contract_market: Mapped[str] = mapped_column(
        VARCHAR(50), nullable=False, server_default="cocoa"
    )

    prod_merc_long: Mapped[Optional[int]] = mapped_column(INTEGER)
    prod_merc_short: Mapped[Optional[int]] = mapped_column(INTEGER)
    prod_merc_net: Mapped[Optional[int]] = mapped_column(
        INTEGER,
        Computed("prod_merc_long - prod_merc_short", persisted=True),
    )

    m_money_long: Mapped[Optional[int]] = mapped_column(INTEGER)
    m_money_short: Mapped[Optional[int]] = mapped_column(INTEGER)
    m_money_net: Mapped[Optional[int]] = mapped_column(
        INTEGER,
        Computed("m_money_long - m_money_short", persisted=True),
    )

    other_rept_long: Mapped[Optional[int]] = mapped_column(INTEGER)
    other_rept_short: Mapped[Optional[int]] = mapped_column(INTEGER)
    non_rept_long: Mapped[Optional[int]] = mapped_column(INTEGER)
    non_rept_short: Mapped[Optional[int]] = mapped_column(INTEGER)

    open_interest: Mapped[Optional[int]] = mapped_column(INTEGER)

    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())


class PlStockObservation(Base):
    """ICE certified cocoa stocks — generic region-agnostic table.

    One row per (region, report_date, contract_market) publication. Stores
    both the source's native unit (``value_native`` + ``unit_native``) and
    a normalized ``value_tonnes`` so consumers can compare regions without
    re-implementing the bag→tonne math at every call site.

    Replaces ``pl_contract_data_daily.stock_us`` and
    ``pl_contract_data_daily.stock_eu_bags60kg`` (migration r2m3n4o5p6q7,
    2026-05-27) — the daily contract row was the wrong home for weekly data
    with its own publication cadence and provenance.

    Sources today:
      * region='us', source='ice_us_report41' — daily-cadence URL but
        often-flat values; native unit tonnes (the scraper already converts
        from 70-lb bags at ingest).
      * region='eu', source='barchart_ic345drw' — ICE Europe weekly Tuesday
        publication; native unit 60kg bags (raw count, Barchart convention).
    """

    __tablename__ = "pl_stock_observation"
    __table_args__ = (
        CheckConstraint("region IN ('us', 'eu')", name="ck_stock_observation_region"),
        CheckConstraint(
            "unit_native IN ('tonnes', 'bags_60kg')",
            name="ck_stock_observation_unit_native",
        ),
        UniqueConstraint(
            "region", "report_date", "contract_market", name="uq_stock_observation"
        ),
        Index(
            "ix_stock_observation_lookup",
            "region",
            "contract_market",
            text("report_date DESC"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    region: Mapped[str] = mapped_column(VARCHAR(10), nullable=False)
    report_date: Mapped[date] = mapped_column(DATE, nullable=False)
    value_native: Mapped[Decimal] = mapped_column(DECIMAL(15, 6), nullable=False)
    unit_native: Mapped[str] = mapped_column(VARCHAR(15), nullable=False)
    value_tonnes: Mapped[Decimal] = mapped_column(DECIMAL(15, 6), nullable=False)
    contract_market: Mapped[str] = mapped_column(
        VARCHAR(50), nullable=False, server_default="cocoa"
    )
    source: Mapped[str] = mapped_column(VARCHAR(40), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now()
    )


class PlModelArtifact(Base):
    """Campaign 5 ensemble — ML artifact registry stored in Postgres as BYTEA.

    Replaces the original `gs://cacaooo-rnd-models/` GCS bucket design with
    in-DB storage per CAMPAIGN_5_PROD_DEPLOYMENT.md §4.5 + §7. Each row holds
    ONE serialized payload (pickle / JSON / parquet / CSV) plus full
    provenance (SHA-256, train range, lib versions). The ensemble pipeline
    loads artifacts at job time via `ensemble.artifact_io.DBArtifactLoader`,
    which re-verifies SHA-256 before deserializing (fail-loud rule §0 #1).

    Layout per delivery: ~38 rows
      * 14 × specialist_model (`.pkl`)
      * 14 × specialist_hp (`.json`)
      * 3  × long_run (anomaly, priors, regime_clusters)
      * 2  × tuned_config (soft_gate, wrapper)
      * 5  × canonical_snapshot (parquet + csv)

    Unique on (algorithm_version_id, artifact_kind, artifact_name,
    training_month) so monthly retrains UPSERT new rows alongside the
    previous month's frozen set.
    """

    __tablename__ = "pl_model_artifact"
    __table_args__ = (
        UniqueConstraint(
            "algorithm_version_id",
            "artifact_kind",
            "artifact_name",
            "training_month",
            name="uq_pl_model_artifact",
        ),
        Index(
            "ix_pl_model_artifact_kind",
            "algorithm_version_id",
            "artifact_kind",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    algorithm_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pl_algorithm_version.id"), nullable=False
    )

    # Allowed values validated app-side (see ensemble.artifact_io):
    #   specialist_model, specialist_hp,
    #   long_run_anomaly, long_run_priors, long_run_regime_clusters,
    #   soft_gate_config, wrapper_config, canonical_snapshot.
    artifact_kind: Mapped[str] = mapped_column(VARCHAR(64), nullable=False)
    artifact_name: Mapped[str] = mapped_column(VARCHAR(128), nullable=False)

    # 'YYYY-MM' for specialist_*; NULL for long_run/config/canonical artifacts
    # that don't refit monthly.
    training_month: Mapped[Optional[str]] = mapped_column(VARCHAR(7))

    payload: Mapped[bytes] = mapped_column(nullable=False)
    payload_encoding: Mapped[str] = mapped_column(VARCHAR(16), nullable=False)
    sha256: Mapped[str] = mapped_column(VARCHAR(64), nullable=False)
    n_bytes: Mapped[int] = mapped_column(INTEGER, nullable=False)

    # Provenance (rule §0 #3 — pipeline-continuity, every column traceable)
    fit_train_start: Mapped[Optional[date]] = mapped_column(DATE)
    fit_train_end: Mapped[Optional[date]] = mapped_column(DATE)
    n_train: Mapped[Optional[int]] = mapped_column(INTEGER)
    class_balance: Mapped[Optional[dict]] = mapped_column(JSONB)
    git_sha: Mapped[str] = mapped_column(VARCHAR(40), nullable=False)
    python_version: Mapped[str] = mapped_column(VARCHAR(20), nullable=False)
    lib_versions: Mapped[dict] = mapped_column(JSONB, nullable=False)

    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())


class PlSpecialistPrediction(Base):
    """Campaign 5 ensemble — per-specialist daily vote audit.

    One row per (date, contract_id, algorithm_version_id, specialist_name).
    Feeds the wrapper's cluster-dispersion detector and Phase 5 post-hoc
    analysis ("which specialists were wrong on day X?"). `forward_return_6d`
    is back-filled once the h=6 horizon expires.
    """

    __tablename__ = "pl_specialist_prediction"
    __table_args__ = (
        UniqueConstraint(
            "date",
            "contract_id",
            "algorithm_version_id",
            "specialist_name",
            name="uq_specialist_prediction",
        ),
        Index(
            "ix_specialist_prediction_date_version",
            "date",
            "algorithm_version_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    date: Mapped[date] = mapped_column(DATE, nullable=False)
    contract_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ref_contract.id"), nullable=False
    )
    algorithm_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pl_algorithm_version.id"), nullable=False
    )
    specialist_name: Mapped[str] = mapped_column(VARCHAR(64), nullable=False)
    # 12 (baseline/TB/calibrated-TB) or 24 (GARCH) — per R&D pool config.
    window_months: Mapped[int] = mapped_column(INTEGER, nullable=False)
    # "OPEN" | "HEDGE" | "MONITOR"
    pred: Mapped[str] = mapped_column(VARCHAR(10), nullable=False)
    n_features_used: Mapped[Optional[int]] = mapped_column(INTEGER)
    forward_return_6d: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())


class PlOrchestratorDecision(Base):
    """Campaign 5 ensemble — soft-gate + wrapper audit trail.

    One row per (date, contract_id, algorithm_version_id). Captures both
    decision layers: the raw soft-gate output (``soft_gate_decision``) and
    the final wrapped output (``decision_wrapped``) that
    ``pl_indicator_daily`` mirrors.

    Every diagnostic column is NULLABLE so day-1 / data-edge cases write
    NULL rather than the silent 0.0 placeholder that rule §0 #3 forbids
    (pipeline-continuity).
    """

    __tablename__ = "pl_orchestrator_decision"
    __table_args__ = (
        UniqueConstraint(
            "date",
            "contract_id",
            "algorithm_version_id",
            name="uq_orchestrator_decision",
        ),
        Index(
            "ix_orchestrator_decision_date_version",
            "date",
            "algorithm_version_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    date: Mapped[date] = mapped_column(DATE, nullable=False)
    contract_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ref_contract.id"), nullable=False
    )
    algorithm_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pl_algorithm_version.id"), nullable=False
    )

    # Soft-gate layer
    soft_gate_decision: Mapped[str] = mapped_column(VARCHAR(10), nullable=False)
    net_score: Mapped[Decimal] = mapped_column(DECIMAL(15, 6), nullable=False)
    weights_sum: Mapped[Decimal] = mapped_column(DECIMAL(15, 6), nullable=False)
    n_committed_specialists: Mapped[int] = mapped_column(INTEGER, nullable=False)

    # Wrapper layer (final decision mirrored to pl_indicator_daily)
    decision_wrapped: Mapped[str] = mapped_column(VARCHAR(10), nullable=False)
    wrapper_active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    fired_running_acc: Mapped[bool] = mapped_column(Boolean, nullable=False)
    fired_trend: Mapped[bool] = mapped_column(Boolean, nullable=False)
    fired_dispersion: Mapped[bool] = mapped_column(Boolean, nullable=False)
    fired_three_way: Mapped[bool] = mapped_column(Boolean, nullable=False)

    # Diagnostics (all NULLABLE — write NULL on missing, never silent 0.0)
    running_acc_5d: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(8, 6))
    realized_return_5d: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    winter_vote_signed: Mapped[Optional[int]] = mapped_column(INTEGER)
    spring_vote_signed: Mapped[Optional[int]] = mapped_column(INTEGER)
    macro_direction: Mapped[Optional[int]] = mapped_column(INTEGER)
    macro_surprise: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(8, 6))
    macro_half_life_days: Mapped[Optional[int]] = mapped_column(INTEGER)
    anomaly_score_z: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    prior_open: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(8, 6))
    prior_hedge: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(8, 6))
    prior_monitor: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(8, 6))

    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())


class PlSupplyDemandObservation(Base):
    """Unified EAV-style storage for fundamental supply/demand metrics.

    Populated by quarterly grindings scrapers (ECA, NCA) and future
    fundamentals (ICCO crop forecasts, CCC arrivals, COCOBOD production).
    Each row stores one (metric_name, value) tuple keyed on
    ``(publication_date, category, source, region, period_label,
    metric_name)``. EAV-style chosen over typed columns to absorb new
    metrics without schema migrations — see P3 user story §2.1.

    Distinct from ``pl_fundamental_article`` (LLM-extracted narrative).
    """

    __tablename__ = "pl_supply_demand_observation"
    __table_args__ = (
        UniqueConstraint(
            "publication_date",
            "category",
            "source",
            "region",
            "period_label",
            "metric_name",
            name="uq_supply_demand_observation",
        ),
        Index(
            "ix_supply_demand_observation_lookup",
            "category",
            "source",
            "period_date",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    publication_date: Mapped[date] = mapped_column(DATE, nullable=False)
    period_date: Mapped[date] = mapped_column(DATE, nullable=False)
    period_label: Mapped[str] = mapped_column(VARCHAR(20), nullable=False)
    category: Mapped[str] = mapped_column(VARCHAR(30), nullable=False)
    source: Mapped[str] = mapped_column(VARCHAR(30), nullable=False)
    region: Mapped[Optional[str]] = mapped_column(VARCHAR(30))
    metric_name: Mapped[str] = mapped_column(VARCHAR(50), nullable=False)
    value: Mapped[Optional[float]] = mapped_column(DOUBLE_PRECISION)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())
