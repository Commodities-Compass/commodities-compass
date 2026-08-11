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
from app.core.i18n import resolve_language
from app.core import entitlements as ent
from app.core.audio_signing import sign_stream_token
from app.core.config import settings
from app.core.tenancy import require_any_entitlement
from app.schemas.auth import NonTradingDaysResponse
from app.schemas.dashboard import (
    PositionStatusResponse,
    IndicatorsGridResponse,
    RecommendationsResponse,
    NewsResponse,
    NewsSentimentResponse,
    ThemeSentiment,
    WeatherEnrichedResponse,
    ChartDataResponse,
    AudioResponse,
    FarmgatePriceResponse,
    MacroPanelResponse,
    PositioningResponse,
    EnsembleDiagnosticsResponse,
    SpecialistVotesResponse,
    SpecialistVote,
)
from app.services.dashboard_service import (
    calculate_ytd_performance,
    get_position_from_technicals,
    get_indicators_with_ranges,
    get_latest_recommendations,
    get_chart_data,
    get_latest_market_research,
    get_latest_weather_data,
    get_theme_sentiments,
)
from app.utils.contract_resolver import (
    get_active_contract_id,
    get_active_algorithm_version_id,
    get_algorithm_version_for_date,
    get_contract_code_by_id,
    resolve_contract_for_date,
)
from app.services.dashboard_transformers import (
    transform_to_position_status_response,
    transform_to_indicators_grid_response,
    transform_to_recommendations_response,
    transform_to_chart_data_response,
    transform_market_research_to_news,
    transform_to_weather_enriched_response,
)
from app.services.macro_panel_service import get_macro_panel
from app.services.farmgate_service import get_farmgate_prices
from app.services.positioning_service import get_positioning
from app.services.ensemble_diagnostics_service import (
    get_ensemble_diagnostics,
    get_specialist_votes,
)
from app.utils.contract_resolver import ENSEMBLE_VERSION_NAME
from app.services.weather_service import (
    get_current_campaign,
    get_harmattan_status,
    get_seasonal_scores,
    compute_campaign_health,
    build_season_statuses,
    build_location_diagnostics,
    build_daily_diagnostics,
    parse_impact_score,
)
from app.models.pipeline import PlContractDataDaily, PlSessionRelease
from app.models.reference import RefExchange, RefTradingCalendar
from app.utils.date_utils import parse_date_string
from app.utils.trading_calendar import TradingCalendarError, get_latest_trading_day
from app.services.audio_service import get_audio_service

router = APIRouter()
logger = logging.getLogger(__name__)


async def _resolve_contract_for_request(
    db: AsyncSession, business_date: Optional[date]
):
    """Front-month contract for the requested date — NOT just the active one.

    For a specific historical date, resolve the contract that was front-month
    THAT day (``resolve_contract_for_date``). This is essential across a
    contract roll: the post-roll active contract (e.g. CAU26) has no rows for
    pre-roll dates, so keying the date-aware algo/position lookup to the active
    contract makes every pre-roll session fall back to legacy + a null position
    (rendered as MONITOR). For a 'latest' (no-date) request, use the active
    contract. Falls back to active if no contract has data for the date.
    """
    if business_date is not None:
        cid = await resolve_contract_for_date(db, business_date)
        if cid is not None:
            return cid
    return await get_active_contract_id(db)


async def _resolve_algo_for_date(
    db: AsyncSession,
    business_date: Optional[date],
    contract_id,
) -> tuple:
    """Resolve (algorithm_version_id, algorithm_name) for a date.

    Centralizes the date-aware lookup so all dashboard endpoints expose a
    consistent ``source_algorithm`` field. When no business_date is provided
    (latest data request), falls back to today — the resolver caches per
    (date, contract) so this is cheap on a hot path.
    """
    resolution_date = business_date or datetime.now(timezone.utc).date()
    try:
        algo_id, algo_name = await get_algorithm_version_for_date(
            db, resolution_date, contract_id=contract_id
        )
        return algo_id, algo_name
    except ValueError:
        # No version registered at all — fall back to the legacy "active" id.
        algo_id = await get_active_algorithm_version_id(db)
        return algo_id, "legacy"


