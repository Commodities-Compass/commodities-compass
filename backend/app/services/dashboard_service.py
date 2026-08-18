"""Dashboard business logic service.

Contains pure business logic functions for dashboard operations,
independent of FastAPI dependencies for better testability and reusability.

All queries read from pl_* tables (contract-centric).
"""

import logging
import re
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Sequence

import uuid

from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline import (
    PlArticleSegment,
    PlDashboardGauge,
    PlCotEuWeekly,
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
        algo_id = await _default_serving_algo_id(db, target_date, contract_id)

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


async def _default_serving_algo_id(
    db: AsyncSession,
    target_date: Optional[date],
    contract_id: Optional[uuid.UUID] = None,
) -> uuid.UUID:
    """Algorithm id to use when the caller did not pin one.

    The endpoints always pass the version resolved by ``_resolve_algo_for_date``;
    this is the default for direct callers (scripts, tests, ad-hoc queries). It
    resolves through the serving chain so those callers see the same algorithm
    as the dashboard instead of whatever carries ``is_active`` — that flag
    belongs to the compute layer.

    Degrades to the historical ``is_active`` lookup when no chain is configured,
    so a mis-seeded environment still answers instead of 500-ing.
    """
    from app.utils.serving_chain import NoServingVersionError, resolve_serving_version

    resolution_date = target_date or date.today()
    try:
        version_id, _ = await resolve_serving_version(
            db, resolution_date, contract_id=contract_id
        )
        return version_id
    except NoServingVersionError:
        logger.warning(
            "No serving chain configured — falling back to the is_active "
            "algorithm version. Seed pl_algorithm_version.serving_rank."
        )
        return await get_active_algorithm_version_id(db)


async def _decision_aware_front_month_series(
    db: AsyncSession, start_date: date, end_date: date
) -> Sequence[Any]:
    """Return ``(date, close, decision)`` rows for the canonical front-month
    contract per date, ordered by date ASC.

    Roll-safe series shared by the YTD walk (``calculate_ytd_performance``) and
    the ensemble diagnostics ``running_acc_5d`` (``ensemble_diagnostics_service``).
    The front-month per date comes from the canonical roll calendar
    (``ref_contract.active_from``) — the single source of truth — so it can never
    disagree with compute / the chained VIEW. The decision on that contract is
    ensemble-preferred over legacy (``:ensemble_id`` / ``:legacy_id`` pinned to
    ``language='fr'`` since the decision is language-agnostic).

    This replaces the former "highest-OI among decision-carrying contracts"
    selection, which still repicked the wrong contract on a roll (e.g. CAZ26 in
    July 2026 carried a legacy decision AND led OI, so it was scored instead of
    the operator's CAU26) — a residual of the YTD split-brain. Calendar selection
    makes that structurally impossible.
    """
    from sqlalchemy import text as sa_text

    from app.utils.serving_chain import get_serving_chain

    chain = await get_serving_chain(db)
    if not chain:
        # Nothing is ranked: no algorithm is served, so no decision can be
        # scored. Return an empty series rather than inventing a fallback —
        # a silently mis-scored YTD is worse than a visibly empty one.
        logger.error("Serving chain is empty — YTD series cannot be built")
        return []

    query = sa_text("""
        WITH front AS (
            -- calendar front-month per date (greatest active_from <= date)
            SELECT dd.date,
                   (SELECT c.id FROM ref_contract c
                     WHERE c.active_from IS NOT NULL
                       AND c.active_from <= dd.date
                     ORDER BY c.active_from DESC LIMIT 1) AS contract_id
            FROM (SELECT DISTINCT date FROM pl_contract_data_daily
                   WHERE date >= :start AND date <= :end_date
                     AND close IS NOT NULL) dd
        )
        SELECT f.date, cd.close, d.decision
        FROM front f
        JOIN pl_contract_data_daily cd
              ON cd.date = f.date AND cd.contract_id = f.contract_id
        LEFT JOIN LATERAL (
            -- The serving chain, resolved per date: first ranked name that has
            -- a row wins; within a name, the newest version wins. Identical
            -- rule to resolve_serving_version(), so the YTD scores exactly the
            -- decisions the dashboard showed.
            SELECT i.decision
            FROM pl_indicator_daily i
            JOIN pl_algorithm_version av ON av.id = i.algorithm_version_id
            WHERE i.date = f.date
              AND i.contract_id = f.contract_id
              AND i.language = 'fr'
              AND av.name = ANY(:names)
            ORDER BY array_position(:names, av.name), av.created_at DESC
            LIMIT 1
        ) d ON TRUE
        ORDER BY f.date ASC
    """)
    # Two invariants hold this query together (.claude/rules/timeseries-uniqueness):
    #  * LIMIT 1 in the LATERAL → exactly one decision per (date, contract), so
    #    the horizon-indexed scoring loop in the callers can never pair
    #    mismatched sessions;
    #  * language='fr' pin → the decision is language-agnostic (the EN row
    #    copies it), so without it every date would fan out to 2 rows once EN
    #    content exists and the YTD / running-acc figures would drift.
    # Joining on av.name (not a pinned version id) also means a go-forward-only
    # version keeps serving recent dates while its predecessor keeps the
    # historical ones — matching what the dashboard resolver does.

    result = await db.execute(
        query,
        {
            "start": start_date,
            "end_date": end_date,
            "names": list(chain),
        },
    )
    return result.all()


async def calculate_ytd_performance(
    db: AsyncSession, reference_date: Optional[date] = None
) -> float:
    """Calculate YTD performance by replicating the CONCLUSION scoring server-side.

    Date-aware decision source — uses the SAME decision that the system would
    have shipped live each day:
      * For dates with an ensemble row: ensemble's ``decision`` (which mirrors
        the orchestrator's ``decision_wrapped`` — i.e. post-Compass override).
      * For older dates: legacy decision.

    Cross-contract & roll-safe via ``_decision_aware_front_month_series``: for
    each date it scores the highest-OI contract *that carries a decision*, so
    YTD spans contract rolls without silently dropping days when OHLCV OI rolls
    ahead of the contract the decisions are written on.
    """
    if reference_date is None:
        reference_date = date.today()

    start_of_year = get_year_start_date(reference_date)
    rows = await _decision_aware_front_month_series(db, start_of_year, reference_date)

    scores: list[float] = []
    unscorable: list[str] = []
    horizon = YTD_EVAL_HORIZON_DAYS
    # Skip the last `horizon` rows — they have no T+horizon close yet (decision
    # too recent to evaluate against a future price). That's expected, not an
    # anomaly, so they're excluded from the range rather than flagged below.
    for i in range(len(rows) - horizon):
        current = rows[i]
        next_row = rows[i + horizon]

        if not current.decision:
            unscorable.append(f"{current.date} (no decision)")
            continue
        if current.close is None or next_row.close is None:
            unscorable.append(f"{current.date} (missing close)")
            continue

        score = _score_day(
            current.decision.strip().upper(),
            float(current.close),
            float(next_row.close),
        )
        if score is None:
            unscorable.append(f"{current.date} (bad label '{current.decision}')")
            continue
        scores.append(score)

    if unscorable:
        # Post-Option-B ``front_month`` only yields contracts that carry a
        # decision, so any non-scorable day inside the evaluable window is a
        # genuine anomaly (missing OHLCV close, unrecognized decision label, or
        # a roll/contract split-brain re-emerging). Log LOUD — the silent
        # `logger.warning` skip is exactly what let the freeze go unnoticed.
        logger.error(
            "YTD: %d/%d evaluable days non-scorable — %s",
            len(unscorable),
            max(len(rows) - horizon, 0),
            ", ".join(unscorable[:25]),
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
    """Get all technical gauges with their colour ranges for a given date.

    Reads ``pl_dashboard_gauge`` — the algorithm-independent gauge table fed by
    ``cc-compute-gauges``. Previously this read ``pl_indicator_daily.*_norm``,
    i.e. whichever ALGORITHM wrote that row, which forced a three-step fallback
    cascade (resolved algo → any algo on this contract → any contract) purely to
    survive the fact that only one algorithm ever filled the norms. All of that
    is gone: the gauges no longer belong to an algorithm.

    ``algo_id`` is accepted for call-signature compatibility and deliberately
    unused — no caller should have to know an algorithm to read a gauge.
    """
    _ = algo_id  # gauges are algorithm-independent by construction

    if contract_id is None:
        if target_date:
            contract_id = await resolve_contract_for_date(db, target_date)
            if not contract_id:
                return {}
        else:
            contract_id = await get_active_contract_id(db)

    gauge_query = select(PlDashboardGauge).where(
        PlDashboardGauge.contract_id == contract_id
    )
    if target_date:
        gauge_query = gauge_query.where(PlDashboardGauge.date == target_date)
    else:
        # Latest available session for this contract.
        latest = select(func.max(PlDashboardGauge.date)).where(
            PlDashboardGauge.contract_id == contract_id
        )
        gauge_query = gauge_query.where(
            PlDashboardGauge.date == latest.scalar_subquery()
        )
    gauge_rows = (await db.execute(gauge_query)).scalars().all()

    if gauge_rows:
        return await _build_indicators_from_gauges(gauge_rows, db)

    # No gauge row for this (date, contract). Legitimate before the backfill
    # covers a date, so degrade to an empty grid rather than 500 — but say so,
    # since after the backfill it means cc-compute-gauges has not run.
    logger.warning(
        "No pl_dashboard_gauge row for date=%s contract=%s — has cc-compute-gauges run?",
        target_date,
        contract_id,
    )
    return {}


# pl_dashboard_gauge.indicator_name → the keyword _build_indicators_dict expects.
# The names on the left match test_range.indicator, so the colour join stays a
# plain equality on the way out.
_GAUGE_NAME_TO_KWARG = {
    "RSI": "rsi",
    "MACD": "macd",
    "%K": "stoch_k",
    "ATR": "atr",
    "VOL_OI": "vol_oi",
}


async def _build_indicators_from_gauges(
    gauge_rows: Sequence[Any], db: AsyncSession
) -> Dict[str, Dict[str, Any]]:
    """Adapt pl_dashboard_gauge rows to the unchanged grid response shape.

    ``macroeco`` is passed as None on purpose: it was never a technical gauge —
    it is the LLM macro bonus, it is not in the frontend's INDICATOR_KEYS, and
    it is rendered nowhere. ``_build_indicators_dict`` skips None values, so it
    simply stops appearing in the payload.
    """
    values: Dict[str, Any] = {kwarg: None for kwarg in _GAUGE_NAME_TO_KWARG.values()}
    for row in gauge_rows:
        kwarg = _GAUGE_NAME_TO_KWARG.get(row.indicator_name)
        if kwarg is None:
            logger.warning(
                "Unknown gauge indicator_name %r — not in the served grid",
                row.indicator_name,
            )
            continue
        values[kwarg] = row.norm_value

    return await _build_indicators_dict(macroeco=None, db=db, **values)


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
async def get_latest_recommendations(
    db: AsyncSession,
    target_date: Optional[date] = None,
    *,
    contract_id: Optional[uuid.UUID] = None,
    algo_id: Optional[uuid.UUID] = None,
    language: str = "fr",
) -> tuple[List[str], Optional[str], Optional[date]]:
    """Narrative for the SERVED algorithm — one row, no cross-algorithm fallback.

    This used to walk a four-step cascade that progressively relaxed the
    contract filter and then the ALGORITHM filter, so a date whose served row
    had no narrative silently borrowed one from another algorithm. That was a
    workaround for a specific era: the decision came from the ensemble while
    only the legacy job authored prose.

    It is now forbidden. The served algorithm owns its narrative end to end; a
    row from any other algorithm — including one still sitting in the table
    from a retired pipeline — must never surface next to a decision it did not
    produce. If the served row has no narrative, the section is empty and the
    producing job failed loudly upstream. That is the intended outcome.

    Returns ``([], None, None)`` when nothing is available.
    """
    if contract_id is None:
        if target_date:
            contract_id = await resolve_contract_for_date(db, target_date)
            if not contract_id:
                return [], None, None
        else:
            contract_id = await get_active_contract_id(db)
    if algo_id is None:
        algo_id = await _default_serving_algo_id(db, target_date, contract_id)

    query = select(PlIndicatorDaily.conclusion, PlIndicatorDaily.date).where(
        and_(
            PlIndicatorDaily.language == language,
            PlIndicatorDaily.contract_id == contract_id,
            PlIndicatorDaily.algorithm_version_id == algo_id,
            PlIndicatorDaily.conclusion.isnot(None),
        )
    )
    if target_date:
        query = query.where(PlIndicatorDaily.date == target_date)
    query = query.order_by(desc(PlIndicatorDaily.date)).limit(1)
    row = (await db.execute(query)).one_or_none()

    if not row or not row.conclusion:
        logger.warning(
            "No narrative for the served algorithm at date=%s contract=%s "
            "language=%s — section will be empty (no cross-algorithm fallback)",
            target_date,
            contract_id,
            language,
        )
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
    from sqlalchemy import text as sa_text

    # Calendar window: [window_start, window_end] inclusive.
    window_end = end_date if end_date is not None else date.today()
    window_start = window_end - timedelta(days=days)

    # Chained front-month series so the chart spans contract rolls seamlessly.
    # ``v_contract_data_chained`` now resolves the front-month per date from the
    # canonical roll calendar (ref_contract.active_from) — one row per date =
    # the contract the operator had active that day. This replaces
    # the old active-contract filter (which dropped ALL pre-roll history the
    # moment the new contract went active) and its fragile row-count fallback
    # (which never fired for short windows — e.g. the 5-day ticker series — and,
    # once the daily back-month scrape started writing a 2nd contract per date,
    # double-counted dates). Derived indicators join on the front-month
    # contract per date. Mirrors the YTD cross-contract query above.
    chart_query = sa_text(
        """
        SELECT c.date, c.close, c.volume, c.oi, pi.rsi_14d, pi.macd
        FROM v_contract_data_chained c
        LEFT JOIN pl_derived_indicators pi
               ON pi.date = c.date AND pi.contract_id = c.contract_id
        WHERE c.date >= :start AND c.date <= :end_date
        ORDER BY c.date ASC
        """
    )
    result = await db.execute(
        chart_query, {"start": window_start, "end_date": window_end}
    )
    chart_rows = list(result.all())

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
    db: AsyncSession,
    target_date: Optional[date] = None,
    language: str = "fr",
) -> Optional[Dict[str, Any]]:
    """Get the latest active fundamental article."""
    query = (
        select(PlFundamentalArticle)
        .where(PlFundamentalArticle.is_active.is_(True))
        .where(PlFundamentalArticle.language == language)
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
    db: AsyncSession,
    target_date: Optional[date] = None,
    language: str = "fr",
) -> Optional[Dict[str, Any]]:
    """Get the latest weather observation."""
    query = (
        select(PlWeatherObservation)
        .where(PlWeatherObservation.language == language)
        .order_by(
            desc(PlWeatherObservation.date),
            desc(PlWeatherObservation.created_at),
        )
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
    language: str = "fr",
) -> List[Dict[str, Any]]:
    """Build per-location stress history from the last N weather observations.

    Returns a list of dicts with: location_name, country, current_status,
    streak_days, trend, history (list of statuses oldest→newest).

    The ``language`` filter is load-bearing: pl_weather_observation is keyed on
    ``(date, language)``, so without it the ``LIMIT days`` window spans half as
    many distinct dates once EN content exists, corrupting the per-location
    timeline. Mirrors ``get_latest_weather_data``.
    """
    ref = target_date or date.today()
    query = (
        select(PlWeatherObservation.date, PlWeatherObservation.diagnostics)
        .where(
            PlWeatherObservation.date <= ref,
            PlWeatherObservation.language == language,
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
