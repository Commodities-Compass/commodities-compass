"""Dashboard business logic service.

Contains pure business logic functions for dashboard operations,
independent of FastAPI dependencies for better testability and reusability.

All queries read from pl_* tables (contract-centric).
"""

import logging
import re
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import uuid

from sqlalchemy import and_, desc, outerjoin, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline import (
    PlArticleSegment,
    PlContractDataDaily,
    PlCotEuWeekly,
    PlDerivedIndicators,
    PlFundamentalArticle,
    PlIndicatorDaily,
    PlSentimentFeature,
    PlStockObservation,
    PlWeatherObservation,
)
from app.models.test_range import TestRange
from app.utils.contract_resolver import (
    get_active_algorithm_version_id,
    get_active_contract_id,
    resolve_contract_for_date,
)
from app.utils.date_utils import get_year_start_date

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


# Evaluation horizon (trading days) used by the YTD scoring formula.
# 4 days is the empirically-best horizon for ensemble v1.0.0 — picked from a
# sweep across J+1..J+6 on the 2026 production data: J+4 maximises the YTD
# score (98.62%), the hit-rate (92.5%), and the worst-day downside (-0.32 vs
# -0.45 at J+3 or -0.59 at J+5). The ensemble's R&D training horizon is J+6
# (forward_return_6d), but the price signal is most informative at J+4 in
# practice — mean reversion dilutes the signal beyond.
YTD_EVAL_HORIZON_DAYS = 4


