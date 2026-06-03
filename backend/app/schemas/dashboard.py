"""Dashboard API schemas for position status and indicators."""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class IndicatorRange(BaseModel):
    """Range definition for indicator color zones."""

    range_low: float = Field(..., description="Lower boundary of the range")
    range_high: float = Field(..., description="Upper boundary of the range")
    area: str = Field(..., description="Color zone: RED, ORANGE, or GREEN")


class CommodityIndicator(BaseModel):
    """Indicator gauge display data."""

    value: float = Field(..., description="Current indicator value")
    min: float = Field(..., description="Minimum value for the gauge scale")
    max: float = Field(..., description="Maximum value for the gauge scale")
    label: str = Field(..., description="Display label for the indicator")
    ranges: Optional[List[IndicatorRange]] = Field(
        None, description="Color zone ranges for this indicator"
    )


class PositionStatusResponse(BaseModel):
    """Response schema for position status endpoint."""

    model_config = ConfigDict(
        json_encoders={datetime: lambda v: v.isoformat(), Decimal: float}
    )

    date: datetime = Field(..., description="Date of the current position")
    position: str = Field(..., description="Current position: OPEN, HEDGE, or MONITOR")
    ytd_performance: float = Field(
        ..., description="Year-to-date performance percentage"
    )
    source_algorithm: Optional[str] = Field(
        None,
        description=(
            "Algorithm version that produced this decision for the date — "
            "e.g. 'ensemble_v1_softgate_wrapper' or 'legacy'. Resolved per "
            "(date, contract) via the date-aware resolver."
        ),
    )


class IndicatorData(BaseModel):
    """Raw indicator data from database."""

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={
            datetime: lambda v: v.isoformat(),
            Decimal: lambda v: float(v) if v is not None else None,
        },
    )

    date: datetime
    conclusion: Optional[str] = None
    final_indicator: Optional[Decimal] = None


class IndicatorsGridResponse(BaseModel):
    """Response schema for indicators grid endpoint."""

    model_config = ConfigDict(json_encoders={datetime: lambda v: v.isoformat()})

    date: datetime = Field(..., description="Date of the indicators")
    indicators: dict[str, CommodityIndicator] = Field(
        ..., description="Map of indicator names to their data"
    )
    source_algorithm: Optional[str] = Field(
        None,
        description="Algorithm version that produced the indicators for this date.",
    )


class RecommendationsResponse(BaseModel):
    """Response schema for recommendations endpoint."""

    model_config = ConfigDict(json_encoders={datetime: lambda v: v.isoformat()})

    date: datetime = Field(..., description="Date of the recommendations")
    recommendations: List[str] = Field(
        default_factory=list,
        description="List of recommendations parsed from the score column",
    )
    raw_score: Optional[str] = Field(
        None, description="Raw score text from technicals table"
    )
    source_algorithm: Optional[str] = Field(
        None,
        description=(
            "Algorithm version whose pl_indicator_daily row supplied the "
            "conclusion narrative. Note: legacy LLM narrative may be served "
            "alongside an ensemble decision (until v2 narrative ships)."
        ),
    )


class NewsResponse(BaseModel):
    """Response schema for news endpoint from market research."""

    date: str = Field(..., description="Date of the news article")
    title: Optional[str] = Field(None, description="Title from impact_synthesis column")
    content: Optional[str] = Field(None, description="Content from summary column")
    keywords: Optional[str] = Field(
        None, description="Semicolon-separated keywords from the article"
    )
    author: Optional[str] = Field(None, description="Author information")
    source_count: Optional[int] = Field(
        None, description="Number of sources successfully scraped"
    )
    total_sources: Optional[int] = Field(
        None, description="Total number of configured sources"
    )


class ThemeSentiment(BaseModel):
    """Single theme sentiment score with metadata."""

    theme: str = Field(
        ..., description="Theme name: production, chocolat, transformation, economie"
    )
    score: Optional[float] = Field(None, description="Raw sentiment score [-1.0, +1.0]")
    confidence: Optional[float] = Field(
        None, description="Confidence in the score [0.0, 1.0]"
    )
    rationale: Optional[str] = Field(None, description="One-sentence justification")
    zscore_delta: Optional[float] = Field(
        None, description="Z-score delta (3-day) — null until enough data"
    )
    has_signal: bool = Field(
        False,
        description="True for themes with Granger significance (production, chocolat)",
    )


