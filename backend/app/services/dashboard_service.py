"""Dashboard business logic service.

Contains pure business logic functions for dashboard operations,
independent of FastAPI dependencies for better testability and reusability.
"""

import logging
import re
from datetime import date, time, timedelta
from datetime import datetime as dt_datetime
from typing import Any, Dict, List, Optional

from decimal import Decimal

from sqlalchemy import and_, asc, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.indicator import Indicator
from app.models.market_research import MarketResearch
from app.models.technicals import Technicals
from app.models.test_range import TestRange
from app.models.weather_data import WeatherData
from app.utils.date_utils import get_business_date, get_year_start_date

logger = logging.getLogger(__name__)


def _date_filter(column, target_date: date):
    """Create a range filter that uses timestamp indices efficiently.

    Replaces func.date(column) == target_date which defeats index usage
    by applying a function to every row before comparison.
    """
    day_start = dt_datetime.combine(target_date, time.min)
    day_end = dt_datetime.combine(target_date + timedelta(days=1), time.min)
    return and_(column >= day_start, column < day_end)


def _score_day(decision: str, close_t: float, close_t1: float) -> Optional[float]:
    """Replicate the Google Sheets CONCLUSION scoring formula server-side.

    Scoring rules (mirrors TECHNICALS column AS formula exactly):
      OPEN  + price up   → +1.25 if |move| > 1%, else +1
      HEDGE + price down → +1.25 if |move| > 1%, else +1
      OPEN  + price down → -2 × |%change|
      HEDGE + price up   → -2 × |%change|
      MONITOR + any move → +1 if |move| > 1%, else +0.75
      MONITOR + no move  → 0

    No contract roll filtering — matches the original formula behavior.
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


async def calculate_ytd_performance(
    db: AsyncSession, reference_date: Optional[date] = None
) -> float:
    """Calculate YTD performance by replicating the CONCLUSION scoring server-side.

    Computes from raw decision + close data instead of the mutable Google Sheets
    CONCLUSION formula. Deterministic regardless of import timing.
    """
    if reference_date is None:
        reference_date = date.today()

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

    for i in range(len(rows) - 1):
        current = rows[i]
        next_day = rows[i + 1]

        decision = current.decision
        close_t = current.close
        close_t1 = next_day.close

        if not decision or not close_t or not close_t1:
            continue

        decision_upper = decision.strip().upper()
        close_t_f = float(close_t) if isinstance(close_t, Decimal) else close_t
        close_t1_f = float(close_t1) if isinstance(close_t1, Decimal) else close_t1

        score = _score_day(decision_upper, close_t_f, close_t1_f)
        if score is not None:
            scores.append(score)

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


async def get_latest_technicals(
    db: AsyncSession, target_date: Optional[date] = None
) -> Optional[Technicals]:
    """Get the latest technicals record for a given date."""
    query = select(Technicals).order_by(desc(Technicals.timestamp))

    if target_date:
        business_date = get_business_date(target_date)
        query = query.where(_date_filter(Technicals.timestamp, business_date))

    result = await db.execute(query)
    return result.scalars().first()


async def get_indicators_with_ranges(
    db: AsyncSession, target_date: Optional[date] = None
) -> Dict[str, Dict[str, Any]]:
    """Get all indicators with their ranges for a given date."""
    query = select(Indicator).order_by(desc(Indicator.date))

    if target_date:
        business_date = get_business_date(target_date)
        query = query.where(_date_filter(Indicator.date, business_date))

    result = await db.execute(query)
    indicator = result.scalars().first()

    if not indicator:
        return {}

    # Get all test ranges
    ranges_query = select(TestRange)
    ranges_result = await db.execute(ranges_query)
    all_ranges = ranges_result.scalars().all()

    # Group ranges by indicator
    ranges_by_indicator: dict[str, list] = {}
    for range_obj in all_ranges:
        if range_obj.indicator not in ranges_by_indicator:
            ranges_by_indicator[range_obj.indicator] = []
        ranges_by_indicator[range_obj.indicator].append(range_obj)

    indicators = {}

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
            line = re.sub(r"^[-•*]\s*", "", line)
            if line:
                recommendations.append(line)

    return recommendations


async def get_latest_recommendations(
    db: AsyncSession, target_date: Optional[date] = None
) -> tuple[List[str], Optional[str], Optional[date]]:
    """Get the latest recommendations from technicals data."""
    technicals = await get_latest_technicals(db, target_date)
    if not technicals or not technicals.score:
        return [], None, None

    recommendations = parse_recommendations_text(technicals.score)
    return recommendations, technicals.score, technicals.timestamp


async def get_chart_data(db: AsyncSession, days: int = 30) -> List[Dict[str, Any]]:
    """Get historical chart data for the specified number of days.

    Selects only needed columns instead of loading full ORM objects.
    """
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


async def get_latest_market_research(
    db: AsyncSession, target_date: Optional[date] = None
) -> Optional[MarketResearch]:
    """Get the latest market research record."""
    query = select(MarketResearch).order_by(desc(MarketResearch.date))

    if target_date:
        business_date = get_business_date(target_date)
        query = query.where(_date_filter(MarketResearch.date, business_date))

    result = await db.execute(query)
    return result.scalars().first()


async def get_latest_weather_data(
    db: AsyncSession, target_date: Optional[date] = None
) -> Optional[WeatherData]:
    """Get the latest weather data record."""
    query = select(WeatherData).order_by(desc(WeatherData.date))

    if target_date:
        business_date = get_business_date(target_date)
        query = query.where(_date_filter(WeatherData.date, business_date))

    result = await db.execute(query)
    return result.scalars().first()


async def get_position_from_technicals(
    db: AsyncSession, target_date: Optional[date] = None
) -> Optional[str]:
    """Get the position of the day from technicals decision data."""
    query = select(Technicals).order_by(desc(Technicals.timestamp))

    if target_date:
        business_date = get_business_date(target_date)
        query = query.where(_date_filter(Technicals.timestamp, business_date))

    result = await db.execute(query)
    technicals = result.scalars().first()

    if not technicals:
        return None

    return technicals.decision
