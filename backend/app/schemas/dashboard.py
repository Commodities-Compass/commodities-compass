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


class NewsResponse(BaseModel):
    """Response schema for news endpoint from market research."""

    date: str = Field(..., description="Date of the news article")
    title: str = Field(..., description="Title from impact_synthesis column")
    content: str = Field(..., description="Content from summary column")
    author: Optional[str] = Field(None, description="Author information")


class WeatherResponse(BaseModel):
    """Response schema for weather endpoint from weather data."""

    date: str = Field(..., description="Date of the weather update")
    description: str = Field(..., description="Weather description from text column")
    impact: str = Field(..., description="Market impact from impact_synthesis column")


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


class WeatherEnrichedResponse(WeatherResponse):
    """Enriched weather response with seasonal campaign data."""

    campaign: Optional[str] = Field(
        None, description="Campaign identifier (e.g. 2025-2026)"
    )
    campaign_health: Optional[float] = Field(
        None, description="Average score across all location-seasons"
    )
    seasons: List[SeasonStatus] = Field(
        default_factory=list, description="Season statuses"
    )
    diagnostics: List[LocationDiagnostic] = Field(
        default_factory=list, description="Per-location diagnostics"
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
    com_net_us: Optional[float] = Field(None, description="Commercial net US")


class ChartDataResponse(BaseModel):
    """Response schema for chart data endpoint."""

    data: List[ChartDataPoint] = Field(..., description="Historical chart data points")


class AudioResponse(BaseModel):
    """Response schema for audio endpoint."""

    url: str = Field(..., description="Publicly accessible URL for the audio file")
    title: str = Field(..., description="Display title for the audio")
    date: str = Field(..., description="Date of the audio in ISO format")
    filename: str = Field(..., description="Original filename of the audio")
