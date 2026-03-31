"""Dashboard business logic service.

Contains pure business logic functions for dashboard operations,
independent of FastAPI dependencies for better testability and reusability.

Feature flag USE_NEW_TABLES controls whether queries hit legacy tables
(technicals, indicator, market_research, weather_data) or new pl_* tables
(pl_contract_data_daily, pl_indicator_daily, pl_derived_indicators, etc.).
"""

import logging
import re
from datetime import date, time, timedelta
from datetime import datetime as dt_datetime
from typing import Any, Dict, List, Optional, Union

from decimal import Decimal

from sqlalchemy import and_, asc, desc, join, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.indicator import Indicator
from app.models.market_research import MarketResearch
from app.models.pipeline import (
    PlContractDataDaily,
    PlDerivedIndicators,
    PlFundamentalArticle,
    PlIndicatorDaily,
    PlWeatherObservation,
)
from app.models.technicals import Technicals
from app.models.test_range import TestRange
from app.models.weather_data import WeatherData
from app.utils.contract_resolver import (
    get_active_algorithm_version_id,
    get_active_contract_id,
)
from app.utils.date_utils import get_year_start_date
from app.utils.trading_calendar import get_latest_trading_day

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _date_filter(column, target_date: date):
    """Create a range filter for TIMESTAMP columns that uses indices efficiently.

    Replaces func.date(column) == target_date which defeats index usage.
    For DATE columns, use direct == comparison instead.
    """
    day_start = dt_datetime.combine(target_date, time.min)
    day_end = dt_datetime.combine(target_date + timedelta(days=1), time.min)
    return and_(column >= day_start, column < day_end)


def _score_day(decision: str, close_t: float, close_t1: float) -> Optional[float]:
    """Replicate the Google Sheets CONCLUSION scoring formula server-side.

    Scoring rules (mirrors TECHNICALS column AS formula exactly):
      OPEN  + price up   -> +1.25 if |move| > 1%, else +1
      HEDGE + price down -> +1.25 if |move| > 1%, else +1
      OPEN  + price down -> -2 x |%change|
      HEDGE + price up   -> -2 x |%change|
      MONITOR + any move -> +1 if |move| > 1%, else +0.75
      MONITOR + no move  -> 0

    No contract roll filtering -- matches the original formula behavior.
    """
    if close_t == 0:
        return None

    abs_pct = abs((close_t1 - close_t) / close_t)

    if decision == "OPEN":
        if close_t1 > close_t:
            return 1.25 if abs_pct > 0.01 else 1.0
        return -abs_pct * 2

    if decision == "HEDGE":
        if close_t1 < close_t:
            return 1.25 if abs_pct > 0.01 else 1.0
        return -abs_pct * 2

    if decision == "MONITOR":
        if close_t1 != close_t:
            return 1.0 if abs_pct > 0.01 else 0.75
        return 0.0

    return None


def parse_recommendations_text(text: str) -> list[str]:
    """Parse recommendations from raw text. Pure CPU, no I/O."""
    if not text:
        return []

    # Strip HTML tags replacing them with newlines
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</?[a-z][a-z0-9]*[^>]*>", "\n", text, flags=re.IGNORECASE)

    lines = text.split("\n")
    recommendations = []

    for line in lines:
        line = line.strip()
        if line:
            line = re.sub(r"^[-\u2022*]\s*", "", line)
            if line:
                recommendations.append(line)

    return recommendations


# ---------------------------------------------------------------------------
# 1. Position
# ---------------------------------------------------------------------------


async def get_position_from_technicals(
    db: AsyncSession, target_date: Optional[date] = None
) -> Optional[str]:
    """Get the trading position (OPEN/HEDGE/MONITOR) for a given date."""
    if settings.USE_NEW_TABLES:
        return await _pl_get_position(db, target_date)

    query = select(Technicals).order_by(desc(Technicals.timestamp))

    if target_date:
        business_date = await get_latest_trading_day(db, target_date)
        query = query.where(_date_filter(Technicals.timestamp, business_date))

    result = await db.execute(query)
    technicals = result.scalars().first()
    return technicals.decision if technicals else None


