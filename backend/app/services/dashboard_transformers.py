"""
Dashboard data transformers.

Transforms database query results into API response formats.
Separates data transformation logic from API endpoints.
"""

import logging
from typing import Any, Dict, List, Optional
from datetime import date

from app.schemas.dashboard import (
    PositionStatusResponse,
    CommodityIndicator,
    IndicatorRange,
    IndicatorsGridResponse,
    RecommendationsResponse,
    NewsResponse,
    WeatherResponse,
    WeatherEnrichedResponse,
    HarmattanStatus,
    SeasonStatus,
    LocationDiagnostic,
    ChartDataResponse,
    ChartDataPoint,
)
from app.utils.date_utils import format_date_for_display


_VALID_POSITIONS = {"OPEN", "HEDGE", "MONITOR"}

_position_logger = logging.getLogger(__name__)


def transform_to_position_status_response(
    position: Optional[str],
    ytd_performance: float,
    response_date,
) -> PositionStatusResponse:
    """Transform position data to PositionStatusResponse."""
    original = position
    if position:
        position = position.strip().upper()
    if not position or position not in _VALID_POSITIONS:
        _position_logger.error(
            "UNEXPECTED POSITION VALUE: got %r, expected one of %s — "
            "defaulting to MONITOR. This indicates a data quality issue "
            "in pl_indicator_daily.decision. Investigate immediately.",
            original,
            _VALID_POSITIONS,
        )
        position = "MONITOR"

    return PositionStatusResponse(
        date=response_date,
        position=position,
        ytd_performance=ytd_performance,
    )


def transform_to_indicators_grid_response(
    indicators_data: Dict[str, Dict[str, Any]],
    response_date: date,
) -> IndicatorsGridResponse:
    """Transform indicators data to IndicatorsGridResponse."""
    indicators = {}

    for indicator_name, data in indicators_data.items():
        ranges = [
            IndicatorRange(
                range_low=r["range_low"],
                range_high=r["range_high"],
                area=r["area"],
            )
            for r in data["ranges"]
        ]

        indicators[indicator_name] = CommodityIndicator(
            value=data["value"],
            min=data["min"],
            max=data["max"],
            label=data["label"],
            ranges=ranges,
        )

    from datetime import datetime

    response_datetime = datetime.combine(response_date, datetime.min.time())

    return IndicatorsGridResponse(
        date=response_datetime,
        indicators=indicators,
    )


def transform_to_recommendations_response(
    recommendations: List[str],
    raw_score: Optional[str],
    response_date: date,
) -> RecommendationsResponse:
    """Transform recommendations data to RecommendationsResponse."""
    from datetime import datetime

    response_datetime = datetime.combine(response_date, datetime.min.time())

    return RecommendationsResponse(
        date=response_datetime,
        recommendations=recommendations,
        raw_score=raw_score,
    )


def transform_to_chart_data_response(
    chart_data: List[Dict[str, Any]],
) -> ChartDataResponse:
    """Transform chart data to ChartDataResponse."""
    data_points = [
        ChartDataPoint(
            date=point["date"],
            close=point["close"],
            volume=point["volume"],
            open_interest=point["open_interest"],
            rsi_14d=point["rsi_14d"],
            macd=point["macd"],
            stock_us=point["stock_us"],
            com_net_us=point["com_net_us"],
        )
        for point in chart_data
    ]

    return ChartDataResponse(data=data_points)


def transform_market_research_to_news(
    market_research: Dict[str, Any],
) -> NewsResponse:
    """Transform pl_fundamental_article dict to NewsResponse."""
    return NewsResponse(
        date=format_date_for_display(market_research["date"]),
        title=market_research.get("impact_synthesis"),
        content=market_research.get("summary"),
        keywords=market_research.get("keywords"),
        author=market_research.get("author"),
        source_count=market_research.get("source_count"),
        total_sources=market_research.get("total_sources"),
    )


def transform_weather_data_to_response(
    weather_data: Dict[str, Any],
) -> WeatherResponse:
    """Transform pl_weather_observation dict to WeatherResponse."""
    return WeatherResponse(
        date=format_date_for_display(weather_data["date"]),
        description=weather_data.get("text"),
        impact=weather_data.get("impact_synthesis"),
    )


def transform_to_weather_enriched_response(
    weather_data: Dict[str, Any],
    campaign: Optional[str],
    campaign_health: Optional[float],
    seasons: list[SeasonStatus],
    diagnostics: list[LocationDiagnostic],
    impact_score: Optional[int],
    harmattan: Optional[HarmattanStatus] = None,
    daily_diagnostics: Optional[list[LocationDiagnostic]] = None,
    stress_history: Optional[list] = None,
) -> WeatherEnrichedResponse:
    """Transform weather dict + seasonal data into enriched response."""
    from app.schemas.dashboard import LocationStressHistory

    return WeatherEnrichedResponse(
        date=format_date_for_display(weather_data.get("date", date.today())),
        description=weather_data.get("text", "") or "No weather description available",
        impact=weather_data.get("impact_synthesis", "")
        or "No market impact assessment available",
        campaign=campaign,
        campaign_health=campaign_health,
        seasons=seasons,
        diagnostics=diagnostics,
        daily_diagnostics=daily_diagnostics or [],
        stress_history=[LocationStressHistory(**h) for h in (stress_history or [])],
        impact_score=impact_score,
        harmattan=harmattan,
    )
