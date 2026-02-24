"""
Dashboard business logic service.

Contains pure business logic functions for dashboard operations,
independent of FastAPI dependencies for better testability and reusability.
"""

from datetime import date
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func, and_
import logging
import re

from app.models.technicals import Technicals
from app.models.indicator import Indicator
from app.models.test_range import TestRange
from app.models.market_research import MarketResearch
from app.models.weather_data import WeatherData
from app.utils.date_utils import get_year_start_date, get_business_date

logger = logging.getLogger(__name__)


async def calculate_ytd_performance(
    db: AsyncSession, reference_date: Optional[date] = None
) -> float:
    """
    Calculate Year-to-Date performance as the mean average of CONCLUSION values.

    Args:
        db: Database session
        reference_date: The date to calculate YTD up to (defaults to current date)

    Returns:
        YTD performance as a percentage
    """
    if reference_date is None:
        reference_date = date.today()

    # Get the year from the reference date
    year = reference_date.year
    start_of_year = get_year_start_date(reference_date)

    # Query for all CONCLUSION values in the current year up to the reference date
    query = (
        select(Technicals.conclusion)
        .where(
            and_(
                func.date(Technicals.timestamp) >= start_of_year,
                func.date(Technicals.timestamp) <= reference_date,
                Technicals.conclusion.isnot(None),
            )
        )
        .order_by(Technicals.timestamp)
    )

    result = await db.execute(query)
    conclusions = result.scalars().all()

    if not conclusions:
        # No data available, return 0.0
        logger.warning(f"No CONCLUSION data found for YTD calculation in year {year}")
        return 0.0

    # Calculate the mean average
    avg_conclusion = sum(conclusions) / len(conclusions)

    # Convert to percentage (multiply by 100 to match original implementation)
    ytd_performance = float(avg_conclusion) * 100

    logger.info(
        f"YTD Performance calculated: {ytd_performance:.2f}% "
        f"(based on {len(conclusions)} data points)"
    )

    return ytd_performance


async def get_latest_technicals(
    db: AsyncSession, target_date: Optional[date] = None
) -> Optional[Technicals]:
    """
    Get the latest technicals record for a given date.

    Args:
        db: Database session
        target_date: Target date (defaults to latest available)

    Returns:
        Latest technicals record or None if not found
    """
    query = select(Technicals).order_by(desc(Technicals.timestamp))

    if target_date:
        business_date = get_business_date(target_date)
        query = query.where(func.date(Technicals.timestamp) == business_date)

    result = await db.execute(query)
    return result.scalars().first()


async def get_indicators_with_ranges(
    db: AsyncSession, target_date: Optional[date] = None
) -> Dict[str, Dict[str, Any]]:
    """
    Get all indicators with their ranges for a given date.

    Args:
        db: Database session
        target_date: Target date (defaults to latest available)

    Returns:
        Dictionary of indicators with their data and ranges
    """
    # Get indicator data (not technicals) - matches original implementation
    query = select(Indicator).order_by(desc(Indicator.date))

    if target_date:
        business_date = get_business_date(target_date)
        query = query.where(func.date(Indicator.date) == business_date)

    result = await db.execute(query)
    indicator = result.scalars().first()

    if not indicator:
        return {}

    # Get all test ranges
    ranges_query = select(TestRange)
    ranges_result = await db.execute(ranges_query)
    all_ranges = ranges_result.scalars().all()

    # Group ranges by indicator
    ranges_by_indicator = {}
    for range_obj in all_ranges:
        if range_obj.indicator not in ranges_by_indicator:
            ranges_by_indicator[range_obj.indicator] = []
        ranges_by_indicator[range_obj.indicator].append(range_obj)

    # Build indicators data using original mapping from backup
    indicators = {}

    # Map of indicator names to their database fields and display labels (from original)
    indicator_configs = [
        ("macroeco", indicator.macroeco_score, "MACROECO", "MACROECO"),
        ("rsi", indicator.rsi_norm, "RSI", "RSI"),
        ("macd", indicator.macd_norm, "MACD", "MACD"),
        ("percentK", indicator.stoch_k_norm, "%K", "%K"),
        ("atr", indicator.atr_norm, "ATR", "ATR"),
        ("volOi", indicator.vol_oi_norm, "VOL/OI", "VOL_OI"),
    ]

    for key, value, label, range_indicator_name in indicator_configs:
        if value is not None and range_indicator_name in ranges_by_indicator:
            ranges = ranges_by_indicator[range_indicator_name]

            # Calculate min and max from ranges
            all_values = []
            for r in ranges:
                all_values.extend([r.range_low, r.range_high])

            indicators[key] = {
                "value": float(value),
                "min": min(all_values),
                "max": max(all_values),
                "label": label,
                "ranges": [
                    {
                        "range_low": r.range_low,
                        "range_high": r.range_high,
                        "area": r.area,
                    }
                    for r in ranges
                ],
            }

    return indicators


