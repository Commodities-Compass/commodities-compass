"""
Dashboard data transformers.

Transforms database models and raw data into API response formats.
Separates data transformation logic from API endpoints.
"""

from typing import Optional, List, Dict, Any
from datetime import date

from app.models.technicals import Technicals
from app.models.test_range import TestRange
from app.models.market_research import MarketResearch
from app.models.weather_data import WeatherData
from app.schemas.dashboard import (
    PositionStatusResponse,
    CommodityIndicator,
    IndicatorRange,
    IndicatorsGridResponse,
    RecommendationsResponse,
    NewsResponse,
    WeatherResponse,
    ChartDataResponse,
    ChartDataPoint,
)
from app.utils.date_utils import format_date_for_display


def create_indicator_for_gauge(
    indicator_name: str,
    technicals: Technicals,
    test_ranges: List[TestRange],
) -> CommodityIndicator:
    """
    Create a gauge indicator from technicals data and test ranges.

    Args:
        indicator_name: Name of the indicator
        technicals: Technicals model instance
        test_ranges: List of test ranges for this indicator

    Returns:
        CommodityIndicator for gauge display

    Raises:
        ValueError: If no ranges are defined for the indicator
    """
    # Mapping of indicator names to technicals attributes
    indicator_mappings = {
        "macroeco": "macroeco",
        "rsi": "rsi_14d",
        "macd": "macd",
        "percent_k": "percent_k",
        "atr": "atr",
        "vol_oi": "vol_oi",
    }

    if indicator_name not in indicator_mappings:
        raise ValueError(f"Unknown indicator: {indicator_name}")

    # Get the value from technicals
    attr_name = indicator_mappings[indicator_name]
    if not hasattr(technicals, attr_name):
        raise ValueError(f"Technicals object missing attribute: {attr_name}")

    value = getattr(technicals, attr_name)
    if value is None:
        raise ValueError(f"No value available for indicator: {indicator_name}")

    if not test_ranges:
        raise ValueError(
            f"No ranges defined for indicator '{indicator_name}' in test_range table"
        )

    # Calculate min and max from ranges
    all_values = []
    for r in test_ranges:
        all_values.extend([r.range_low, r.range_high])
    min_value = min(all_values)
    max_value = max(all_values)

    # Convert ranges to IndicatorRange schema
    ranges = [
        IndicatorRange(
            range_low=r.range_low,
            range_high=r.range_high,
            area=r.area,
        )
        for r in test_ranges
    ]

    # Create display label
    display_names = {
        "macroeco": "MACROECO",
        "rsi": "RSI",
        "macd": "MACD",
        "percent_k": "%K",
        "atr": "ATR",
        "vol_oi": "VOL/OI",
    }

    return CommodityIndicator(
        value=float(value),
        min=min_value,
        max=max_value,
        label=display_names[indicator_name],
        ranges=ranges,
    )


def transform_to_position_status_response(
    position: Optional[str],
    ytd_performance: float,
    response_date,  # Accept datetime directly from service
) -> PositionStatusResponse:
    """
    Transform position data to PositionStatusResponse.

    Args:
        position: Position of the day ("OPEN", "HEDGE", "MONITOR")
        ytd_performance: YTD performance percentage
        response_date: Datetime for the response

    Returns:
        PositionStatusResponse
    """
    # Normalize and default to MONITOR if no valid position found
    if position:
        position = position.strip().upper()
    if not position or position not in ["OPEN", "HEDGE", "MONITOR"]:
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
    """
    Transform indicators data to IndicatorsGridResponse.

    Args:
        indicators_data: Dictionary of indicator data
        response_date: Date for the response

    Returns:
        IndicatorsGridResponse
    """
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

    # Convert date to datetime for schema compatibility
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
    """
    Transform recommendations data to RecommendationsResponse.

    Args:
        recommendations: List of parsed recommendations
        raw_score: Raw score text
        response_date: Date for the response

    Returns:
        RecommendationsResponse
    """
    # Convert date to datetime for schema compatibility
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
    """
    Transform chart data to ChartDataResponse.

    Args:
        chart_data: List of chart data dictionaries

    Returns:
        ChartDataResponse
    """
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


def transform_market_research_to_news(market_research: MarketResearch) -> NewsResponse:
    """
    Transform MarketResearch model to NewsResponse.

    Args:
        market_research: MarketResearch model instance

    Returns:
        NewsResponse
    """
    return NewsResponse(
        date=format_date_for_display(market_research.date),
        title=market_research.impact_synthesis or "Market Research Update",
        content=market_research.summary or "No summary available",
        author=market_research.author or "Market Research Team",
    )


def transform_weather_data_to_response(weather_data: WeatherData) -> WeatherResponse:
    """
    Transform WeatherData model to WeatherResponse.

    Args:
        weather_data: WeatherData model instance

    Returns:
        WeatherResponse
    """
    return WeatherResponse(
        date=format_date_for_display(weather_data.date),
        description=weather_data.text or "No weather description available",
        impact=weather_data.impact_synthesis or "No market impact assessment available",
    )