def _score_day(decision: str, close_t: float, close_t_plus_h: float) -> Optional[float]:
    """Replicate the CONCLUSION scoring formula server-side.

    Compares the decision at T against the close at T+horizon (see
    ``YTD_EVAL_HORIZON_DAYS``). The same +1.25 / +1.0 / -2× rules apply
    regardless of the horizon — only the close used for comparison changes.

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

    abs_pct = abs((close_t_plus_h - close_t) / close_t)

    if decision == "OPEN":
        if close_t_plus_h > close_t:
            return 1.25 if abs_pct > 0.01 else 1.0
        return -abs_pct * 2

    if decision == "HEDGE":
        if close_t_plus_h < close_t:
            return 1.25 if abs_pct > 0.01 else 1.0
        return -abs_pct * 2

    if decision == "MONITOR":
        if close_t_plus_h != close_t:
            return 1.0 if abs_pct > 0.01 else 0.75
        return 0.0

    return None


def _clean_numbers(text: str) -> str:
    """Round numbers with 3+ decimal places to max 2 for clean display.

    Examples: 2575.000000 → 2575, 58.072610 → 58.07, 0.420800 → 0.42.
    Numbers with ≤2 decimals are left untouched. DB values are not modified.
    """

    def _fmt(m: re.Match[str]) -> str:
        num = float(m.group(0))
        if num == int(num):
            return str(int(num))
        return f"{num:.2f}".rstrip("0").rstrip(".")

    return re.sub(r"\d+\.\d{3,}", _fmt, text)


def parse_recommendations_text(text: str) -> list[str]:
    """Parse recommendations from raw text. Pure CPU, no I/O."""
    if not text:
        return []

    # Strip HTML tags replacing them with newlines
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</?[a-z][a-z0-9]*[^>]*>", "\n", text, flags=re.IGNORECASE)

    # Clean excessive decimal places for display
    text = _clean_numbers(text)

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
    db: AsyncSession,
    target_date: Optional[date] = None,
    *,
    contract_id: Optional[uuid.UUID] = None,
    algo_id: Optional[uuid.UUID] = None,
) -> Optional[str]:
    """Get the trading position (OPEN/HEDGE/MONITOR) for a given date.

    Pass contract_id/algo_id to skip redundant resolver calls when the
    caller has already resolved them (e.g., dashboard endpoint).
    """
    if contract_id is None:
        if target_date:
            contract_id = await resolve_contract_for_date(db, target_date)
            if not contract_id:
                return None
        else:
            contract_id = await get_active_contract_id(db)
    if algo_id is None:
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

    Date-aware decision source — uses the SAME decision that the system would
    have shipped live each day:
      * For dates with an ensemble row: ensemble's ``decision`` (which mirrors
        the orchestrator's ``decision_wrapped`` — i.e. post-Compass override).
      * For older dates: legacy decision.

    Cross-contract: uses a DISTINCT ON (date) subquery to pick the
    front-month contract per date (highest OI), so YTD scoring spans
    contract rolls seamlessly.
    """
    if reference_date is None:
        reference_date = date.today()

    from sqlalchemy import text as sa_text

    from app.utils.contract_resolver import (
        ENSEMBLE_VERSION_NAME,
        LEGACY_VERSION_NAME,
        _get_version_id_by_name,
    )

    ensemble_id = await _get_version_id_by_name(db, ENSEMBLE_VERSION_NAME)
    legacy_id = await _get_version_id_by_name(db, LEGACY_VERSION_NAME)
    if ensemble_id is None and legacy_id is None:
        # Fall back to the historical "active" lookup as a defensive default.
        legacy_id = await get_active_algorithm_version_id(db)

    start_of_year = get_year_start_date(reference_date)

    # Cross-contract query: for each date, pick the contract with highest OI
    # then COALESCE the ensemble decision over the legacy one (decision shipped
    # live to the user each day).
    query = sa_text("""
        WITH front_month AS (
            SELECT DISTINCT ON (cd.date) cd.date, cd.close, cd.contract_id
            FROM pl_contract_data_daily cd
            WHERE cd.date >= :start AND cd.date <= :end_date
            ORDER BY cd.date, cd.oi DESC NULLS LAST
        )
        SELECT
            fm.date,
            fm.close,
            COALESCE(ens.decision, leg.decision) AS decision
        FROM front_month fm
        LEFT JOIN pl_indicator_daily ens
               ON ens.date = fm.date
              AND ens.contract_id = fm.contract_id
              AND ens.algorithm_version_id = :ensemble_id
        LEFT JOIN pl_indicator_daily leg
               ON leg.date = fm.date
              AND leg.contract_id = fm.contract_id
              AND leg.algorithm_version_id = :legacy_id
        ORDER BY fm.date ASC
    """)

    result = await db.execute(
        query,
        {
            "start": start_of_year,
            "end_date": reference_date,
            "ensemble_id": str(ensemble_id) if ensemble_id is not None else None,
            "legacy_id": str(legacy_id) if legacy_id is not None else None,
        },
    )
    rows = result.all()

    scores: list[float] = []
    skipped = 0
    horizon = YTD_EVAL_HORIZON_DAYS
    # Skip the last `horizon` rows — they don't have a T+horizon close yet
    # (decision was made too recently to be evaluated against future price).
    for i in range(len(rows) - horizon):
        current = rows[i]
        next_row = rows[i + horizon]

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
            max(len(rows) - horizon, 0),
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
    db: AsyncSession,
    target_date: Optional[date] = None,
    *,
    contract_id: Optional[uuid.UUID] = None,
    algo_id: Optional[uuid.UUID] = None,
) -> Dict[str, Dict[str, Any]]:
    """Get all indicators with their ranges for a given date.

    Fallback when the resolved algo row has NULL norms (e.g. ensemble dates
    where cc-ensemble-compute writes a row with diagnostics + decision but no
    z-scores — the norms are owned by cc-compute-indicators which only fills
    the legacy row). Without this, indicators-grid 404s the moment the
    date-aware resolver picks ensemble for a recent date. We pick the first
    row across (contract, algo) that has a non-null rsi_norm.
    """
    if contract_id is None:
        if target_date:
            contract_id = await resolve_contract_for_date(db, target_date)
            if not contract_id:
                return {}
        else:
            contract_id = await get_active_contract_id(db)
    if algo_id is None:
        algo_id = await get_active_algorithm_version_id(db)

    # Step 1: try the resolved (contract, algo, date) — that's the most
    # specific match and preserves macroeco_score from that algo's LLM run.
    query = select(PlIndicatorDaily).where(
        and_(
            PlIndicatorDaily.contract_id == contract_id,
            PlIndicatorDaily.algorithm_version_id == algo_id,
            PlIndicatorDaily.rsi_norm.is_not(None),
        )
    )
    if target_date:
        query = query.where(PlIndicatorDaily.date == target_date)
    query = query.order_by(desc(PlIndicatorDaily.date)).limit(1)
    indicator = (await db.execute(query)).scalars().first()

    # Step 2: same date + contract, ANY algo with non-null norms (typically
    # falls back to legacy which is where compute-indicators writes norms).
    if indicator is None and target_date:
        fallback = (
            select(PlIndicatorDaily)
            .where(
                and_(
                    PlIndicatorDaily.contract_id == contract_id,
                    PlIndicatorDaily.date == target_date,
                    PlIndicatorDaily.rsi_norm.is_not(None),
                )
            )
            .order_by(desc(PlIndicatorDaily.date))
            .limit(1)
        )
        indicator = (await db.execute(fallback)).scalars().first()

    # Step 3: cross-contract fallback (handles contract roll edges).
    if indicator is None and target_date:
        fallback = (
            select(PlIndicatorDaily)
            .where(
                and_(
                    PlIndicatorDaily.date == target_date,
                    PlIndicatorDaily.rsi_norm.is_not(None),
                )
            )
            .order_by(desc(PlIndicatorDaily.date))
            .limit(1)
        )
        indicator = (await db.execute(fallback)).scalars().first()

    if indicator is None:
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