async def _pl_get_position(
    db: AsyncSession, target_date: Optional[date]
) -> Optional[str]:
    """Position from pl_indicator_daily (contract-centric)."""
    contract_id = await get_active_contract_id(db)
    algo_id = await get_active_algorithm_version_id(db)

    query = select(PlIndicatorDaily.decision).where(
        and_(
            PlIndicatorDaily.contract_id == contract_id,
            PlIndicatorDaily.algorithm_version_id == algo_id,
        )
    )

    if target_date:
        query = query.where(PlIndicatorDaily.date == target_date)

    query = query.order_by(desc(PlIndicatorDaily.date)).limit(1)
    result = await db.execute(query)
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# 2. YTD Performance
# ---------------------------------------------------------------------------


async def calculate_ytd_performance(
    db: AsyncSession, reference_date: Optional[date] = None
) -> float:
    """Calculate YTD performance by replicating the CONCLUSION scoring server-side.

    Computes from raw decision + close data instead of the mutable Google Sheets
    CONCLUSION formula. Deterministic regardless of import timing.
    """
    if reference_date is None:
        reference_date = date.today()

    if settings.USE_NEW_TABLES:
        return await _pl_calculate_ytd_performance(db, reference_date)

    start_of_year = get_year_start_date(reference_date)
    year_start_dt = dt_datetime.combine(start_of_year, time.min)
    year_end_dt = dt_datetime.combine(reference_date + timedelta(days=1), time.min)

    query = (
        select(Technicals.timestamp, Technicals.close, Technicals.decision)
        .where(
            and_(
                Technicals.timestamp >= year_start_dt,
                Technicals.timestamp < year_end_dt,
            )
        )
        .order_by(asc(Technicals.timestamp))
    )

    result = await db.execute(query)
    rows = result.all()

    scores: list[float] = []
    skipped = 0

    for i in range(len(rows) - 1):
        current = rows[i]
        next_day = rows[i + 1]

        decision = current.decision
        close_t = current.close
        close_t1 = next_day.close

        if not decision or not close_t or not close_t1:
            skipped += 1
            continue

        decision_upper = decision.strip().upper()
        close_t_f = float(close_t) if isinstance(close_t, Decimal) else close_t
        close_t1_f = float(close_t1) if isinstance(close_t1, Decimal) else close_t1

        score = _score_day(decision_upper, close_t_f, close_t1_f)
        if score is not None:
            scores.append(score)

    if skipped:
        logger.warning(
            "YTD calculation: skipped %d/%d rows (missing decision or close)",
            skipped,
            len(rows) - 1,
        )

    if not scores:
        logger.warning("No scoring data found for YTD calculation")
        return 0.0

    avg_score = sum(scores) / len(scores)
    ytd_performance = avg_score * 100
    logger.info(
        "YTD Performance: %.2f%% (server-side, %d days scored)",
        ytd_performance,
        len(scores),
    )
    return ytd_performance


async def _pl_calculate_ytd_performance(
    db: AsyncSession, reference_date: date
) -> float:
    """YTD performance from pl_* tables (contract-centric)."""
    contract_id = await get_active_contract_id(db)
    algo_id = await get_active_algorithm_version_id(db)
    start_of_year = get_year_start_date(reference_date)

    query = (
        select(
            PlContractDataDaily.date,
            PlContractDataDaily.close,
            PlIndicatorDaily.decision,
        )
        .select_from(
            join(
                PlContractDataDaily,
                PlIndicatorDaily,
                and_(
                    PlContractDataDaily.date == PlIndicatorDaily.date,
                    PlContractDataDaily.contract_id == PlIndicatorDaily.contract_id,
                ),
            )
        )
        .where(
            and_(
                PlContractDataDaily.contract_id == contract_id,
                PlIndicatorDaily.algorithm_version_id == algo_id,
                PlContractDataDaily.date >= start_of_year,
                PlContractDataDaily.date <= reference_date,
            )
        )
        .order_by(asc(PlContractDataDaily.date))
    )

    result = await db.execute(query)
    rows = result.all()

    scores: list[float] = []
    skipped = 0
    for i in range(len(rows) - 1):
        current = rows[i]
        next_row = rows[i + 1]

        if not current.decision or current.close is None or next_row.close is None:
            skipped += 1
            continue

        score = _score_day(
            current.decision.strip().upper(),
            float(current.close),
            float(next_row.close),
        )
        if score is not None:
            scores.append(score)

    if skipped:
        logger.warning(
            "YTD calculation (pl_*): skipped %d/%d rows (missing decision or close)",
            skipped,
            len(rows) - 1,
        )

    if not scores:
        logger.warning("No scoring data found for YTD calculation (pl_* tables)")
        return 0.0

    avg_score = sum(scores) / len(scores)
    ytd_performance = avg_score * 100
    logger.info(
        "YTD Performance: %.2f%% (pl_* tables, %d days scored)",
        ytd_performance,
        len(scores),
    )
    return ytd_performance