async def parse_recommendations_text(text: str) -> List[str]:
    """
    Parse recommendations from raw text.

    Args:
        text: Raw text containing recommendations

    Returns:
        List of parsed recommendation strings
    """
    if not text:
        return []

    # Strip HTML tags (e.g. <br>, <br/>, <p>, etc.) replacing them with newlines
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</?[a-z][a-z0-9]*[^>]*>", "\n", text, flags=re.IGNORECASE)

    # Split by newlines and clean up
    lines = text.split("\n")
    recommendations = []

    for line in lines:
        line = line.strip()
        if line:
            # Remove bullet points and clean up
            line = re.sub(r"^[-•*]\s*", "", line)
            if line:
                recommendations.append(line)

    return recommendations


async def get_latest_recommendations(
    db: AsyncSession, target_date: Optional[date] = None
) -> tuple[List[str], Optional[str], Optional[date]]:
    """
    Get the latest recommendations from technicals data.

    Args:
        db: Database session
        target_date: Target date (defaults to latest available)

    Returns:
        Tuple of (recommendations_list, raw_score, date)
    """
    technicals = await get_latest_technicals(db, target_date)
    if not technicals or not technicals.score:
        return [], None, None

    recommendations = await parse_recommendations_text(technicals.score)
    return recommendations, technicals.score, technicals.timestamp


async def get_chart_data(db: AsyncSession, days: int = 30) -> List[Dict[str, Any]]:
    """
    Get historical chart data for the specified number of days.

    Args:
        db: Database session
        days: Number of days of historical data

    Returns:
        List of chart data points
    """
    query = select(Technicals).order_by(desc(Technicals.timestamp)).limit(days)

    result = await db.execute(query)
    technicals_data = result.scalars().all()

    # Reverse to get chronological order
    technicals_data = list(reversed(technicals_data))

    chart_data = []
    for tech in technicals_data:
        chart_data.append(
            {
                "date": tech.timestamp.strftime("%Y-%m-%d"),
                "close": tech.close,
                "volume": tech.volume,
                "open_interest": tech.open_interest,
                "rsi_14d": tech.rsi_14d,
                "macd": tech.macd,
                "stock_us": tech.stock_us,
                "com_net_us": tech.com_net_us,
            }
        )

    return chart_data


async def get_latest_market_research(
    db: AsyncSession, target_date: Optional[date] = None
) -> Optional[MarketResearch]:
    """
    Get the latest market research record.

    Args:
        db: Database session
        target_date: Target date (defaults to latest available)

    Returns:
        Latest market research record or None if not found
    """
    query = select(MarketResearch).order_by(desc(MarketResearch.date))

    if target_date:
        business_date = get_business_date(target_date)
        query = query.where(func.date(MarketResearch.date) == business_date)

    result = await db.execute(query)
    return result.scalars().first()


async def get_latest_weather_data(
    db: AsyncSession, target_date: Optional[date] = None
) -> Optional[WeatherData]:
    """
    Get the latest weather data record.

    Args:
        db: Database session
        target_date: Target date (defaults to latest available)

    Returns:
        Latest weather data record or None if not found
    """
    query = select(WeatherData).order_by(desc(WeatherData.date))

    if target_date:
        business_date = get_business_date(target_date)
        query = query.where(func.date(WeatherData.date) == business_date)

    result = await db.execute(query)
    return result.scalars().first()


async def get_position_from_technicals(
    db: AsyncSession, target_date: Optional[date] = None
) -> Optional[str]:
    """
    Get the position of the day from technicals decision data.

    Args:
        db: Database session
        target_date: Target date (defaults to latest available)

    Returns:
        Position string from decision column ("OPEN", "HEDGE", "MONITOR") or None
    """
    # Get the latest technicals data
    query = select(Technicals).order_by(desc(Technicals.timestamp))

    if target_date:
        business_date = get_business_date(target_date)
        query = query.where(func.date(Technicals.timestamp) == business_date)

    result = await db.execute(query)
    technicals = result.scalars().first()

    if not technicals:
        return None

    # Return decision directly as position
    return technicals.decision
