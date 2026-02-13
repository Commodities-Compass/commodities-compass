"""
Dashboard API endpoints.

Streamlined API layer that focuses on parameter validation, error handling,
and response formatting. Business logic is delegated to service layer.
"""

from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.core.database import get_db
from app.core.auth import get_current_user
from app.schemas.dashboard import (
    PositionStatusResponse,
    IndicatorsGridResponse,
    RecommendationsResponse,
    NewsResponse,
    WeatherResponse,
    ChartDataResponse,
    AudioResponse,
)
from app.services.dashboard_service import (
    calculate_ytd_performance,
    get_position_from_technicals,
    get_indicators_with_ranges,
    get_latest_recommendations,
    get_chart_data,
    get_latest_market_research,
    get_latest_weather_data,
)
from app.services.dashboard_transformers import (
    transform_to_position_status_response,
    transform_to_indicators_grid_response,
    transform_to_recommendations_response,
    transform_to_chart_data_response,
    transform_market_research_to_news,
    transform_weather_data_to_response,
)
from app.utils.date_utils import (
    parse_date_string,
    get_business_date,
    log_business_date_conversion,
)
from app.services.audio_service import audio_service

router = APIRouter()
logger = logging.getLogger(__name__)


def _parse_and_validate_date(date_str: str) -> tuple[datetime.date, datetime.date]:
    """
    Parse and validate date string, converting to business date if needed.

    Args:
        date_str: Date string in YYYY-MM-DD format

    Returns:
        Tuple of (parsed_date, business_date)

    Raises:
        HTTPException: If date format is invalid
    """
    try:
        parsed_date = parse_date_string(date_str)
        business_date = get_business_date(parsed_date)
        log_business_date_conversion(parsed_date, business_date)
        return parsed_date, business_date
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/position-status", response_model=PositionStatusResponse)
async def get_position_status(
    target_date: Optional[str] = Query(
        default=None, description="Specific date for position data (YYYY-MM-DD format)"
    ),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PositionStatusResponse:
    """
    Get current position status and YTD performance.

    Returns the latest trading position (OPEN/HEDGE/MONITOR) and
    year-to-date performance percentage.

    Args:
        target_date: Optional specific date. If not provided, returns latest data.
        current_user: Authenticated user
        db: Database session

    Returns:
        Position status and YTD performance data

    Raises:
        HTTPException: If data not found or date format invalid
    """
    try:
        # Parse and validate date if provided
        business_date = None
        if target_date:
            _, business_date = _parse_and_validate_date(target_date)

        # Get position and YTD performance from service layer
        position = await get_position_from_technicals(db, business_date)
        ytd_performance = await calculate_ytd_performance(db, business_date)

        # Use business_date for response, or current date if not provided
        response_date = business_date or datetime.now().date()

        return transform_to_position_status_response(
            position=position,
            ytd_performance=ytd_performance,
            response_date=response_date,
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting position status: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/indicators-grid", response_model=IndicatorsGridResponse)
async def get_indicators_grid(
    target_date: Optional[str] = Query(
        default=None, description="Specific date for indicators (YYYY-MM-DD format)"
    ),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> IndicatorsGridResponse:
    """
    Get all indicators with their ranges for gauge display.

    Returns normalized indicator values with color ranges for
    the trading dashboard gauge components.

    Args:
        target_date: Optional specific date. If not provided, returns latest data.
        current_user: Authenticated user
        db: Database session

    Returns:
        All indicators with ranges and values

    Raises:
        HTTPException: If data not found or date format invalid
    """
    try:
        # Parse and validate date if provided
        business_date = None
        if target_date:
            _, business_date = _parse_and_validate_date(target_date)

        # Get indicators data from service layer
        indicators_data = await get_indicators_with_ranges(db, business_date)

        if not indicators_data:
            raise HTTPException(status_code=404, detail="No indicators data found")

        # Use business_date for response, or current date if not provided
        response_date = business_date or datetime.now().date()

        return transform_to_indicators_grid_response(
            indicators_data=indicators_data,
            response_date=response_date,
        )

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting indicators grid: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/recommendations", response_model=RecommendationsResponse)
async def get_recommendations(
    target_date: Optional[str] = Query(
        default=None,
        description="Specific date for recommendations (YYYY-MM-DD format)",
    ),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RecommendationsResponse:
    """
    Get recommendations parsed from technicals score data.

    Returns a list of trading recommendations extracted and parsed
    from the score column in the technicals table.

    Args:
        target_date: Optional specific date. If not provided, returns latest data.
        current_user: Authenticated user
        db: Database session

    Returns:
        Parsed recommendations list

    Raises:
        HTTPException: If data not found or date format invalid
    """
    try:
        # Parse and validate date if provided
        business_date = None
        if target_date:
            _, business_date = _parse_and_validate_date(target_date)

        # Get recommendations from service layer
        recommendations, raw_score, rec_date = await get_latest_recommendations(
            db, business_date
        )

        if not recommendations and not raw_score:
            raise HTTPException(status_code=404, detail="No recommendations data found")

        # Use actual date from data, or business_date, or current date
        response_date = rec_date or business_date or datetime.now().date()

        return transform_to_recommendations_response(
            recommendations=recommendations,
            raw_score=raw_score,
            response_date=response_date,
        )

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting recommendations: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/chart-data", response_model=ChartDataResponse)
async def get_chart_data_endpoint(
    days: int = Query(
        default=30, ge=1, le=365, description="Number of days of historical data"
    ),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChartDataResponse:
    """
    Get historical chart data for the specified number of days.

    Returns time series data for charting with configurable
    time range from 1 to 365 days.

    Args:
        days: Number of days of historical data (1-365)
        current_user: Authenticated user
        db: Database session

    Returns:
        Historical chart data points

    Raises:
        HTTPException: If data not found or parameters invalid
    """
    try:
        # Get chart data from service layer
        chart_data = await get_chart_data(db, days)

        if not chart_data:
            raise HTTPException(status_code=404, detail="No chart data found")

        return transform_to_chart_data_response(chart_data)

    except Exception as e:
        logger.error(f"Error getting chart data: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/news", response_model=NewsResponse)
async def get_news(
    target_date: Optional[str] = Query(
        default=None, description="Specific date for news (YYYY-MM-DD format)"
    ),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NewsResponse:
    """
    Get the latest news from market research data.

    Returns the most recent market research article with
    title and content for news display.

    Args:
        target_date: Optional specific date. If not provided, returns latest data.
        current_user: Authenticated user
        db: Database session

    Returns:
        Latest news article data

    Raises:
        HTTPException: If data not found or date format invalid
    """
    try:
        # Parse and validate date if provided
        business_date = None
        if target_date:
            _, business_date = _parse_and_validate_date(target_date)

        # Get market research from service layer
        market_research = await get_latest_market_research(db, business_date)

        if not market_research:
            raise HTTPException(status_code=404, detail="No news data found")

        return transform_market_research_to_news(market_research)

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting news: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/weather", response_model=WeatherResponse)
async def get_weather(
    target_date: Optional[str] = Query(
        default=None, description="Specific date for weather data (YYYY-MM-DD format)"
    ),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WeatherResponse:
    """
    Get the latest weather update from weather data.

    Returns the most recent weather information with
    conditions and market impact assessment.

    Args:
        target_date: Optional specific date. If not provided, returns latest data.
        current_user: Authenticated user
        db: Database session

    Returns:
        Latest weather update data

    Raises:
        HTTPException: If data not found or date format invalid
    """
    try:
        # Parse and validate date if provided
        business_date = None
        if target_date:
            _, business_date = _parse_and_validate_date(target_date)

        # Get weather data from service layer
        weather_data = await get_latest_weather_data(db, business_date)

        if not weather_data:
            raise HTTPException(status_code=404, detail="No weather data found")

        return transform_weather_data_to_response(weather_data)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting weather data: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/audio", response_model=AudioResponse)
async def get_audio(
    target_date: Optional[str] = Query(
        default=None, description="Specific date for audio file (YYYY-MM-DD format)"
    ),
    current_user: dict = Depends(get_current_user),
) -> AudioResponse:
    """
    Get publicly playable audio file link from Google Drive.

    Retrieves the audio file for the specified date in the format
    YYYYMMDD-CompassAudio.wav and returns a publicly accessible URL.

    Args:
        target_date: Optional specific date. If not provided, returns today's audio.
        current_user: Authenticated user

    Returns:
        Audio file URL and metadata

    Raises:
        HTTPException: If audio file not found or date format invalid
    """
    try:
        # Parse and validate date if provided
        parsed_date = None
        if target_date:
            parsed_date, _ = _parse_and_validate_date(target_date)

        # Get audio metadata from service
        audio_metadata = await audio_service.get_audio_metadata(parsed_date)

        if not audio_metadata:
            # Provide helpful error message
            date_str = (
                parsed_date.strftime("%Y-%m-%d")
                if parsed_date
                else datetime.now().strftime("%Y-%m-%d")
            )
            filename_base = f"{(parsed_date or datetime.now().date()).strftime('%Y%m%d')}-CompassAudio"
            raise HTTPException(
                status_code=404,
                detail=f"Audio file not found for date {date_str}. Looking for: {filename_base}.wav or {filename_base}.m4a",
            )

        # Return backend streaming URL instead of Google Drive URL
        # Use relative path that works with frontend's API_BASE_URL
        stream_url = "/audio/stream"
        if target_date:
            stream_url += f"?target_date={target_date}"

        return AudioResponse(
            url=stream_url,  # Backend streaming URL
            title=audio_metadata["title"],
            date=audio_metadata["date"],
            filename=audio_metadata["filename"],
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting audio file: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# Legacy endpoints for backward compatibility
@router.get("/latest-indicator")
async def get_latest_indicator(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get latest indicator data (legacy endpoint)."""
    # TODO: Implement or deprecate
    return {"message": "Legacy endpoint - use /indicators-grid instead"}


@router.get("/dashboard-data")
async def get_dashboard_data(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get dashboard data (legacy endpoint)."""
    # TODO: Implement or deprecate
    return {"message": "Legacy endpoint - use specific endpoints instead"}


@router.get("/summary")
async def get_dashboard_summary(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get quick summary for dashboard (legacy endpoint)."""
    # TODO: Implement or deprecate
    return {
        "lastUpdate": datetime.utcnow().isoformat(),
        "activePositions": 1,
        "totalCommodities": 1,
        "alerts": [],
    }