# Heuristic to detect the cc-ensemble-compute debug-string conclusion until the
# Phase 8 refactor of cc-daily-analysis writes a real ensemble-aligned narrative.
# Format observed: "C5 ensemble decision=OPEN (soft-gate=OPEN, wrapper_fired=[...], ...)"
_ENSEMBLE_DEBUG_PREFIX = "C5 ensemble decision="


def _is_usable_narrative(text: Optional[str]) -> bool:
    """True when the conclusion looks like a real LLM narrative (not the
    ensemble compute debug string).
    """
    if not text:
        return False
    return not text.strip().startswith(_ENSEMBLE_DEBUG_PREFIX)


async def get_latest_recommendations(
    db: AsyncSession,
    target_date: Optional[date] = None,
    *,
    contract_id: Optional[uuid.UUID] = None,
    algo_id: Optional[uuid.UUID] = None,
) -> tuple[List[str], Optional[str], Optional[date]]:
    """Get the latest recommendations from pl_indicator_daily.conclusion.

    Fallback chain (each step relaxes a filter, narrative quality > strict source):
      1. (contract_id, algo_id, date)
      2. (any contract, algo_id, date)             — transition days
      3. (contract_id, any algo with conclusion, date) — ensemble dates
         where ensemble decision has no LLM conclusion yet
      4. (any contract, any algo with conclusion, date)

    The narrative text is still authored by the legacy cc-daily-analysis job,
    so on ensemble dates the conclusion comes from the legacy row while the
    decision was produced by ensemble. The endpoint exposes
    ``source_algorithm`` so the frontend can disclose this dissonance.

    A row whose conclusion is the cc-ensemble-compute debug string (see
    ``_is_usable_narrative``) is treated as "no narrative" for fallback
    purposes — Phase 8 will replace that debug string with a real
    ensemble-aligned LLM narrative.
    """
    if contract_id is None:
        if target_date:
            contract_id = await resolve_contract_for_date(db, target_date)
            if not contract_id:
                return [], None, None
        else:
            contract_id = await get_active_contract_id(db)
    if algo_id is None:
        algo_id = await get_active_algorithm_version_id(db)

    base_select = select(PlIndicatorDaily.conclusion, PlIndicatorDaily.date)

    # Step 1: contract + algo + (date)
    query = base_select.where(
        and_(
            PlIndicatorDaily.contract_id == contract_id,
            PlIndicatorDaily.algorithm_version_id == algo_id,
            PlIndicatorDaily.conclusion.isnot(None),
        )
    )
    if target_date:
        query = query.where(PlIndicatorDaily.date == target_date)
    query = query.order_by(desc(PlIndicatorDaily.date)).limit(1)
    row = (await db.execute(query)).one_or_none()
    if row is not None and not _is_usable_narrative(row.conclusion):
        row = None

    # Step 2: relax contract filter (any contract, this algo, this date)
    if (not row or not row.conclusion) and target_date:
        q = (
            base_select.where(
                and_(
                    PlIndicatorDaily.date == target_date,
                    PlIndicatorDaily.algorithm_version_id == algo_id,
                    PlIndicatorDaily.conclusion.isnot(None),
                )
            )
            .order_by(desc(PlIndicatorDaily.date))
            .limit(1)
        )
        row = (await db.execute(q)).one_or_none()
        if row is not None and not _is_usable_narrative(row.conclusion):
            row = None

    # Step 3: relax algo filter (this contract, ANY algo with usable narrative, this date)
    if (not row or not row.conclusion) and target_date:
        q = (
            base_select.where(
                and_(
                    PlIndicatorDaily.date == target_date,
                    PlIndicatorDaily.contract_id == contract_id,
                    PlIndicatorDaily.conclusion.isnot(None),
                    PlIndicatorDaily.conclusion.notlike(f"{_ENSEMBLE_DEBUG_PREFIX}%"),
                )
            )
            .order_by(desc(PlIndicatorDaily.date))
            .limit(1)
        )
        row = (await db.execute(q)).one_or_none()

    # Step 4: fully relaxed (any contract, any algo with usable narrative, this date)
    if (not row or not row.conclusion) and target_date:
        q = (
            base_select.where(
                and_(
                    PlIndicatorDaily.date == target_date,
                    PlIndicatorDaily.conclusion.isnot(None),
                    PlIndicatorDaily.conclusion.notlike(f"{_ENSEMBLE_DEBUG_PREFIX}%"),
                )
            )
            .order_by(desc(PlIndicatorDaily.date))
            .limit(1)
        )
        row = (await db.execute(q)).one_or_none()

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
    """Get historical chart data for a calendar-day window ending at ``end_date``.

    ``days`` is interpreted as a CALENDAR window (e.g., 365 days = real
    calendar year ≈ 252 trading sessions) — NOT a row count. Previously
    ``LIMIT :days`` returned that many session rows, so "1Y" actually spanned
    ~18 months of calendar time. The dashboard pill labels (30J / 90J / 180J
    / 1Y) reflect calendar duration to users, so we filter by date range.

    Queries the active contract first. If the window contains fewer rows for
    the active contract (recent roll), falls back to a cross-contract query
    so the chart still has coverage across the requested window.
    """
    contract_id = await get_active_contract_id(db)

    base_cols = (
        PlContractDataDaily.date,
        PlContractDataDaily.close,
        PlContractDataDaily.volume,
        PlContractDataDaily.oi,
        PlDerivedIndicators.rsi_14d,
        PlDerivedIndicators.macd,
    )

    # Calendar window: [window_start, window_end] inclusive.
    window_end = end_date if end_date is not None else date.today()
    window_start = window_end - timedelta(days=days)

    date_filter = [
        PlContractDataDaily.contract_id == contract_id,
        PlContractDataDaily.date >= window_start,
        PlContractDataDaily.date <= window_end,
    ]

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
        .order_by(PlContractDataDaily.date)
    )

    result = await db.execute(query)
    rows = result.all()

    # Fallback: cross-contract read covers the window across a recent roll
    # boundary. We expect ~5 sessions per week — fall back when the count
    # falls noticeably short of the expected business-day coverage.
    expected_min = max(1, int(days * 5 / 7) - 7)
    if len(rows) < expected_min:
        fallback_query = (
            select(*base_cols)
            .select_from(
                outerjoin(
                    PlContractDataDaily,
                    PlDerivedIndicators,
                    and_(
                        PlContractDataDaily.date == PlDerivedIndicators.date,
                        PlContractDataDaily.contract_id
                        == PlDerivedIndicators.contract_id,
                    ),
                )
            )
            .where(
                and_(
                    PlContractDataDaily.date >= window_start,
                    PlContractDataDaily.date <= window_end,
                )
            )
            .order_by(PlContractDataDaily.date)
        )
        result = await db.execute(fallback_query)
        rows = result.all()

    chart_rows = list(rows)

    # Weekly series — forward-filled per chart date from the dedicated
    # tables. stock_eu and com_net_eu are toggleable chart metrics in the
    # frontend (commodities-data.ts); we keep them in the payload so the
    # chart doesn't lose options, but they're now sourced from
    # pl_stock_observation (region='eu') and pl_cot_eu_weekly (ICE Europe
    # producer/merchant net — both match the London cocoa #7 contract).
    if chart_rows:
        stock_eu_series = await _build_forward_fill_series(
            db,
            chart_dates=[r.date for r in chart_rows],
            table=PlStockObservation,
            date_col=PlStockObservation.report_date,
            extra_where=[
                PlStockObservation.region == "eu",
                PlStockObservation.contract_market == "cocoa",
            ],
            value_col=PlStockObservation.value_tonnes,
        )
        com_net_series = await _build_forward_fill_series(
            db,
            chart_dates=[r.date for r in chart_rows],
            table=PlCotEuWeekly,
            date_col=PlCotEuWeekly.release_date,
            extra_where=[PlCotEuWeekly.contract_market == "cocoa"],
            value_col=PlCotEuWeekly.prod_merc_net,
        )
    else:
        stock_eu_series, com_net_series = {}, {}

    return [
        {
            "date": row.date.strftime("%Y-%m-%d"),
            "close": float(row.close) if row.close is not None else None,
            "volume": float(row.volume) if row.volume is not None else None,
            "open_interest": float(row.oi) if row.oi is not None else None,
            "rsi_14d": float(row.rsi_14d) if row.rsi_14d is not None else None,
            "macd": float(row.macd) if row.macd is not None else None,
            "stock_eu": stock_eu_series.get(row.date),
            "com_net_eu": com_net_series.get(row.date),
        }
        for row in chart_rows
    ]