class NewsSentimentResponse(BaseModel):
    """Response schema for theme-level sentiment endpoint."""

    date: str = Field(..., description="Date of the sentiment data")
    themes: List[ThemeSentiment] = Field(
        default_factory=list, description="Per-theme sentiment scores"
    )
    accumulation: Optional[int] = Field(
        None, description="Total days with sentiment data so far"
    )


class WeatherResponse(BaseModel):
    """Response schema for weather endpoint from weather data."""

    date: str = Field(..., description="Date of the weather update")
    description: Optional[str] = Field(
        None, description="Weather description from text column"
    )
    impact: Optional[str] = Field(
        None, description="Market impact from impact_synthesis column"
    )


class SeasonStatus(BaseModel):
    """Status of a single season within a campaign."""

    season_name: str = Field(..., description="Internal season key (e.g. saison_seche)")
    label: str = Field(..., description="Display label (e.g. Saison Sèche)")
    months_covered: str = Field(..., description="Human-readable month range")
    score: Optional[float] = Field(
        None, description="Average score across locations (1-5)"
    )
    status: str = Field(..., description="completed, in_progress, or upcoming")


class LocationDiagnostic(BaseModel):
    """Health diagnostic for a single cocoa-growing location."""

    location_name: str = Field(..., description="Location name (e.g. Daloa)")
    country: str = Field(..., description="CIV or GHA")
    score: Optional[float] = Field(
        None, description="Average score across seasons (1-5)"
    )
    status: str = Field(..., description="normal, degraded, or stress")
    harmattan_days: Optional[int] = Field(
        None, description="Cumulative Harmattan days this saison_seche"
    )


class HarmattanStatus(BaseModel):
    """Harmattan index status for the current campaign."""

    days: int = Field(..., description="Cumulative Harmattan days since Nov 1")
    threshold: int = Field(..., description="Critical threshold (24 days)")
    risk: bool = Field(..., description="True if days > threshold")
    in_season: bool = Field(
        ..., description="True if current month is in Nov-Mar window"
    )


class LocationStressHistory(BaseModel):
    """Per-location stress history over the last N days."""

    location_name: str = Field(..., description="Location name (e.g. Daloa)")
    country: str = Field(..., description="CIV or GHA")
    current_status: str = Field(..., description="normal, degraded, or stress")
    streak_days: int = Field(..., description="Consecutive days at current status")
    trend: str = Field(..., description="stable, improving, or worsening")
    history: List[str] = Field(
        default_factory=list, description="Status per day, oldest first"
    )


class WeatherEnrichedResponse(WeatherResponse):
    """Enriched weather response with seasonal campaign data."""

    campaign: Optional[str] = Field(
        None, description="Campaign identifier (e.g. 2025-2026)"
    )
    campaign_health: Optional[float] = Field(
        None,
        description=(
            "Worst-season average score (1-5). Tracks the most stressed "
            "phenological window per Copernicus EDO / Climate Central methodology."
        ),
    )
    seasons: List[SeasonStatus] = Field(
        default_factory=list, description="Season statuses"
    )
    diagnostics: List[LocationDiagnostic] = Field(
        default_factory=list, description="Per-location diagnostics (seasonal)"
    )
    daily_diagnostics: List[LocationDiagnostic] = Field(
        default_factory=list, description="Per-location diagnostics from today's LLM"
    )
    stress_history: List[LocationStressHistory] = Field(
        default_factory=list, description="Per-location stress history (last 7 days)"
    )
    impact_score: Optional[int] = Field(None, description="Parsed impact score (1-10)")
    harmattan: Optional[HarmattanStatus] = Field(
        None, description="Harmattan wind index"
    )


class ChartDataPoint(BaseModel):
    """Single data point for chart display."""

    date: str = Field(..., description="Date in YYYY-MM-DD format")
    close: Optional[float] = Field(None, description="Close price")
    volume: Optional[float] = Field(None, description="Volume")
    open_interest: Optional[float] = Field(None, description="Open interest")
    rsi_14d: Optional[float] = Field(None, description="RSI 14-day")
    macd: Optional[float] = Field(None, description="MACD")
    stock_us: Optional[float] = Field(None, description="US stock levels")
    com_net_eu: Optional[float] = Field(
        None, description="ICE EU commercial (producer/merchant) net positioning"
    )


class ChartDataResponse(BaseModel):
    """Response schema for chart data endpoint."""

    data: List[ChartDataPoint] = Field(..., description="Historical chart data points")


# ---------------------------------------------------------------------------
# Section VI — Macro & Positioning (FX + ENSO + COT EU + Stock EU)
# ---------------------------------------------------------------------------