# ---------------------------------------------------------------------------
# 3. Indicators grid (gauges)
# ---------------------------------------------------------------------------


async def get_indicators_with_ranges(
    db: AsyncSession, target_date: Optional[date] = None
) -> Dict[str, Dict[str, Any]]:
    """Get all indicators with their ranges for a given date."""
    if settings.USE_NEW_TABLES:
        return await _pl_get_indicators_with_ranges(db, target_date)

    query = select(Indicator).order_by(desc(Indicator.date))

    if target_date:
        business_date = await get_latest_trading_day(db, target_date)
        query = query.where(_date_filter(Indicator.date, business_date))

    result = await db.execute(query)
    indicator = result.scalars().first()

    if not indicator:
        return {}

    return await _build_indicators_dict(
        macroeco=indicator.macroeco_score,
        rsi=indicator.rsi_norm,
        macd=indicator.macd_norm,
        stoch_k=indicator.stoch_k_norm,
        atr=indicator.atr_norm,
        vol_oi=indicator.vol_oi_norm,
        db=db,
    )


async def _pl_get_indicators_with_ranges(
    db: AsyncSession, target_date: Optional[date]
) -> Dict[str, Dict[str, Any]]:
    """Indicators from pl_indicator_daily (contract-centric)."""
    contract_id = await get_active_contract_id(db)
    algo_id = await get_active_algorithm_version_id(db)

    query = select(PlIndicatorDaily).where(
        and_(
            PlIndicatorDaily.contract_id == contract_id,
            PlIndicatorDaily.algorithm_version_id == algo_id,
        )
    )

    if target_date:
        query = query.where(PlIndicatorDaily.date == target_date)

    query = query.order_by(desc(PlIndicatorDaily.date)).limit(1)
    result = await db.execute(query)
    indicator = result.scalars().first()

    if not indicator:
        return {}

    return await _build_indicators_dict(
        macroeco=indicator.macroeco_score,
        rsi=indicator.rsi_norm,
        macd=indicator.macd_norm,
        stoch_k=indicator.stoch_k_norm,
        atr=indicator.atr_norm,
        vol_oi=indicator.vol_oi_norm,
        db=db,
    )


async def _build_indicators_dict(
    *,
    macroeco: Any,
    rsi: Any,
    macd: Any,
    stoch_k: Any,
    atr: Any,
    vol_oi: Any,
    db: AsyncSession,
) -> Dict[str, Dict[str, Any]]:
    """Build the indicators dict from normalized values + test_range table.

    Shared between legacy and pl_* paths since both use the same test_range
    table and produce identical output shapes.
    """
    ranges_query = select(TestRange)
    ranges_result = await db.execute(ranges_query)
    all_ranges = ranges_result.scalars().all()

    ranges_by_indicator: dict[str, list] = {}
    for range_obj in all_ranges:
        if range_obj.indicator not in ranges_by_indicator:
            ranges_by_indicator[range_obj.indicator] = []
        ranges_by_indicator[range_obj.indicator].append(range_obj)

    indicators: Dict[str, Dict[str, Any]] = {}

    indicator_configs = [
        ("macroeco", macroeco, "MACROECO", "MACROECO"),
        ("rsi", rsi, "RSI", "RSI"),
        ("macd", macd, "MACD", "MACD"),
        ("percentK", stoch_k, "%K", "%K"),
        ("atr", atr, "ATR", "ATR"),
        ("volOi", vol_oi, "VOL/OI", "VOL_OI"),
    ]

    for key, value, label, range_indicator_name in indicator_configs:
        if value is not None and range_indicator_name in ranges_by_indicator:
            ranges = ranges_by_indicator[range_indicator_name]

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


