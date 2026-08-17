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
    GROWTH_FLOOR_TONNES,
    ExporterFlow,
    exporter_flow,
    equivalent_period_delta,
    previous_season,
    PERIMETER_ALL,
    PERIMETER_GEPEX,
    MonthlyOriginSeries,
    compute_season_balance,
    confront_statser,
    cumulative_balance,
    monthly_balance,
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


async def get_destinations(
    db: AsyncSession, season: str | None = None
) -> dict[str, Any]:
    """Where the origin's cocoa actually goes — by destination and by port.

    **Aggregated only.** The cube carries an exporter dimension on the same rows,
    but naming who shipped to whom is `read:watchai:nominative`, a key the tiers
    reaching this view do not necessarily hold. Every query here collapses the
    exporter dimension away before returning.

    Each line is compared against **the same months** a year earlier, not against
    the previous season in full: on a 10-month season the full-season comparison
    understates every destination by two months and reads as a collapse.
    """
    batch_id, data_as_of = await _current_batch(db)
    seasons = await _available_seasons(db, batch_id)
    selected = _resolve_season(season, seasons)

    destinations = await _ranked_breakdown(db, batch_id, selected, "destination")
    ports = await _ranked_breakdown(db, batch_id, selected, "port")

    return {
        "data_as_of": data_as_of,
        "season": selected,
        "available_seasons": seasons,
        "previous_season": previous_season(selected),
        "destinations": destinations,
        "ports": ports,
        "concentration": _concentration(destinations),
    }


async def get_exporters(db: AsyncSession, season: str | None = None) -> dict[str, Any]:
    """Named exporter flows and each one's apparent balance — `:nominative` only.

    This is the one view that names operators, which is why it is the most tightly
    gated row of block ②. Everything else in Section VI collapses the exporter
    dimension away precisely so it can be sold separately.

    The movers lists are computed here rather than left to the UI: the 250 t floor
    (business-rules §8) is an editorial threshold, and two consumers applying it
    differently would publish two different podiums from one dataset.
    """
    batch_id, data_as_of = await _current_batch(db)
    seasons = await _available_seasons(db, batch_id)
    selected = _resolve_season(season, seasons)
    previous = previous_season(selected)

    exports = await _exports_by_exporter(db, batch_id, selected)
    prior = await _exports_by_exporter(db, batch_id, previous)
    purchases = await _purchases_by_exporter(db, batch_id, selected)

    flows = [
        exporter_flow(
            exporter=name,
            is_gepex_member=gepex,
            exports_beans_t=beans,
            exports_transformed_t=transformed,
            purchases_t=purchases.get(name, 0.0),
            previous_exports_t=sum(prior.get(name, (0.0, 0.0, False))[:2]),
        )
        for name, (beans, transformed, gepex) in exports.items()
    ]
    flows.sort(key=lambda f: f.exports_beans_t + f.exports_transformed_t, reverse=True)

    return {
        "data_as_of": data_as_of,
        "season": selected,
        "available_seasons": seasons,
        "previous_season": previous,
        "growth_floor_tonnes": GROWTH_FLOOR_TONNES,
        "exporters": [_exporter_row(f) for f in flows],
        "movers": _movers(flows),
    }