class MacroPanelResponse(BaseModel):
    """FX + ENSO + macro context for a given date.

    Sources:
      * ``pl_external_indicator`` for FX (daily) and ENSO (monthly, lagged).
      * ``pl_orchestrator_decision`` for the ensemble-derived macro signal
        (direction / surprise / half-life). NULL on legacy-only dates.
    """

    date: str = Field(..., description="Date in YYYY-MM-DD format")
    # FX (ECB business days)
    fx_dxy_proxy: Optional[float] = Field(
        None, description="USD strength proxy (1 / EUR per USD)"
    )
    fx_gbpusd: Optional[float] = Field(None, description="USD per 1 GBP")
    fx_eurusd: Optional[float] = Field(None, description="USD per 1 EUR")
    fx_gbpeur: Optional[float] = Field(None, description="GBP per 1 EUR (audit)")
    # ENSO (monthly NOAA, look-back to most recent rowto reflect lag)
    enso_oni_month: Optional[float] = Field(
        None, description="ENSO Oceanic Niño Index (monthly average, lagged 14d)"
    )
    enso_nino34_anomaly: Optional[float] = Field(
        None, description="Niño 3.4 SST anomaly (monthly)"
    )
    enso_reference_date: Optional[str] = Field(
        None, description="Date of the ENSO row actually used (lag-corrected)"
    )
    # Ensemble-derived macro context (NULL on legacy dates)
    macro_direction: Optional[int] = Field(
        None, description="Ensemble macro direction (-1 / 0 / +1)"
    )
    macro_surprise: Optional[float] = Field(
        None, description="Ensemble macro surprise magnitude"
    )
    macro_half_life_days: Optional[int] = Field(
        None, description="Ensemble macro signal half-life"
    )
    source_algorithm: Optional[str] = Field(
        None, description="Source algorithm of the macro context"
    )


class PositioningResponse(BaseModel):
    """COT EU + COT US + Stock EU/US fundamentals.

    Sources (all weekly; payload reflects "latest on/before target_date"):
      * ``pl_cot_eu_weekly`` — ICE Europe Disaggregated COT
      * ``pl_cot_us_weekly`` — CFTC US Disaggregated COT (refactored
        2026-05-27 from the legacy ``com_net_us`` column)
      * ``pl_stock_observation`` — generic ICE certified stocks, both
        regions, canonical tonnes + native unit + report_date provenance.
    """

    date: str = Field(..., description="Date in YYYY-MM-DD format")
    # --- ICE EU COT ------------------------------------------------------
    cot_managed_money_net: Optional[int] = Field(
        None, description="ICE EU Managed Money net (long - short)"
    )
    cot_managed_money_long: Optional[int] = Field(
        None, description="ICE EU Managed Money long"
    )
    cot_managed_money_short: Optional[int] = Field(
        None, description="ICE EU Managed Money short"
    )
    cot_producer_merchant_net: Optional[int] = Field(
        None, description="ICE EU Producer/Merchant net (commercial hedgers)"
    )
    cot_open_interest: Optional[int] = Field(
        None, description="ICE EU total open interest on report"
    )
    cot_report_date: Optional[str] = Field(
        None, description="ICE EU Tuesday the report covers"
    )
    cot_release_date: Optional[str] = Field(
        None, description="ICE EU publication date (Friday)"
    )
    # --- CFTC US COT (new, parity with EU since 2026-05-27) --------------
    cot_us_managed_money_net: Optional[int] = Field(
        None, description="CFTC US Managed Money net (long - short)"
    )
    cot_us_managed_money_long: Optional[int] = Field(
        None, description="CFTC US Managed Money long"
    )
    cot_us_managed_money_short: Optional[int] = Field(
        None, description="CFTC US Managed Money short"
    )
    cot_us_producer_merchant_net: Optional[int] = Field(
        None, description="CFTC US Producer/Merchant net (commercial hedgers)"
    )
    cot_us_open_interest: Optional[int] = Field(
        None, description="CFTC US total open interest on report"
    )
    cot_us_report_date: Optional[str] = Field(
        None, description="CFTC US Tuesday the report covers"
    )
    cot_us_release_date: Optional[str] = Field(
        None, description="CFTC US publication date (Friday)"
    )
    # --- Stocks (canonical tonnes for both regions, plus EU native audit) -
    stock_eu_tonnes: Optional[float] = Field(
        None, description="ICE Europe certified stocks normalized to tonnes"
    )
    stock_eu_native_value: Optional[float] = Field(
        None,
        description="ICE EU stocks raw value as published (60kg bag count)",
    )
    stock_eu_native_unit: Optional[str] = Field(
        None, description="Native unit of stock_eu_native_value ('bags_60kg')"
    )
    stock_eu_report_date: Optional[str] = Field(
        None, description="ICE EU stocks publication date (Tuesday weekly)"
    )
    stock_us_tonnes: Optional[float] = Field(
        None, description="ICE US certified stocks (tonnes)"
    )
    stock_us_report_date: Optional[str] = Field(
        None, description="ICE US stocks publication date (Report 41)"
    )
    stock_eu_us_ratio: Optional[float] = Field(
        None,
        description=(
            "Ratio of EU stocks (tonnes) over US stocks (tonnes). "
            "Higher = more EU coverage relative to US."
        ),
    )