# ---------------------------------------------------------------------------
# 4. Recommendations
# ---------------------------------------------------------------------------


async def get_latest_technicals(
    db: AsyncSession, target_date: Optional[date] = None
) -> Optional[Technicals]:
    """Get the latest technicals record for a given date (legacy only)."""
    query = select(Technicals).order_by(desc(Technicals.timestamp))

    if target_date:
        business_date = await get_latest_trading_day(db, target_date)
        query = query.where(_date_filter(Technicals.timestamp, business_date))

    result = await db.execute(query)
    return result.scalars().first()


async def get_latest_recommendations(
    db: AsyncSession, target_date: Optional[date] = None
) -> tuple[List[str], Optional[str], Optional[date]]:
    """Get the latest recommendations from technicals/indicator data."""
    if settings.USE_NEW_TABLES:
        return await _pl_get_latest_recommendations(db, target_date)

    technicals = await get_latest_technicals(db, target_date)
    if not technicals or not technicals.score:
        return [], None, None

    recommendations = parse_recommendations_text(technicals.score)
    return recommendations, technicals.score, technicals.timestamp


async def _pl_get_latest_recommendations(
    db: AsyncSession, target_date: Optional[date]
) -> tuple[List[str], Optional[str], Optional[date]]:
    """Recommendations from pl_indicator_daily.conclusion."""
    contract_id = await get_active_contract_id(db)
    algo_id = await get_active_algorithm_version_id(db)

    query = select(PlIndicatorDaily.conclusion, PlIndicatorDaily.date).where(
        and_(
            PlIndicatorDaily.contract_id == contract_id,
            PlIndicatorDaily.algorithm_version_id == algo_id,
        )
    )

    if target_date:
        query = query.where(PlIndicatorDaily.date == target_date)

    query = query.order_by(desc(PlIndicatorDaily.date)).limit(1)
    result = await db.execute(query)
    row = result.one_or_none()

    if not row or not row.conclusion:
        return [], None, None

    recommendations = parse_recommendations_text(row.conclusion)
    return recommendations, row.conclusion, row.date


# ---------------------------------------------------------------------------
# 5. Chart data
# ---------------------------------------------------------------------------


async def get_chart_data(db: AsyncSession, days: int = 30) -> List[Dict[str, Any]]:
    """Get historical chart data for the specified number of days."""
    if settings.USE_NEW_TABLES:
        return await _pl_get_chart_data(db, days)

    query = (
        select(
            Technicals.timestamp,
            Technicals.close,
            Technicals.volume,
            Technicals.open_interest,
            Technicals.rsi_14d,
            Technicals.macd,
            Technicals.stock_us,
            Technicals.com_net_us,
        )
        .order_by(desc(Technicals.timestamp))
        .limit(days)
    )

    result = await db.execute(query)
    rows = result.all()

    return [
        {
            "date": row.timestamp.strftime("%Y-%m-%d"),
            "close": (float(row.close) if row.close is not None else None),
            "volume": (float(row.volume) if row.volume is not None else None),
            "open_interest": (
                float(row.open_interest) if row.open_interest is not None else None
            ),
            "rsi_14d": (float(row.rsi_14d) if row.rsi_14d is not None else None),
            "macd": (float(row.macd) if row.macd is not None else None),
            "stock_us": (float(row.stock_us) if row.stock_us is not None else None),
            "com_net_us": (
                float(row.com_net_us) if row.com_net_us is not None else None
            ),
        }
        for row in reversed(rows)
    ]


