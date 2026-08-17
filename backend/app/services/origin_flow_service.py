"""Origin flow service — reads the cube, assembles the campaign and market views.

Serves matrix block ② rows *Point campagne mensuel* and *Vues marché agrégées*.

Three rules this module exists to hold:

* **Reads the cube only** (decision #9). ``pl_origin_export_declaration`` is
  nominative and line-level; no endpoint touches it. Purchases and grindings are
  read from their own tables because they live at coarser grains.
* **Never joins the three grains in SQL.** One query per source, merged by period
  in Python. Exports are exporter×product×destination×port×month, purchases are
  exporter×month, grinding is a single figure per month — a SQL join across them
  fans out silently, which is the class .claude/rules/timeseries-uniqueness.md
  exists to prevent.
* **No exporter, destination or port ever leaves these two endpoints.** Those are
  gated by `read:watchai:nominative` and `read:watchai:destinations`, which the
  tiers holding *campaign* and *market_views* do not necessarily own. The
  aggregations here are season / month / product only, and a test enforces it.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.origin_balance import (
    PERIMETER_ALL,
    PERIMETER_GEPEX,
    MonthlyOriginSeries,
    compute_season_balance,
    confront_statser,
    cumulative_balance,
    ytd_block,
)

logger = logging.getLogger(__name__)

SOURCE_EXPORTS = "exports"
SOURCE_PURCHASES = "purchases"
SOURCE_GRINDING = "grinding"

KG_PER_TONNE = 1000


class OriginDataUnavailableError(Exception):
    """No current ingest batch — nothing has been loaded yet.

    Distinct from "the season you asked for is empty": this means the whole
    subsystem has no data, which is an operational state (the manual
    ``watchai-sync`` has never run against this database), not a client error.
    """


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------
async def get_campaign(
    db: AsyncSession, season: str | None = None, month: str | None = None
) -> dict[str, Any]:
    """Monthly campaign point: volumes, achats vs exports, vs N-1.

    Held by all seven tiers, so it carries **no exporter-level anything** — not
    even a top-3 by growth, which would leak names to tiers that did not buy
    `read:watchai:nominative`.
    """
    batch_id, data_as_of = await _current_batch(db)
    seasons = await _available_seasons(db, batch_id)
    selected = _resolve_season(season, seasons)

    series = await _monthly_series(db, batch_id, selected)
    previous = await _monthly_series(db, batch_id, _previous_season(selected))

    return {
        "data_as_of": data_as_of,
        "season": selected,
        "available_seasons": seasons,
        "perimeter": PERIMETER_ALL,
        "monthly": [_monthly_row(row) for row in series],
        "ytd": _ytd_blocks(selected, series, previous),
        "month": await _month_synthesis(db, batch_id, _resolve_month(month, series)),
    }


async def get_market_views(
    db: AsyncSession, season: str | None = None
) -> dict[str, Any]:
    """Aggregated market views: monthly, season comparison, transformation.

    The transformation block is the material balance (business-rules §4) plus the
    STATSER confrontation (§5). Both carry their own window and perimeter, because
    they do not share either.
    """
    batch_id, data_as_of = await _current_batch(db)
    seasons = await _available_seasons(db, batch_id)
    selected = _resolve_season(season, seasons)

    series = await _monthly_series(db, batch_id, selected)
    gepex_series = await _monthly_series(db, batch_id, selected, gepex_only=True)

    return {
        "data_as_of": data_as_of,
        "season": selected,
        "available_seasons": seasons,
        "season_totals": await _season_totals(db, batch_id),
        "monthly": [_monthly_row(row) for row in series],
        "product_mix": await _product_mix(db, batch_id, selected),
        "transformation": _transformation_block(selected, series, gepex_series),
    }


# ---------------------------------------------------------------------------
# assembly (pure, on top of origin_balance)
# ---------------------------------------------------------------------------
def _transformation_block(
    season: str,
    series: list[MonthlyOriginSeries],
    gepex_series: list[MonthlyOriginSeries],
) -> dict[str, Any] | None:
    """The balance on all operators, the confrontation on GEPEX.

    Returns ``None`` when the balance window is empty — the purchase master starts
    2020-10, so every earlier season has exports and a product mix but no balance.
    Emitting zeros there would print "solde 0 t, stock constitué" as though it had
    been measured; absent is the honest answer, and the rest of the view still
    works.

    Two perimeters on purpose. The balance no longer reads STATSER, so it can and
    should cover the whole country. The confrontation *is* a check on STATSER,
    which only covers the 11 GEPEX members — so both of its sides are computed on
    those members, otherwise the gap conflates a real signal with a population
    mismatch (business-rules §4.5).
    """
    balance = compute_season_balance(season, series)
    if not balance.months:
        return None
    confrontation = confront_statser(gepex_series, perimeter=PERIMETER_GEPEX)
    running = cumulative_balance(balance.monthly)

    return {
        "perimeter": balance.perimeter,
        "window": _window(balance.months),
        "purchases_t": balance.purchases_t,
        "exports_beans_t": balance.exports_beans_t,
        "exports_transformed_t": balance.exports_transformed_t,
        "exports_total_t": balance.exports_total_t,
        "grinding_derived_t": balance.grinding_derived_t,
        "balance_t": balance.balance_t,
        "balance_pct": balance.ratios.balance_pct,
        # Over PURCHASES (§4.3) — not the transformed share of the export mix,
        # which is a different denominator and reads ~0.5 pt apart on real data.
        "transformation_rate_pct": balance.ratios.transformation_rate_pct,
        "outflow_rate_pct": balance.ratios.outflow_rate_pct,
        "stock_signal": balance.stock_signal,
        # Published, never suppressed: over the whole history one season (2021-2022)
        # exceeds 100% because the achats master covers fewer operators than
        # customs exports and stock carries across seasons. That is what makes it
        # a solde *apparent*.
        "outflow_exceeds_purchases": balance.outflow_exceeds_purchases,
        "cumulative_balance_t": running[-1] if running else 0.0,
        "monthly_cumulative_t": list(running),
        "statser_confrontation": None
        if confrontation is None
        else {
            "perimeter": confrontation.perimeter,
            "window": _window(confrontation.months),
            "derived_t": confrontation.derived_t,
            "declared_t": confrontation.declared_t,
            "gap_t": confrontation.gap_t,
            "gap_pct": confrontation.gap_pct,
        },
    }


def _ytd_blocks(
    season: str,
    series: list[MonthlyOriginSeries],
    previous: list[MonthlyOriginSeries],
) -> list[dict[str, Any]]:
    """One YTD block per source, each on its own window (business-rules §6).

    The three publications stop at different months — on the current batch,
    exports and purchases run to July while STATSER stops at April. A shared
    window would manufacture a collapse in the latest months.
    """
    extractors = {
        SOURCE_EXPORTS: lambda row: row.exports_total_t,
        SOURCE_PURCHASES: lambda row: row.purchases_t,
        SOURCE_GRINDING: lambda row: row.grinding_declared_t or 0.0,
    }
    blocks = []
    for source, value_of in extractors.items():
        block = ytd_block(
            source,
            season,
            {row.period: value_of(row) for row in series},
            {row.period: value_of(row) for row in previous},
        )
        blocks.append(
            {
                "source": block.source,
                "season": block.season,
                "previous_season": block.previous_season,
                "window": _window(block.months),
                "current_t": block.current_t,
                "previous_t": block.previous_t,
                "delta_pct": block.delta_pct,
            }
        )
    return blocks


def _monthly_row(row: MonthlyOriginSeries) -> dict[str, Any]:
    return {
        "period": row.period,
        "purchases_t": row.purchases_t,
        "exports_beans_t": row.exports_beans_t,
        "exports_transformed_t": row.exports_transformed_t,
        "exports_total_t": row.exports_total_t,
        "grinding_declared_t": row.grinding_declared_t,
    }


def _window(months: tuple[date, ...]) -> dict[str, Any]:
    """Every block states the window it covers, so a UI can never imply a full
    season it does not have."""
    return {
        "from": months[0] if months else None,
        "to": months[-1] if months else None,
        "months": len(months),
    }


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------
async def _current_batch(db: AsyncSession) -> tuple[uuid.UUID, date]:
    row = (
        await db.execute(
            text(
                "SELECT id, data_as_of FROM pl_origin_ingest_batch "
                "WHERE is_current LIMIT 1"
            )
        )
    ).one_or_none()
    if row is None:
        raise OriginDataUnavailableError(
            "no current origin batch — run `poetry run watchai-sync` first"
        )
    return row[0], row[1]


async def _available_seasons(db: AsyncSession, batch_id: uuid.UUID) -> list[str]:
    """Seasons the cube actually holds, newest first."""
    rows = await db.execute(
        text(
            "SELECT DISTINCT season FROM pl_origin_flow_monthly "
            "WHERE ingest_batch_id = :b ORDER BY season DESC"
        ),
        {"b": batch_id},
    )
    return [row[0] for row in rows]


async def _monthly_series(
    db: AsyncSession,
    batch_id: uuid.UUID,
    season: str,
    *,
    gepex_only: bool = False,
) -> list[MonthlyOriginSeries]:
    """One row per month of the season, merged from three separate queries.

    Deliberately three round trips rather than one join: the grains differ, and
    joining exporter×product×month against exporter×month against month fans out
    without any error. Merging on ``period`` in Python cannot.

    Months come back in season order — which, within a single season, is simply
    chronological (Oct→Sep never wraps inside one season label), so no special
    ordering is needed here even though the display order is never calendar order
    across seasons.
    """
    exports = await _exports_by_month(db, batch_id, season, gepex_only=gepex_only)
    purchases = await _purchases_by_month(db, batch_id, season, gepex_only=gepex_only)
    grinding = await _grinding_by_month(db, batch_id, season)

    periods = sorted(set(exports) | set(purchases) | set(grinding))
    return [
        MonthlyOriginSeries(
            period=period,
            purchases_t=purchases.get(period, 0.0),
            exports_beans_t=exports.get(period, (0.0, 0.0))[0],
            exports_transformed_t=exports.get(period, (0.0, 0.0))[1],
            # Absent means "STATSER has not published", never zero — it stops 2-3
            # months behind the other two sources.
            grinding_declared_t=grinding.get(period),
        )
        for period in periods
    ]


async def _exports_by_month(
    db: AsyncSession, batch_id: uuid.UUID, season: str, *, gepex_only: bool
) -> dict[date, tuple[float, float]]:
    """period → (beans_t, transformed_t), split on the GENERATED bean flag.

    Splitting on ``is_bean_equivalent`` rather than re-listing product codes is
    the point of that column: hors-grade is a bean (business-rules §2) and no
    query here can get that wrong.
    """
    gepex_join = (
        "JOIN ref_origin_entity e ON e.id = f.exporter_entity_id AND e.is_gepex_member"
        if gepex_only
        else ""
    )
    rows = await db.execute(
        text(
            f"""
            SELECT f.period_date,
                   COALESCE(SUM(CASE WHEN f.is_bean_equivalent
                                     THEN f.export_tonnes END), 0),
                   COALESCE(SUM(CASE WHEN NOT f.is_bean_equivalent
                                     THEN f.export_tonnes END), 0)
              FROM pl_origin_flow_monthly f
              {gepex_join}
             WHERE f.ingest_batch_id = :b AND f.season = :season
             GROUP BY f.period_date
             ORDER BY f.period_date
            """
        ),
        {"b": batch_id, "season": season},
    )
    return {row[0]: (float(row[1]), float(row[2])) for row in rows}


async def _purchases_by_month(
    db: AsyncSession, batch_id: uuid.UUID, season: str, *, gepex_only: bool
) -> dict[date, float]:
    gepex_join = (
        "JOIN ref_origin_entity e ON e.id = p.exporter_entity_id AND e.is_gepex_member"
        if gepex_only
        else ""
    )
    rows = await db.execute(
        text(
            f"""
            SELECT p.period_date, COALESCE(SUM(p.net_weight_kg), 0) / {KG_PER_TONNE}
              FROM pl_origin_purchase_monthly p
              {gepex_join}
             WHERE p.ingest_batch_id = :b AND p.season = :season
             GROUP BY p.period_date
             ORDER BY p.period_date
            """
        ),
        {"b": batch_id, "season": season},
    )
    return {row[0]: float(row[1]) for row in rows}


async def _grinding_by_month(
    db: AsyncSession, batch_id: uuid.UUID, season: str
) -> dict[date, float]:
    """STATSER grinding. Never GEPEX-filtered because it *is* a GEPEX aggregate —
    the table has no exporter dimension at all (business-rules §7)."""
    rows = await db.execute(
        text(
            "SELECT period_date, tons_ground FROM pl_origin_grinding_monthly "
            "WHERE ingest_batch_id = :b AND season = :season ORDER BY period_date"
        ),
        {"b": batch_id, "season": season},
    )
    return {row[0]: float(row[1]) for row in rows}


async def _product_mix(
    db: AsyncSession, batch_id: uuid.UUID, season: str
) -> list[dict[str, Any]]:
    """Season export tonnage per canonical product, with the bean flag attached.

    The flag travels with each line so a client can recompute either
    "transformation" figure and see which denominator it used — the published
    report's 27,7 % counts hors-grade as transformed, ours does not.
    """
    rows = await db.execute(
        text(
            """
            SELECT product_code, is_bean_equivalent, SUM(export_tonnes)
              FROM pl_origin_flow_monthly
             WHERE ingest_batch_id = :b AND season = :season
             GROUP BY product_code, is_bean_equivalent
             ORDER BY 3 DESC
            """
        ),
        {"b": batch_id, "season": season},
    )
    mix = [
        {
            "product_code": row[0],
            "is_bean_equivalent": row[1],
            "export_tonnes": float(row[2]),
        }
        for row in rows
    ]
    total = sum(item["export_tonnes"] for item in mix)
    for item in mix:
        item["share_pct"] = item["export_tonnes"] / total * 100 if total > 0 else None
    return mix


async def _season_totals(db: AsyncSession, batch_id: uuid.UUID) -> list[dict[str, Any]]:
    """Exports and purchases per season, for the season-comparison view.

    Two separate aggregates merged by season label — same no-join discipline as
    the monthly series.
    """
    export_rows = await db.execute(
        text(
            "SELECT season, SUM(export_tonnes) FROM pl_origin_flow_monthly "
            "WHERE ingest_batch_id = :b GROUP BY season"
        ),
        {"b": batch_id},
    )
    exports = {row[0]: float(row[1]) for row in export_rows}
    purchase_rows = await db.execute(
        text(
            f"SELECT season, SUM(net_weight_kg) / {KG_PER_TONNE} "
            "FROM pl_origin_purchase_monthly WHERE ingest_batch_id = :b GROUP BY season"
        ),
        {"b": batch_id},
    )
    purchases = {row[0]: float(row[1]) for row in purchase_rows}

    return [
        {
            "season": season,
            "exports_t": exports.get(season, 0.0),
            "purchases_t": purchases.get(season),
        }
        for season in sorted(set(exports) | set(purchases), reverse=True)
    ]


async def _month_synthesis(
    db: AsyncSession, batch_id: uuid.UUID, period: date | None
) -> dict[str, Any] | None:
    """The four published figures for one month: exports, achats, VALCAF, taxes.

    ``valcaf_fcfa`` sums a column that is 0 on every row before the 2023-2024
    season (131 573 of 172 712 rows on the current source). The sum is therefore
    honest, but an *average* over it would not be — that belongs to the
    stabilisation analytic, with a `> 1` filter.
    """
    if period is None:
        return None
    row = (
        await db.execute(
            text(
                """
                SELECT COALESCE(SUM(export_tonnes), 0),
                       COALESCE(SUM(valcaf), 0),
                       COALESCE(SUM(duties_taxes), 0)
                  FROM pl_origin_flow_monthly
                 WHERE ingest_batch_id = :b AND period_date = :p
                """
            ),
            {"b": batch_id, "p": period},
        )
    ).one()
    purchases = (
        await db.execute(
            text(
                f"SELECT COALESCE(SUM(net_weight_kg), 0) / {KG_PER_TONNE} "
                "FROM pl_origin_purchase_monthly "
                "WHERE ingest_batch_id = :b AND period_date = :p"
            ),
            {"b": batch_id, "p": period},
        )
    ).scalar_one()
    return {
        "period": period,
        "exports_t": float(row[0]),
        "purchases_t": float(purchases),
        "valcaf_fcfa": float(row[1]),
        "duties_taxes_fcfa": float(row[2]),
    }


# ---------------------------------------------------------------------------
# parameter resolution
# ---------------------------------------------------------------------------
def _resolve_season(requested: str | None, available: list[str]) -> str:
    """Default to the newest season the batch holds.

    An unknown season is not an error: it resolves to the newest one, because the
    caller is a season selector and a stale bookmark should show data rather than
    a 404. Empty batches raise earlier, in ``_current_batch``.
    """
    if requested and requested in available:
        return requested
    if requested:
        logger.warning(
            "season %s not in the current batch %s — falling back to newest",
            requested,
            available[:3],
        )
    return available[0] if available else ""


def _resolve_month(
    requested: str | None, series: list[MonthlyOriginSeries]
) -> date | None:
    """``YYYY-MM`` → the first of that month, defaulting to the newest month with
    exports. A month with purchases but no exports is not a synthesis candidate:
    the four published figures are all export-side except one."""
    exporting = [row.period for row in series if row.exports_total_t > 0]
    if requested:
        try:
            year, month = (int(part) for part in requested.split("-"))
            candidate = date(year, month, 1)
        except (ValueError, TypeError):
            logger.warning("unparseable month %r — falling back to newest", requested)
        else:
            if candidate in {row.period for row in series}:
                return candidate
            logger.warning("month %s not in season — falling back to newest", requested)
    return max(exporting) if exporting else None


def _previous_season(season: str) -> str:
    if not season:
        return ""
    start, end = (int(part) for part in season.split("-"))
    return f"{start - 1}-{end - 1}"