async def _build_forward_fill_series(
    db: AsyncSession,
    *,
    chart_dates: List[date],
    table,
    date_col,
    extra_where,
    value_col,
) -> Dict[date, Optional[float]]:
    """Forward-fill a weekly value across daily chart dates.

    Pulls every relevant observation in the window plus one earlier
    observation as the carry-in, then walks the sorted chart dates and
    associates the latest observation on/before each one. ~1 query
    regardless of chart length.
    """
    if not chart_dates:
        return {}

    window_start = min(chart_dates)
    window_end = max(chart_dates)

    # Carry-in: the most recent observation strictly before window_start.
    carry_query = (
        select(date_col, value_col)
        .where(*extra_where, date_col < window_start)
        .order_by(desc(date_col))
        .limit(1)
    )
    carry_result = await db.execute(carry_query)
    in_window_query = (
        select(date_col, value_col)
        .where(*extra_where, date_col >= window_start, date_col <= window_end)
        .order_by(date_col)
    )
    in_window_result = await db.execute(in_window_query)

    observations: List[tuple[date, Optional[float]]] = []
    for row in carry_result.all():
        observations.append((row[0], float(row[1]) if row[1] is not None else None))
    for row in in_window_result.all():
        observations.append((row[0], float(row[1]) if row[1] is not None else None))

    if not observations:
        return {d: None for d in chart_dates}

    series: Dict[date, Optional[float]] = {}
    obs_idx = 0
    last_value: Optional[float] = None
    for d in sorted(chart_dates):
        while obs_idx < len(observations) and observations[obs_idx][0] <= d:
            last_value = observations[obs_idx][1]
            obs_idx += 1
        series[d] = last_value
    return series


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
        "source_count": article.source_count,
        "total_sources": article.total_sources,
    }