async def _parse_and_validate_date(date_str: str, db: AsyncSession) -> date:
    """Parse display date and resolve to the session date for DB queries.

    The frontend sends a display_date (next trading day after the session).
    This function looks up the corresponding session date in pl_contract_data_daily.
    Falls back to trading calendar resolution if no display_date match exists.

    Raises:
        HTTPException: If date format is invalid or calendar lookup fails.
    """
    try:
        parsed_date = parse_date_string(date_str)

        # Try display_date lookup first (new behavior)
        result = await db.execute(
            select(PlContractDataDaily.date)
            .where(PlContractDataDaily.display_date == parsed_date)
            .order_by(PlContractDataDaily.date.desc())
            .limit(1)
        )
        session_date = result.scalar_one_or_none()
        if session_date is not None:
            if session_date != parsed_date:
                logger.info(
                    "Display date %s resolved to session date %s",
                    parsed_date,
                    session_date,
                )
            return session_date

        # Fallback: trading calendar resolution (pre-migration data, direct date query)
        trading_day = await get_latest_trading_day(db, parsed_date)
        if trading_day != parsed_date:
            logger.info("Date %s resolved to trading day %s", parsed_date, trading_day)
        return trading_day
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except TradingCalendarError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get(
    "/position-status",
    response_model=PositionStatusResponse,
    dependencies=[
        Depends(require_any_entitlement(ent.SECTION_SIGNAL, ent.CHROME_TICKER))
    ],
)
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

        # Resolve contract, then date-aware algo version (ensemble vs legacy)
        contract_id = await _resolve_contract_for_request(db, business_date)
        algo_id, algo_name = await _resolve_algo_for_date(
            db, business_date, contract_id
        )

        # Get position and YTD performance from service layer
        position = await get_position_from_technicals(
            db, business_date, contract_id=contract_id, algo_id=algo_id
        )
        ytd_performance = await calculate_ytd_performance(db, business_date)

        # Use business_date for response, or current date if not provided
        response_date = business_date or datetime.now(timezone.utc).date()

        return transform_to_position_status_response(
            position=position,
            ytd_performance=ytd_performance,
            response_date=response_date,
            source_algorithm=algo_name,
        )

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting position status: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/indicators-grid",
    response_model=IndicatorsGridResponse,
    dependencies=[
        Depends(require_any_entitlement(ent.SECTION_MARKET, ent.CHROME_TICKER))
    ],
)
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

        # Resolve contract + date-aware algo version so indicators come from the
        # right version when ensemble has data for that date.
        contract_id = await _resolve_contract_for_request(db, business_date)
        algo_id, algo_name = await _resolve_algo_for_date(
            db, business_date, contract_id
        )

        indicators_data = await get_indicators_with_ranges(
            db, business_date, contract_id=contract_id, algo_id=algo_id
        )

        if not indicators_data:
            raise HTTPException(status_code=404, detail="No indicators data found")

        # Use business_date for response, or current date if not provided
        response_date = business_date or datetime.now(timezone.utc).date()

        # Display-only provenance for the Section II socle. Never fatal: a
        # missing code degrades the caption, not the indicators.
        contract_code = await get_contract_code_by_id(db, contract_id)
        if contract_code is None:
            logger.warning(
                "No ref_contract row for resolved contract_id %s — "
                "indicators-grid served without contract_code",
                contract_id,
            )

        return transform_to_indicators_grid_response(
            indicators_data=indicators_data,
            response_date=response_date,
            source_algorithm=algo_name,
            contract_code=contract_code,
        )

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting indicators grid: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/recommendations",
    response_model=RecommendationsResponse,
    dependencies=[
        Depends(require_any_entitlement(ent.SECTION_SIGNAL, ent.SECTION_MARKET))
    ],
)
@limiter.limit("60/minute")
async def get_recommendations(
    request: Request,
    target_date: Optional[str] = Query(
        default=None,
        description="Specific date for recommendations (YYYY-MM-DD format)",
    ),
    language: Optional[str] = Query(
        default=None,
        description="Content language ('fr' | 'en'). Falls back to Accept-Language, else 'fr'.",
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

        # Resolve contract + date-aware algo version. Recommendations narrative
        # currently always comes from the legacy LLM job — even when ensemble
        # produced the decision, the conclusion text is still legacy-generated.
        # source_algorithm reflects which version's pl_indicator_daily row was
        # picked so the frontend can disclose the dissonance.
        contract_id = await _resolve_contract_for_request(db, business_date)
        algo_id, algo_name = await _resolve_algo_for_date(
            db, business_date, contract_id
        )

        lang = resolve_language(language, request.headers.get("accept-language"))
        recommendations, raw_score, rec_date = await get_latest_recommendations(
            db, business_date, contract_id=contract_id, algo_id=algo_id, language=lang
        )

        if not recommendations and not raw_score:
            raise HTTPException(status_code=404, detail="No recommendations data found")

        # Use actual date from data, or business_date, or current date
        response_date = rec_date or business_date or datetime.now(timezone.utc).date()

        return transform_to_recommendations_response(
            recommendations=recommendations,
            raw_score=raw_score,
            response_date=response_date,
            source_algorithm=algo_name,
        )

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting recommendations: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/chart-data",
    response_model=ChartDataResponse,
    dependencies=[
        Depends(require_any_entitlement(ent.SECTION_CHART, ent.CHROME_TICKER))
    ],
)
@limiter.limit("60/minute")
async def get_chart_data_endpoint(
    request: Request,
    days: int = Query(
        default=30, ge=1, le=365, description="Number of days of historical data"
    ),
    target_date: Optional[str] = Query(
        default=None,
        description="Cap chart data at this display date (YYYY-MM-DD format)",
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
        end_date = None
        if target_date:
            end_date = await _parse_and_validate_date(target_date, db)

        chart_data = await get_chart_data(db, days, end_date=end_date)

        if not chart_data:
            raise HTTPException(status_code=404, detail="No chart data found")

        return transform_to_chart_data_response(chart_data)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting chart data: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/news",
    response_model=NewsResponse,
    dependencies=[Depends(require_any_entitlement(ent.SECTION_NEWS))],
)
@limiter.limit("60/minute")
async def get_news(
    request: Request,
    target_date: Optional[str] = Query(
        default=None, description="Specific date for news (YYYY-MM-DD format)"
    ),
    language: Optional[str] = Query(
        default=None,
        description="Content language ('fr' | 'en'). Falls back to Accept-Language, else 'fr'.",
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
        lang = resolve_language(language, request.headers.get("accept-language"))
        market_research = await get_latest_market_research(
            db, business_date, language=lang
        )

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


@router.get(
    "/news/sentiment",
    response_model=NewsSentimentResponse,
    dependencies=[Depends(require_any_entitlement(ent.SECTION_NEWS))],
)
@limiter.limit("60/minute")
async def get_news_sentiment(
    request: Request,
    target_date: Optional[str] = Query(
        default=None, description="Specific date (YYYY-MM-DD format)"
    ),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NewsSentimentResponse:
    """Get per-theme sentiment scores for the press review.

    Returns sentiment scores for production, chocolat, transformation,
    and economie themes, plus z-delta trend when available.
    """
    try:
        business_date = None
        if target_date:
            business_date = await _parse_and_validate_date(target_date, db)

        data = await get_theme_sentiments(db, business_date)

        if not data:
            raise HTTPException(
                status_code=404, detail="No sentiment data found for this date"
            )

        from app.utils.date_utils import format_date_for_display

        return NewsSentimentResponse(
            date=format_date_for_display(data["date"]) if data["date"] else "",
            themes=[ThemeSentiment(**t) for t in data["themes"]],
            accumulation=data.get("accumulation"),
        )

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting news sentiment: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/weather",
    response_model=WeatherEnrichedResponse,
    dependencies=[
        Depends(
            require_any_entitlement(ent.SECTION_WEATHER, ent.SECTION_WEATHER_SUMMARY)
        )
    ],
)
@limiter.limit("60/minute")
async def get_weather(
    request: Request,
    target_date: Optional[str] = Query(
        default=None, description="Specific date for weather data (YYYY-MM-DD format)"
    ),
    language: Optional[str] = Query(
        default=None,
        description="Content language ('fr' | 'en'). Falls back to Accept-Language, else 'fr'.",
    ),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WeatherEnrichedResponse:
    """Get weather update enriched with seasonal campaign data."""
    try:
        business_date = None
        if target_date:
            business_date = await _parse_and_validate_date(target_date, db)

        lang = resolve_language(language, request.headers.get("accept-language"))
        weather_data = await get_latest_weather_data(db, business_date, language=lang)
        if not weather_data:
            raise HTTPException(status_code=404, detail="No weather data found")

        # Enrich with seasonal scores + harmattan (non-blocking: graceful fallback)
        reference = business_date or date.today()
        campaign = get_current_campaign(reference)
        campaign_health = None
        seasons: list = []
        diagnostics: list = []
        daily_diag: list = []
        stress_hist: list = []
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

        # Daily diagnostics from LLM
        raw_diag = (
            weather_data.get("diagnostics") if isinstance(weather_data, dict) else None
        )
        daily_diag = build_daily_diagnostics(raw_diag)
        if not daily_diag and diagnostics:
            logger.warning(
                "No daily diagnostics in pl_weather_observation — "
                "falling back to seasonal diagnostics"
            )
            daily_diag = diagnostics

        # Stress history (7-day lookback)
        from app.services.dashboard_service import get_stress_history

        stress_hist = await get_stress_history(
            db, days=7, target_date=business_date, language=lang
        )

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
            daily_diagnostics=daily_diag,
            stress_history=stress_hist,
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


@router.get(
    "/audio",
    response_model=AudioResponse,
    dependencies=[Depends(require_any_entitlement(ent.SECTION_PODCAST))],
)
@limiter.limit("10/minute")
async def get_audio(
    request: Request,
    target_date: Optional[str] = Query(
        default=None, description="Specific date for audio file (YYYY-MM-DD format)"
    ),
    version: Optional[str] = Query(
        default=None,
        description=(
            "Brief track: 'legacy' | 'ensemble'. Defaults to settings.BRIEF_DEFAULT_VERSION. "
            "Allows the frontend to preview the ensemble brief without flipping the global default."
        ),
    ),
    language: Optional[str] = Query(
        default=None,
        description=(
            "Audio edition ('fr' | 'en'). Falls back to Accept-Language, else "
            "'fr'. The EN edition is ensemble-only and never serves an FR audio."
        ),
    ),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AudioResponse:
    """
    Get publicly playable audio file link from Google Drive.

    Retrieves the audio file for the specified date and returns a backend
    streaming URL. The `version` query param selects the brief track
    (legacy/ensemble) for the dual-track rollout; `language` selects the
    edition (fr/en) for the Ghana rollout.

    Args:
        target_date: Optional specific date. If not provided, returns today's audio.
        version: Optional brief track override.
        language: Optional edition override; else Accept-Language, else 'fr'.
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

        lang = resolve_language(language, request.headers.get("accept-language"))

        # Get audio metadata from service (version + language aware)
        audio_metadata = await get_audio_service().get_audio_metadata(
            trading_day, version=version, language=str(lang)
        )

        if not audio_metadata:
            # Provide helpful error message
            date_str = (
                trading_day.strftime("%Y-%m-%d")
                if trading_day
                else datetime.now(timezone.utc).strftime("%Y-%m-%d")
            )
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Audio file not found for date {date_str} "
                    f"(version={version or 'default'}, language={lang})."
                ),
            )

        # Return backend streaming URL with resolved trading day + version +
        # language so the unauthenticated stream endpoint resolves the same file.
        stream_url = "/audio/stream"
        params = []
        if trading_day:
            params.append(f"target_date={trading_day.isoformat()}")
        if version:
            params.append(f"version={version}")
        if str(lang) != "fr":
            params.append(f"language={lang}")
        if params:
            stream_url += "?" + "&".join(params)

        # Hard boundary: mint a signed capability token bound to the resolved
        # params so the unauthenticated /audio/stream only serves callers who
        # passed the podcast gate here. Dark mode (flag off) leaves the stream open.
        if settings.ENTITLEMENTS_ENFORCED:
            token = sign_stream_token(
                trading_day.isoformat() if trading_day else "",
                version or "",
                str(lang) if str(lang) != "fr" else "",
            )
            stream_url += ("&" if "?" in stream_url else "?") + f"token={token}"

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


@router.get("/non-trading-days", response_model=NonTradingDaysResponse)
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

        # Latest selectable/default day = the newest RELEASED session.
        #
        # Publication gate: a session (row date T) is exposed only once
        # cc-publish-session has stamped its pl_session_release row — i.e. its
        # data is complete AND (normal path) its NotebookLM audio is present.
        # The flip is therefore atomic (never a half-filled section) and can
        # happen the same evening T rather than waiting for the T+1 calendar
        # date. We read the released session's display_date (what the calendar
        # shows). No `<= today` cap here: the newest session that HAS data is
        # by construction the last close, so its display_date (= T+1) is exactly
        # the day we want to surface tonight — a future session can't be
        # published because its data doesn't exist yet.
        from sqlalchemy import func as sa_func

        today = date.today()
        released_result = await db.execute(
            select(sa_func.max(PlContractDataDaily.display_date)).join(
                PlSessionRelease,
                PlSessionRelease.session_date == PlContractDataDaily.date,
            )
        )
        latest_display = released_result.scalar_one_or_none()

        # Safe fallback — while pl_session_release is empty (feature dormant or
        # before the first publish), preserve the legacy behavior: newest
        # display_date not in the future. Guarantees zero regression until the
        # publish job starts stamping releases.
        if latest_display is None:
            legacy_result = await db.execute(
                select(sa_func.max(PlContractDataDaily.display_date)).where(
                    PlContractDataDaily.display_date <= today
                )
            )
            latest_display = legacy_result.scalar_one_or_none()

        # Fallback to trading calendar if no display_date populated yet
        if latest_display is None:
            latest_td = await get_latest_trading_day(db)
            latest_display = latest_td

        return {
            "dates": non_trading_dates,
            "latest_trading_day": latest_display.isoformat(),
        }
    except TradingCalendarError:
        return {"dates": [], "latest_trading_day": None}
    except Exception as e:
        logger.error("Error fetching non-trading days: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/macro-panel",
    response_model=MacroPanelResponse,
    dependencies=[Depends(require_any_entitlement(ent.FEATURE_MACRO_PANEL))],
)
@limiter.limit("60/minute")
async def get_macro_panel_endpoint(
    request: Request,
    target_date: Optional[str] = Query(
        default=None, description="Date for macro panel (YYYY-MM-DD format)"
    ),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MacroPanelResponse:
    """FX + ENSO + ensemble macro context.

    Returns FX values (most recent business day on/before the date), ENSO
    (most recent monthly publication, lag-corrected), and ensemble macro
    diagnostics when available. Macro context fields are NULL on legacy dates.
    """
    try:
        business_date = None
        if target_date:
            business_date = await _parse_and_validate_date(target_date, db)
        resolution_date = business_date or datetime.now(timezone.utc).date()

        contract_id = await _resolve_contract_for_request(db, business_date)
        algo_id, algo_name = await _resolve_algo_for_date(
            db, business_date, contract_id
        )

        data = await get_macro_panel(
            db, resolution_date, contract_id=contract_id, algo_id=algo_id
        )
        return MacroPanelResponse(**data, source_algorithm=algo_name)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting macro panel: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/farmgate-price",
    response_model=FarmgatePriceResponse,
    dependencies=[Depends(require_any_entitlement(ent.FEATURE_FARMGATE))],
)
@limiter.limit("60/minute")
async def get_farmgate_price_endpoint(
    request: Request,
    target_date: Optional[str] = Query(
        default=None, description="Date for farmgate price (YYYY-MM-DD format)"
    ),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FarmgatePriceResponse:
    """Official / guaranteed farmgate price — CIV (CCC) + Ghana (COCOBOD).

    Returns, per region, the most recent price effective on or before the date.
    This is the official guaranteed price (distinct from the real terrain price);
    a region is NULL when nothing has been announced on or before the date.
    """
    try:
        business_date = None
        if target_date:
            business_date = await _parse_and_validate_date(target_date, db)
        resolution_date = business_date or datetime.now(timezone.utc).date()

        data = await get_farmgate_prices(db, resolution_date)
        return FarmgatePriceResponse(**data)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting farmgate price: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/positioning",
    response_model=PositioningResponse,
    dependencies=[Depends(require_any_entitlement(ent.FEATURE_POSITIONING))],
)
@limiter.limit("60/minute")
async def get_positioning_endpoint(
    request: Request,
    target_date: Optional[str] = Query(
        default=None, description="Date for positioning (YYYY-MM-DD format)"
    ),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PositioningResponse:
    """COT EU (Managed Money + Producer/Merchant nets) + Stock EU/US.

    Stock EU is the principal signal (60kg bags). Stock US is retained as a
    secondary metric and is used to compute the EU/US ratio in tonnes.
    """
    try:
        business_date = None
        if target_date:
            business_date = await _parse_and_validate_date(target_date, db)
        resolution_date = business_date or datetime.now(timezone.utc).date()

        contract_id = await _resolve_contract_for_request(db, business_date)

        data = await get_positioning(db, resolution_date, contract_id=contract_id)
        return PositioningResponse(**data)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting positioning: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/ensemble-diagnostics",
    response_model=EnsembleDiagnosticsResponse,
    dependencies=[Depends(require_any_entitlement(ent.FEATURE_ENSEMBLE_DIAGNOSTICS))],
)
@limiter.limit("60/minute")
async def get_ensemble_diagnostics_endpoint(
    request: Request,
    target_date: Optional[str] = Query(
        default=None, description="Date for ensemble diagnostics (YYYY-MM-DD format)"
    ),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EnsembleDiagnosticsResponse:
    """Soft-gate + wrapper audit row for an ensemble date.

    Returns 404 on dates without an ensemble row (pre-2025-12-15 or future
    dates) — the frontend conditionally hides Section VII in that case.
    """
    try:
        business_date = None
        if target_date:
            business_date = await _parse_and_validate_date(target_date, db)
        resolution_date = business_date or datetime.now(timezone.utc).date()

        contract_id = await _resolve_contract_for_request(db, business_date)
        algo_id, algo_name = await _resolve_algo_for_date(
            db, business_date, contract_id
        )
        if algo_name != ENSEMBLE_VERSION_NAME:
            raise HTTPException(
                status_code=404,
                detail="No ensemble diagnostics available for this date",
            )

        data = await get_ensemble_diagnostics(
            db,
            resolution_date,
            contract_id=contract_id,
            algo_id=algo_id,
            algo_name=algo_name,
        )
        if data is None:
            raise HTTPException(
                status_code=404,
                detail="No ensemble diagnostics row found for this date",
            )
        return EnsembleDiagnosticsResponse(**data)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting ensemble diagnostics: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/specialist-votes",
    response_model=SpecialistVotesResponse,
    dependencies=[Depends(require_any_entitlement(ent.FEATURE_SPECIALIST_VOTES))],
)
@limiter.limit("60/minute")
async def get_specialist_votes_endpoint(
    request: Request,
    target_date: Optional[str] = Query(
        default=None, description="Date for specialist votes (YYYY-MM-DD format)"
    ),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SpecialistVotesResponse:
    """14 specialist votes + cluster mapping for an ensemble date.

    Returns 404 on legacy dates (no ensemble row).
    """
    try:
        business_date = None
        if target_date:
            business_date = await _parse_and_validate_date(target_date, db)
        resolution_date = business_date or datetime.now(timezone.utc).date()

        contract_id = await _resolve_contract_for_request(db, business_date)
        algo_id, algo_name = await _resolve_algo_for_date(
            db, business_date, contract_id
        )
        if algo_name != ENSEMBLE_VERSION_NAME:
            raise HTTPException(
                status_code=404,
                detail="No specialist votes available for this date",
            )

        data = await get_specialist_votes(
            db,
            resolution_date,
            contract_id=contract_id,
            algo_id=algo_id,
            algo_name=algo_name,
        )
        if data is None:
            raise HTTPException(
                status_code=404,
                detail="No specialist vote rows found for this date",
            )
        return SpecialistVotesResponse(
            date=data["date"],
            algorithm_version=data["algorithm_version"],
            votes=[SpecialistVote(**v) for v in data["votes"]],
            winter_signed=data["winter_signed"],
            spring_signed=data["spring_signed"],
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting specialist votes: {e}")
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
