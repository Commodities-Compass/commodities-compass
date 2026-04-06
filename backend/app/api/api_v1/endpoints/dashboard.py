"""
Dashboard API endpoints.

Streamlined API layer that focuses on parameter validation, error handling,
and response formatting. Business logic is delegated to service layer.
"""

from datetime import date, datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.core.rate_limit import limiter

from app.core.database import get_db
from app.core.auth import get_current_user
from app.schemas.dashboard import (
    PositionStatusResponse,
    IndicatorsGridResponse,
    RecommendationsResponse,
    NewsResponse,
    WeatherEnrichedResponse,
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
    transform_to_weather_enriched_response,
)
from app.services.weather_service import (
    get_current_campaign,
    get_harmattan_status,
    get_seasonal_scores,
    compute_campaign_health,
    build_season_statuses,
    build_location_diagnostics,
    parse_impact_score,
)
from app.models.reference import RefExchange, RefTradingCalendar
from app.utils.date_utils import parse_date_string
from app.utils.trading_calendar import TradingCalendarError, get_latest_trading_day
from app.services.audio_service import get_audio_service

router = APIRouter()
logger = logging.getLogger(__name__)


async def _parse_and_validate_date(date_str: str, db: AsyncSession) -> date:
    """Parse date string and resolve to the latest trading day.

    Returns the most recent trading day on or before the parsed date,
    using ref_trading_calendar as the single source of truth.

    Raises:
        HTTPException: If date format is invalid or calendar lookup fails.
    """
    try:
        parsed_date = parse_date_string(date_str)
        trading_day = await get_latest_trading_day(db, parsed_date)
        if trading_day != parsed_date:
            logger.info("Date %s resolved to trading day %s", parsed_date, trading_day)
        return trading_day
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except TradingCalendarError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/position-status", response_model=PositionStatusResponse)
@limiter.limit("60/minute")
async def get_position_status(
    request: Request,
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
            business_date = await _parse_and_validate_date(target_date, db)

        # Get position and YTD performance from service layer
        position = await get_position_from_technicals(db, business_date)
        ytd_performance = await calculate_ytd_performance(db, business_date)

        # Use business_date for response, or current date if not provided
        response_date = business_date or datetime.now(timezone.utc).date()

        return transform_to_position_status_response(
            position=position,
            ytd_performance=ytd_performance,
            response_date=response_date,
        )

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting position status: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/indicators-grid", response_model=IndicatorsGridResponse)
@limiter.limit("60/minute")
async def get_indicators_grid(
    request: Request,
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
            business_date = await _parse_and_validate_date(target_date, db)

        # Get indicators data from service layer
        indicators_data = await get_indicators_with_ranges(db, business_date)

        if not indicators_data:
            raise HTTPException(status_code=404, detail="No indicators data found")

        # Use business_date for response, or current date if not provided
        response_date = business_date or datetime.now(timezone.utc).date()

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
@limiter.limit("60/minute")
async def get_recommendations(
    request: Request,
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
            business_date = await _parse_and_validate_date(target_date, db)

        # Get recommendations from service layer
        recommendations, raw_score, rec_date = await get_latest_recommendations(
            db, business_date
        )

        if not recommendations and not raw_score:
            raise HTTPException(status_code=404, detail="No recommendations data found")

        # Use actual date from data, or business_date, or current date
        response_date = rec_date or business_date or datetime.now(timezone.utc).date()

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
@limiter.limit("60/minute")
async def get_chart_data_endpoint(
    request: Request,
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

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting chart data: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/news", response_model=NewsResponse)
@limiter.limit("60/minute")
async def get_news(
    request: Request,
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
            business_date = await _parse_and_validate_date(target_date, db)

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


@router.get("/weather", response_model=WeatherEnrichedResponse)
@limiter.limit("60/minute")
async def get_weather(
    request: Request,
    target_date: Optional[str] = Query(
        default=None, description="Specific date for weather data (YYYY-MM-DD format)"
    ),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WeatherEnrichedResponse:
    """Get weather update enriched with seasonal campaign data."""
    try:
        business_date = None
        if target_date:
            business_date = await _parse_and_validate_date(target_date, db)

        weather_data = await get_latest_weather_data(db, business_date)
        if not weather_data:
            raise HTTPException(status_code=404, detail="No weather data found")

        # Enrich with seasonal scores + harmattan (non-blocking: graceful fallback)
        reference = business_date or date.today()
        campaign = get_current_campaign(reference)
        campaign_health = None
        seasons: list = []
        diagnostics: list = []
        harmattan = None

        try:
            scores = await get_seasonal_scores(db, campaign)
            if scores:
                campaign_health = compute_campaign_health(scores)
                seasons = build_season_statuses(scores, reference)
                diagnostics = build_location_diagnostics(scores)
            else:
                seasons = build_season_statuses([], reference)
            harmattan = await get_harmattan_status(db, campaign, reference)
        except Exception as e:
            logger.warning(f"Seasonal enrichment failed (non-blocking): {e}")
            campaign = None

        raw_impact = (
            weather_data.get("impact_synthesis", "")
            if isinstance(weather_data, dict)
            else getattr(weather_data, "impact_synthesis", "") or ""
        )
        impact_score = parse_impact_score(raw_impact)

        return transform_to_weather_enriched_response(
            weather_data=weather_data,
            campaign=campaign,
            campaign_health=campaign_health,
            seasons=seasons,
            diagnostics=diagnostics,
            impact_score=impact_score,
            harmattan=harmattan,
        )

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting weather data: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/audio", response_model=AudioResponse)
@limiter.limit("10/minute")
async def get_audio(
    request: Request,
    target_date: Optional[str] = Query(
        default=None, description="Specific date for audio file (YYYY-MM-DD format)"
    ),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
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
        # Parse and resolve to trading day
        trading_day = None
        if target_date:
            trading_day = await _parse_and_validate_date(target_date, db)

        # Get audio metadata from service
        audio_metadata = await get_audio_service().get_audio_metadata(trading_day)

        if not audio_metadata:
            # Provide helpful error message
            date_str = (
                trading_day.strftime("%Y-%m-%d")
                if trading_day
                else datetime.now(timezone.utc).strftime("%Y-%m-%d")
            )
            filename_base = f"{(trading_day or datetime.now(timezone.utc).date()).strftime('%Y%m%d')}-CompassAudio"
            raise HTTPException(
                status_code=404,
                detail=f"Audio file not found for date {date_str}. Looking for: {filename_base}.wav or {filename_base}.m4a",
            )

        # Return backend streaming URL with resolved trading day
        stream_url = "/audio/stream"
        if trading_day:
            stream_url += f"?target_date={trading_day.isoformat()}"

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


@router.get("/non-trading-days")
@limiter.limit("10/minute")
async def get_non_trading_days(
    request: Request,
    year: int = Query(description="Year to fetch non-trading days for"),
    month: Optional[int] = Query(default=None, ge=1, le=12, description="Month (1-12)"),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return non-trading weekday dates (exchange holidays) for the calendar.

    Weekends are already handled client-side. This endpoint only returns
    weekdays that are non-trading (holidays, closures).
    """
    try:
        exchange_result = await db.execute(
            select(RefExchange.id).where(RefExchange.code == "IFEU")
        )
        exchange_id = exchange_result.scalar_one_or_none()
        if exchange_id is None:
            return {"dates": [], "latest_trading_day": None}

        query = select(RefTradingCalendar.date).where(
            RefTradingCalendar.exchange_id == exchange_id,
            RefTradingCalendar.is_trading_day.is_(False),
        )
        if month is not None:
            start = date(year, month, 1)
            end = date(year, month + 1, 1) if month < 12 else date(year + 1, 1, 1)
            query = query.where(
                RefTradingCalendar.date >= start,
                RefTradingCalendar.date < end,
            )
        else:
            query = query.where(
                RefTradingCalendar.date >= date(year, 1, 1),
                RefTradingCalendar.date < date(year + 1, 1, 1),
            )

        result = await db.execute(query.order_by(RefTradingCalendar.date))
        non_trading_dates = [row[0].isoformat() for row in result.all()]

        latest = await get_latest_trading_day(db)

        return {
            "dates": non_trading_dates,
            "latest_trading_day": latest.isoformat(),
        }
    except TradingCalendarError:
        return {"dates": [], "latest_trading_day": None}
    except Exception as e:
        logger.error("Error fetching non-trading days: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# Legacy endpoints for backward compatibility
@router.get("/latest-indicator", deprecated=True)
async def get_latest_indicator(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get latest indicator data (legacy endpoint). Use /indicators-grid instead."""
    return {"message": "Legacy endpoint - use /indicators-grid instead"}


@router.get("/dashboard-data", deprecated=True)
async def get_dashboard_data(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get dashboard data (legacy endpoint). Use specific endpoints instead."""
    return {"message": "Legacy endpoint - use specific endpoints instead"}


@router.get("/summary", deprecated=True)
async def get_dashboard_summary(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get quick summary for dashboard (legacy endpoint)."""
    return {
        "lastUpdate": datetime.now(timezone.utc).isoformat(),
        "activePositions": 1,
        "totalCommodities": 1,
        "alerts": [],
    }
