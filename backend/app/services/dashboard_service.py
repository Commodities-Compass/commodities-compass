"""Dashboard business logic service.

Contains pure business logic functions for dashboard operations,
independent of FastAPI dependencies for better testability and reusability.

All queries read from pl_* tables (contract-centric).
"""

import logging
import re
from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, asc, desc, join, outerjoin, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline import (
    PlContractDataDaily,
    PlDerivedIndicators,
    PlFundamentalArticle,
    PlIndicatorDaily,
    PlWeatherObservation,
)
from app.models.test_range import TestRange
from app.utils.contract_resolver import (
    get_active_algorithm_version_id,
    get_active_contract_id,
)
from app.utils.date_utils import get_year_start_date

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _score_day(decision: str, close_t: float, close_t1: float) -> Optional[float]:
    """Replicate the CONCLUSION scoring formula server-side.

    Scoring rules:
      OPEN  + price up   -> +1.25 if |move| > 1%, else +1
      HEDGE + price down -> +1.25 if |move| > 1%, else +1
      OPEN  + price down -> -2 x |%change|
      HEDGE + price up   -> -2 x |%change|
      MONITOR + any move -> +1 if |move| > 1%, else +0.75
      MONITOR + no move  -> 0
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
    """Calculate YTD performance by replicating the CONCLUSION scoring server-side."""
    if reference_date is None:
        reference_date = date.today()

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
        "YTD Performance: %.2f%% (%d days scored)",
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
    """Build the indicators dict from normalized values + test_range table."""
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


async def get_latest_recommendations(
    db: AsyncSession, target_date: Optional[date] = None
) -> tuple[List[str], Optional[str], Optional[date]]:
    """Get the latest recommendations from pl_indicator_daily.conclusion."""
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


async def get_chart_data(
    db: AsyncSession, days: int = 30, *, end_date: Optional[date] = None
) -> List[Dict[str, Any]]:
    """Get historical chart data for the specified number of days.

    Queries the active contract first. If fewer rows than requested (contract
    rolled recently), falls back to a cross-contract query ordered by date so
    the chart always has enough history.
    """
    contract_id = await get_active_contract_id(db)

    base_cols = (
        PlContractDataDaily.date,
        PlContractDataDaily.close,
        PlContractDataDaily.volume,
        PlContractDataDaily.oi,
        PlDerivedIndicators.rsi_14d,
        PlDerivedIndicators.macd,
        PlContractDataDaily.stock_us,
        PlContractDataDaily.com_net_us,
    )

    # Try active contract first
    date_filter = [PlContractDataDaily.contract_id == contract_id]
    if end_date is not None:
        date_filter.append(PlContractDataDaily.date <= end_date)

    query = (
        select(*base_cols)
        .select_from(
            outerjoin(
                PlContractDataDaily,
                PlDerivedIndicators,
                and_(
                    PlContractDataDaily.date == PlDerivedIndicators.date,
                    PlContractDataDaily.contract_id == PlDerivedIndicators.contract_id,
                ),
            )
        )
        .where(and_(*date_filter))
        .order_by(desc(PlContractDataDaily.date))
        .limit(days)
    )

    result = await db.execute(query)
    rows = result.all()

    # Fallback: active contract has fewer rows than requested (recent roll)
    if len(rows) < days:
        fallback_filter = []
        if end_date is not None:
            fallback_filter.append(PlContractDataDaily.date <= end_date)

        fallback_query = select(*base_cols).select_from(
            outerjoin(
                PlContractDataDaily,
                PlDerivedIndicators,
                and_(
                    PlContractDataDaily.date == PlDerivedIndicators.date,
                    PlContractDataDaily.contract_id == PlDerivedIndicators.contract_id,
                ),
            )
        )
        if fallback_filter:
            fallback_query = fallback_query.where(and_(*fallback_filter))
        fallback_query = fallback_query.order_by(desc(PlContractDataDaily.date)).limit(
            days
        )
        result = await db.execute(fallback_query)
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
# 6. News (fundamental articles)
# ---------------------------------------------------------------------------


async def get_latest_market_research(
    db: AsyncSession, target_date: Optional[date] = None
) -> Optional[Dict[str, Any]]:
    """Get the latest active fundamental article."""
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
        "keywords": article.keywords,
        "author": article.source or article.llm_provider,
    }


# ---------------------------------------------------------------------------
# 7. Weather
# ---------------------------------------------------------------------------


async def get_latest_weather_data(
    db: AsyncSession, target_date: Optional[date] = None
) -> Optional[Dict[str, Any]]:
    """Get the latest weather observation."""
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