async def get_benchmark(
    db: AsyncSession, exporter_entity_id: uuid.UUID | None, season: str | None = None
) -> dict[str, Any]:
    """ "Vos flux vs marché" — one exporter measured against the whole origin.

    Net-new: WatchAI has no per-tenant view at all, its GEPEX toggle is a global
    filter rather than an identity. The identity is read from
    ``tenant_account.exporter_entity_id`` and applied **at read time**; it is never
    a column on the cube, which stays tenant-free ("pipelines shared, tenants
    subscribe").

    ``applicable=False`` is the answer for an account with no exporter identity —
    Signal+ and Origin Desk have none by nature, and a freshly created account has
    none yet. The matrix distinguishes *not sold* (`—`, a 403) from *meaningless*
    (`n/a`), and this endpoint has to as well: returning an empty book to a
    consultancy would read as "you shipped nothing".
    """
    batch_id, data_as_of = await _current_batch(db)
    seasons = await _available_seasons(db, batch_id)
    selected = _resolve_season(season, seasons)

    base = {
        "data_as_of": data_as_of,
        "season": selected,
        "available_seasons": seasons,
        "previous_season": previous_season(selected),
    }
    if exporter_entity_id is None:
        return {**base, "applicable": False, "exporter": None, "position": None}

    identity = await _exporter_identity(db, exporter_entity_id)
    if identity is None:
        # The account is mapped to an entity the current batch does not know —
        # ref_origin_entity is rebuilt on every sync. Loud "not applicable" beats
        # a zeroed book that reads as "you shipped nothing".
        return {**base, "applicable": False, "exporter": None, "position": None}

    return {
        **base,
        "applicable": True,
        "exporter": identity,
        "position": await _benchmark_position(db, batch_id, selected, identity),
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
    """One month, with its bean-equivalent balance already computed.

    ``balance_t`` is served rather than left to the client: it is the same
    ``÷ RENDEMENT_BROYAGE`` arithmetic as the season balance, and a consumer
    re-deriving it would be a second implementation free to drift from this one
    (.claude/rules/pipeline-continuity.md — the writer receives, it does not
    recompute). A single month may legitimately be negative: off-season shipments
    draw on stock bought earlier.
    """
    return {
        "period": row.period,
        "purchases_t": row.purchases_t,
        "exports_beans_t": row.exports_beans_t,
        "exports_transformed_t": row.exports_transformed_t,
        "exports_total_t": row.exports_total_t,
        "grinding_declared_t": row.grinding_declared_t,
        "grinding_derived_t": monthly_balance(row).grinding_derived_t,
        "balance_t": monthly_balance(row).balance_t,
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


async def _breakdown_by_month(
    db: AsyncSession, batch_id: uuid.UUID, seasons: tuple[str, str], dimension: str
) -> dict[str, dict[date, float]]:
    """``{label: {month: tonnes}}`` for one dimension, over two seasons at once.

    One query for both seasons because the equivalent-period comparison needs
    them side by side; the season is not part of the returned key, since the
    month already carries the year.

    The join onto ``ref_origin_entity`` is on its primary key, so it cannot fan
    out — and this feeds a *sum*, not a rolling computation, so even a fan-out
    would give a wrong total rather than the silent corruption the
    timeseries-uniqueness rule guards against. Stated because that rule makes
    every join in this file worth a sentence.
    """
    label = {
        "destination": "COALESCE(e.canonical_name, 'INCONNUE')",
        "port": "f.port",
    }[dimension]
    join = (
        "LEFT JOIN ref_origin_entity e ON e.id = f.destination_entity_id"
        if dimension == "destination"
        else ""
    )
    rows = await db.execute(
        text(
            f"""
            SELECT {label} AS label, f.period_date, SUM(f.export_tonnes)
              FROM pl_origin_flow_monthly f
              {join}
             WHERE f.ingest_batch_id = :b AND f.season IN (:current, :previous)
             GROUP BY 1, 2
            """
        ),
        {"b": batch_id, "current": seasons[0], "previous": seasons[1]},
    )
    out: dict[str, dict[date, float]] = {}
    for label_value, period, tonnes in rows:
        out.setdefault(label_value, {})[period] = float(tonnes)
    return out


async def _ranked_breakdown(
    db: AsyncSession, batch_id: uuid.UUID, season: str, dimension: str
) -> list[dict[str, Any]]:
    """One line per destination (or port), ranked, each on its own window."""
    previous = previous_season(season)
    by_month = await _breakdown_by_month(db, batch_id, (season, previous), dimension)

    lines = []
    for label, months in by_month.items():
        # A line's window is the months IT shipped in this season — a destination
        # that stopped in March is compared over those months, not the full span.
        current = {p: t for p, t in months.items() if _season_of(p) == season}
        if not current:
            continue
        prior = {p: t for p, t in months.items() if _season_of(p) == previous}
        current_t, previous_t, delta_pct, window = equivalent_period_delta(
            current, prior
        )
        lines.append(
            {
                "label": label,
                "export_tonnes": current_t,
                "previous_tonnes": previous_t,
                "delta_pct": delta_pct,
                "window": _window(window),
                "share_pct": None,  # filled once the total is known
            }
        )
    total = sum(line["export_tonnes"] for line in lines)
    for line in lines:
        line["share_pct"] = line["export_tonnes"] / total * 100 if total > 0 else None
    return sorted(lines, key=lambda line: line["export_tonnes"], reverse=True)


def _season_of(period: date) -> str:
    """Oct→Sep. October opens the season that carries that calendar year."""
    start = period.year if period.month >= 10 else period.year - 1
    return f"{start}-{start + 1}"


def _concentration(destinations: list[dict[str, Any]]) -> dict[str, Any]:
    """How few buyers the origin depends on.

    An exporter reads this as counterparty risk, which is why it is served rather
    than left to the client: "top 3 = 49 %" is the sentence, and computing it in
    the UI would let two consumers disagree about what "top" means.
    """
    total = sum(line["export_tonnes"] for line in destinations)
    if total <= 0:
        return {"top1_share_pct": None, "top3_share_pct": None, "count": 0}
    top3 = sum(line["export_tonnes"] for line in destinations[:3])
    return {
        "top1_share_pct": destinations[0]["export_tonnes"] / total * 100,
        "top3_share_pct": top3 / total * 100,
        "count": len(destinations),
    }


async def _exports_by_exporter(
    db: AsyncSession, batch_id: uuid.UUID, season: str
) -> dict[str, tuple[float, float, bool]]:
    """``{exporter: (beans_t, transformed_t, is_gepex)}`` for one season."""
    rows = await db.execute(
        text(
            """
            SELECT e.canonical_name, e.is_gepex_member,
                   SUM(f.export_tonnes) FILTER (WHERE f.is_bean_equivalent),
                   SUM(f.export_tonnes) FILTER (WHERE NOT f.is_bean_equivalent)
              FROM pl_origin_flow_monthly f
              JOIN ref_origin_entity e ON e.id = f.exporter_entity_id
             WHERE f.ingest_batch_id = :b AND f.season = :season
             GROUP BY 1, 2
            """
        ),
        {"b": batch_id, "season": season},
    )
    return {
        row[0]: (float(row[2] or 0.0), float(row[3] or 0.0), bool(row[1]))
        for row in rows
    }


async def _purchases_by_exporter(
    db: AsyncSession, batch_id: uuid.UUID, season: str
) -> dict[str, float]:
    """Purchases are already exporter x month — collapse the month away only.

    Kept a separate round trip from exports on purpose: joining exporter x product
    x month against exporter x month is exactly the fan-out shape the
    timeseries-uniqueness rule exists for, and here it would silently multiply
    every purchase figure by the number of products that exporter ships.
    """
    rows = await db.execute(
        text(
            """
            SELECT e.canonical_name, SUM(p.net_weight_kg) / 1000.0
              FROM pl_origin_purchase_monthly p
              JOIN ref_origin_entity e ON e.id = p.exporter_entity_id
             WHERE p.ingest_batch_id = :b AND p.season = :season
             GROUP BY 1
            """
        ),
        {"b": batch_id, "season": season},
    )
    return {row[0]: float(row[1]) for row in rows}


def _exporter_row(flow: ExporterFlow) -> dict[str, Any]:
    return {
        "exporter": flow.exporter,
        "is_gepex_member": flow.is_gepex_member,
        "exports_beans_t": flow.exports_beans_t,
        "exports_transformed_t": flow.exports_transformed_t,
        "exports_total_t": flow.exports_beans_t + flow.exports_transformed_t,
        "purchases_t": flow.purchases_t,
        "grinding_derived_t": flow.grinding_derived_t,
        "balance_t": flow.balance_t,
        "transformation_share_pct": flow.transformation_share_pct,
        "previous_exports_t": flow.previous_exports_t,
        "growth_pct": flow.growth_pct,
        "outflow_exceeds_purchases": flow.outflow_exceeds_purchases,
    }


def _movers(flows: list[ExporterFlow]) -> dict[str, list[dict[str, Any]]]:
    """Top 3 up and down, on the §8 rules.

    Two exclusions, both deliberate: the 250 t floor kills the meaningless
    +4 000 % off a 2 t base, and an exporter who shipped **nothing** this season is
    kept out of the drops — otherwise operators who simply stopped monopolise the
    −100 % podium and hide the real decliners.
    """
    eligible = [f for f in flows if f.growth_pct is not None]
    risers = sorted(eligible, key=lambda f: f.growth_pct or 0.0, reverse=True)
    fallers = sorted(
        (f for f in eligible if f.exports_beans_t + f.exports_transformed_t > 0),
        key=lambda f: f.growth_pct or 0.0,
    )
    brief = lambda f: {  # noqa: E731
        "exporter": f.exporter,
        "growth_pct": f.growth_pct,
        "exports_total_t": f.exports_beans_t + f.exports_transformed_t,
        "previous_exports_t": f.previous_exports_t,
    }
    return {
        "up": [brief(f) for f in risers[:3]],
        "down": [brief(f) for f in fallers[:3]],
    }


async def _exporter_identity(db: AsyncSession, entity_id: uuid.UUID) -> str | None:
    row = (
        await db.execute(
            text(
                "SELECT canonical_name FROM ref_origin_entity "
                "WHERE id = :id AND entity_type = 'exporter'"
            ),
            {"id": entity_id},
        )
    ).one_or_none()
    return row[0] if row else None


async def _benchmark_position(
    db: AsyncSession, batch_id: uuid.UUID, season: str, exporter: str
) -> dict[str, Any]:
    """Share, rank and own destination mix for one exporter.

    Rank is computed over **every** exporter, not over a truncated top-N: being
    23rd of 102 is the information, and a list cut at 20 would report "unranked"
    for exactly the clients most likely to ask.

    The client's own destinations are theirs to see — this is the one place a
    destination is attached to a named operator, and it is that operator.
    """
    exports = await _exports_by_exporter(db, batch_id, season)
    totals = {
        name: beans + transformed for name, (beans, transformed, _) in exports.items()
    }
    market_total = sum(totals.values())
    own = totals.get(exporter, 0.0)
    ranked = sorted(totals.values(), reverse=True)
    rank = ranked.index(own) + 1 if own in ranked else None

    rows = await db.execute(
        text(
            """
            SELECT COALESCE(d.canonical_name, 'INCONNUE'), SUM(f.export_tonnes)
              FROM pl_origin_flow_monthly f
              JOIN ref_origin_entity e ON e.id = f.exporter_entity_id
              LEFT JOIN ref_origin_entity d ON d.id = f.destination_entity_id
             WHERE f.ingest_batch_id = :b AND f.season = :season
               AND e.canonical_name = :exporter
             GROUP BY 1 ORDER BY 2 DESC
            """
        ),
        {"b": batch_id, "season": season, "exporter": exporter},
    )
    own_destinations = [
        {
            "label": row[0],
            "export_tonnes": float(row[1]),
            "share_pct": float(row[1]) / own * 100 if own > 0 else None,
        }
        for row in rows
    ]
    return {
        "exports_total_t": own,
        "market_total_t": market_total,
        "market_share_pct": own / market_total * 100 if market_total > 0 else None,
        "rank": rank,
        "exporters_ranked": len(totals),
        "own_destinations": own_destinations,
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