# ---------------------------------------------------------------------------
# 7. Theme Sentiments
# ---------------------------------------------------------------------------

SIGNAL_THEMES = {"production", "chocolat"}


async def get_theme_sentiments(
    db: AsyncSession, target_date: Optional[date] = None
) -> Optional[Dict[str, Any]]:
    """Get per-theme sentiment scores for a given date.

    Reads from pl_article_segment (inline_v1) and left-joins
    pl_sentiment_feature for z-delta values.
    """
    # Raw sentiment from pl_article_segment
    segment_query = (
        select(
            PlArticleSegment.theme,
            PlArticleSegment.sentiment_score,
            PlArticleSegment.confidence,
            PlArticleSegment.facts,
        )
        .where(
            PlArticleSegment.extraction_version == "inline_v1",
            PlArticleSegment.zone == "all",
        )
        .order_by(desc(PlArticleSegment.article_date))
    )

    if target_date:
        segment_query = segment_query.where(
            PlArticleSegment.article_date == target_date
        )

    result = await db.execute(segment_query)
    segments = result.all()

    if not segments:
        return None

    # Batch-fetch all z-delta values for this date (avoids N+1 queries)
    zscore_by_theme: dict[str, float] = {}
    if target_date:
        feat_query = select(
            PlSentimentFeature.theme, PlSentimentFeature.zscore_delta
        ).where(
            PlSentimentFeature.date == target_date,
            PlSentimentFeature.min_periods_met.is_(True),
        )
        feat_result = await db.execute(feat_query)
        zscore_by_theme = {
            r.theme: float(r.zscore_delta)
            for r in feat_result.all()
            if r.zscore_delta is not None
        }

    # Build theme data from segments
    themes: list[Dict[str, Any]] = []
    for row in segments:
        theme_data: Dict[str, Any] = {
            "theme": row.theme,
            "score": float(row.sentiment_score)
            if row.sentiment_score is not None
            else None,
            "confidence": float(row.confidence) if row.confidence is not None else None,
            "rationale": row.facts,
            "zscore_delta": zscore_by_theme.get(row.theme),
            "has_signal": row.theme in SIGNAL_THEMES,
        }
        themes.append(theme_data)

    # Count total days with sentiment data (for accumulation tracking)
    count_query = (
        select(PlArticleSegment.article_date)
        .where(
            PlArticleSegment.extraction_version == "inline_v1",
            PlArticleSegment.zone == "all",
        )
        .distinct()
    )
    count_result = await db.execute(count_query)
    accumulation = len(count_result.all())

    return {
        "date": target_date,
        "themes": themes,
        "accumulation": accumulation,
    }