# ---------------------------------------------------------------------------
# Section VII — Ensemble Decision Audit (full transparency)
# ---------------------------------------------------------------------------


class SpecialistVote(BaseModel):
    """One specialist's signed vote for a date."""

    specialist_name: str = Field(
        ..., description="Specialist identifier (e.g. wm_h1_a)"
    )
    cluster: str = Field(..., description="winter | spring | unmapped")
    pred: str = Field(..., description="OPEN | HEDGE | MONITOR")
    window_months: int = Field(..., description="Lookback window in months (12 or 24)")
    n_features_used: Optional[int] = Field(
        None, description="Features actually consumed at predict-time"
    )


class SpecialistVotesResponse(BaseModel):
    """14 specialist votes for a date, with cluster mapping resolved server-side."""

    date: str = Field(..., description="Date in YYYY-MM-DD format")
    algorithm_version: str = Field(
        ..., description="ensemble_v1_softgate_wrapper expected"
    )
    votes: List[SpecialistVote] = Field(
        default_factory=list, description="14 specialist votes, cluster-tagged"
    )
    winter_signed: Optional[int] = Field(
        None,
        description=(
            "Signed sum across the Winter cluster (OPEN = +1, HEDGE = -1, "
            "MONITOR = 0). NULL if cluster mapping is empty."
        ),
    )
    spring_signed: Optional[int] = Field(
        None, description="Signed sum across the Spring cluster"
    )


class EnsembleDiagnosticsResponse(BaseModel):
    """Soft-gate + wrapper + detector diagnostics for an ensemble date.

    Mirrors ``pl_orchestrator_decision``. Returns 404 on dates with no
    ensemble row (pre-2025-12-15) — the frontend conditionally hides
    Section VII in that case.
    """

    date: str = Field(..., description="Date in YYYY-MM-DD format")
    algorithm_version: str = Field(..., description="ensemble_v1_softgate_wrapper")

    # Soft-gate
    soft_gate_decision: str = Field(..., description="OPEN | HEDGE | MONITOR")
    net_score: float = Field(..., description="Soft-gate net score (range ~[-1, +1])")
    weights_sum: float = Field(..., description="Sum of committed specialist weights")
    n_committed_specialists: int = Field(
        ..., description="Number of committed specialists (out of 14)"
    )

    # Wrapper
    decision_wrapped: str = Field(
        ..., description="Final wrapped decision (mirrored to pl_indicator_daily)"
    )
    wrapper_active: bool = Field(
        ..., description="True if the Compass wrapper modified the soft-gate output"
    )
    fired_running_acc: bool = Field(..., description="Running-accuracy gate fired")
    fired_trend: bool = Field(
        ..., description="Trend-conflict detector fired (inactive v1.0.0)"
    )
    fired_dispersion: bool = Field(..., description="Cluster-dispersion detector fired")
    fired_three_way: bool = Field(
        ..., description="Three-way disagreement detector fired (inactive v1.0.0)"
    )

    # Diagnostics (every column NULLABLE — see pipeline-continuity rule)
    running_acc_5d: Optional[float] = Field(None)
    realized_return_5d: Optional[float] = Field(None)
    winter_vote_signed: Optional[int] = Field(None)
    spring_vote_signed: Optional[int] = Field(None)
    macro_direction: Optional[int] = Field(None)
    macro_surprise: Optional[float] = Field(None)
    macro_half_life_days: Optional[int] = Field(None)
    anomaly_score_z: Optional[float] = Field(None)
    prior_open: Optional[float] = Field(None)
    prior_hedge: Optional[float] = Field(None)
    prior_monitor: Optional[float] = Field(None)


class AudioResponse(BaseModel):
    """Response schema for audio endpoint."""

    url: str = Field(..., description="Publicly accessible URL for the audio file")
    title: str = Field(..., description="Display title for the audio")
    date: str = Field(..., description="Date of the audio in ISO format")
    filename: str = Field(..., description="Original filename of the audio")