async def _pl_get_chart_data(db: AsyncSession, days: int) -> List[Dict[str, Any]]:
    """Chart data from pl_contract_data_daily + pl_derived_indicators."""
    contract_id = await get_active_contract_id(db)

    query = (
        select(
            PlContractDataDaily.date,
            PlContractDataDaily.close,
            PlContractDataDaily.volume,
            PlContractDataDaily.oi,
            PlDerivedIndicators.rsi_14d,
            PlDerivedIndicators.macd,
            PlContractDataDaily.stock_us,
            PlContractDataDaily.com_net_us,
        )
        .select_from(
            join(
                PlContractDataDaily,
                PlDerivedIndicators,
                and_(
                    PlContractDataDaily.date == PlDerivedIndicators.date,
                    PlContractDataDaily.contract_id == PlDerivedIndicators.contract_id,
                ),
            )
        )
        .where(PlContractDataDaily.contract_id == contract_id)
        .order_by(desc(PlContractDataDaily.date))
        .limit(days)
    )

    result = await db.execute(query)
    rows = result.all()

    return [
        {
            "date": row.date.strftime("%Y-%m-%d"),
            "close": float(row.close) if row.close is not None else None,
            "volume": float(row.volume) if row.volume is not None else None,
            "open_interest": float(row.oi) if row.oi is not None else None,
            "rsi_14d": float(row.rsi_14d) if row.rsi_14d is not None else None,
            "macd": float(row.macd) if row.macd is not None else None,
            "stock_us": float(row.stock_us) if row.stock_us is not None else None,
            "com_net_us": (
                float(row.com_net_us) if row.com_net_us is not None else None
            ),
        }
        for row in reversed(rows)
    ]


# ---------------------------------------------------------------------------
# 6. News (market research / fundamental articles)
# ---------------------------------------------------------------------------


async def get_latest_market_research(
    db: AsyncSession, target_date: Optional[date] = None
) -> Union[Optional[MarketResearch], Optional[Dict[str, Any]]]:
    """Get the latest market research / fundamental article.

    Returns MarketResearch ORM when USE_NEW_TABLES=false,
    or a dict with keys {date, impact_synthesis, summary, author} when true.
    """
    if settings.USE_NEW_TABLES:
        return await _pl_get_latest_article(db, target_date)

    query = select(MarketResearch).order_by(desc(MarketResearch.date))

    if target_date:
        business_date = await get_latest_trading_day(db, target_date)
        query = query.where(_date_filter(MarketResearch.date, business_date))

    result = await db.execute(query)
    return result.scalars().first()


async def _pl_get_latest_article(
    db: AsyncSession, target_date: Optional[date]
) -> Optional[Dict[str, Any]]:
    """Latest active article from pl_fundamental_article."""
    query = (
        select(PlFundamentalArticle)
        .where(PlFundamentalArticle.is_active.is_(True))
        .order_by(
            desc(PlFundamentalArticle.date),
            desc(PlFundamentalArticle.created_at),
        )
    )

    if target_date:
        query = query.where(PlFundamentalArticle.date == target_date)

    query = query.limit(1)
    result = await db.execute(query)
    article = result.scalars().first()

    if not article:
        return None

    return {
        "date": article.date,
        "impact_synthesis": article.impact_synthesis,
        "summary": article.summary,
        "author": article.source or article.llm_provider,
    }


# ---------------------------------------------------------------------------
# 7. Weather
# ---------------------------------------------------------------------------


async def get_latest_weather_data(
    db: AsyncSession, target_date: Optional[date] = None
) -> Union[Optional[WeatherData], Optional[Dict[str, Any]]]:
    """Get the latest weather observation.

    Returns WeatherData ORM when USE_NEW_TABLES=false,
    or a dict with keys {date, text, impact_synthesis} when true.
    """
    if settings.USE_NEW_TABLES:
        return await _pl_get_latest_weather(db, target_date)

    query = select(WeatherData).order_by(desc(WeatherData.date))

    if target_date:
        business_date = await get_latest_trading_day(db, target_date)
        query = query.where(_date_filter(WeatherData.date, business_date))

    result = await db.execute(query)
    return result.scalars().first()


async def _pl_get_latest_weather(
    db: AsyncSession, target_date: Optional[date]
) -> Optional[Dict[str, Any]]:
    """Latest observation from pl_weather_observation."""
    query = select(PlWeatherObservation).order_by(
        desc(PlWeatherObservation.date),
        desc(PlWeatherObservation.created_at),
    )

    if target_date:
        query = query.where(PlWeatherObservation.date == target_date)

    query = query.limit(1)
    result = await db.execute(query)
    obs = result.scalars().first()

    if not obs:
        return None

    return {
        "date": obs.date,
        "text": obs.observation,
        "impact_synthesis": obs.impact_assessment,
    }