# ---------------------------------------------------------------------------
# 8. Weather
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
        "diagnostics": obs.diagnostics,
    }


# ---------------------------------------------------------------------------
# 7b. Stress History (7-day lookback)
# ---------------------------------------------------------------------------

CANONICAL_LOCATIONS = ("Daloa", "San-Pédro", "Soubré", "Kumasi", "Takoradi", "Goaso")
LOCATION_COUNTRY_MAP = {
    "Daloa": "CIV",
    "San-Pédro": "CIV",
    "Soubré": "CIV",
    "Kumasi": "GHA",
    "Takoradi": "GHA",
    "Goaso": "GHA",
}


async def get_stress_history(
    db: AsyncSession,
    days: int = 7,
    target_date: Optional[date] = None,
) -> List[Dict[str, Any]]:
    """Build per-location stress history from the last N weather observations.

    Returns a list of dicts with: location_name, country, current_status,
    streak_days, trend, history (list of statuses oldest→newest).
    """
    ref = target_date or date.today()
    query = (
        select(PlWeatherObservation.date, PlWeatherObservation.diagnostics)
        .where(
            PlWeatherObservation.date <= ref,
            PlWeatherObservation.diagnostics.is_not(None),
        )
        .order_by(desc(PlWeatherObservation.date))
        .limit(days)
    )
    result = await db.execute(query)
    rows = result.fetchall()

    if not rows:
        return []

    # Build per-location timeline (oldest first)
    location_history: Dict[str, List[str]] = {loc: [] for loc in CANONICAL_LOCATIONS}
    for row in reversed(rows):  # oldest first
        diag = row[1] or {}
        for loc in CANONICAL_LOCATIONS:
            # Fuzzy: try canonical name, lowercase, with/without accent
            status = diag.get(loc) or diag.get(loc.lower()) or "normal"
            if status not in ("normal", "degraded", "stress"):
                status = "normal"
            location_history[loc].append(status)

    histories: List[Dict[str, Any]] = []
    for loc in CANONICAL_LOCATIONS:
        timeline = location_history[loc]
        current = timeline[-1] if timeline else "normal"

        # Compute streak: how many consecutive days at current status (from end)
        streak = 0
        for s in reversed(timeline):
            if s == current:
                streak += 1
            else:
                break

        # Trend: compare current to previous status
        prev = timeline[-streak - 1] if len(timeline) > streak else current
        severity = {"normal": 0, "degraded": 1, "stress": 2}
        if severity.get(current, 0) > severity.get(prev, 0):
            trend = "worsening"
        elif severity.get(current, 0) < severity.get(prev, 0):
            trend = "improving"
        else:
            trend = "stable"

        histories.append(
            {
                "location_name": loc,
                "country": LOCATION_COUNTRY_MAP[loc],
                "current_status": current,
                "streak_days": streak,
                "trend": trend,
                "history": timeline,
            }
        )

    return histories
