"""Origin flow endpoints — matrix block ②, Côte d'Ivoire physical flows.

``GET /v1/dashboard/origin/campaign``      — held by all seven tiers
``GET /v1/dashboard/origin/market-views``  — six tiers (not Coop Essentiel)

**One key, one gate, one endpoint.** The two rows carry different entitlement
keys, and the gate is an endpoint-level ``Depends``. Serving both from a single
route would mean filtering fields inside the payload according to the keys held —
machinery that does not exist here, and where a leak is one bad conditional away.
Splitting costs nothing: the frontend caches these for 24 h.

Neither endpoint returns an exporter, a destination or a port. Those belong to
``read:watchai:nominative`` and ``read:watchai:destinations``, which the tiers
reaching these two routes do not necessarily hold.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import entitlements as ent
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.core.tenancy import (
    TenantPrincipal,
    get_current_principal,
    require_any_entitlement,
)
from app.schemas.origin import (
    OriginCampaignResponse,
    OriginBenchmarkResponse,
    OriginDestinationsResponse,
    OriginExportersResponse,
    OriginMarketViewsResponse,
)
from app.services.origin_flow_service import (
    OriginDataUnavailableError,
    get_campaign,
    get_benchmark,
    get_destinations,
    get_exporters,
    get_market_views,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_SEASON_QUERY = Query(
    None,
    description="Season label, e.g. 2025-2026 (Oct→Sep). Defaults to the newest "
    "season the current batch holds.",
    pattern=r"^\d{4}-\d{4}$",
)
_MONTH_QUERY = Query(
    None,
    description="Month for the synthesis block, YYYY-MM. Defaults to the newest "
    "month with exports.",
    pattern=r"^\d{4}-\d{2}$",
)


@router.get(
    "/campaign",
    response_model=OriginCampaignResponse,
    dependencies=[
        # Any-of: the reduced variant is a real grant, not a downgrade to deny.
        Depends(
            require_any_entitlement(ent.WATCHAI_CAMPAIGN, ent.WATCHAI_CAMPAIGN_REDUCED)
        )
    ],
)
@limiter.limit("60/minute")
async def get_origin_campaign(
    request: Request,
    season: str | None = _SEASON_QUERY,
    month: str | None = _MONTH_QUERY,
    db: AsyncSession = Depends(get_db),
) -> OriginCampaignResponse:
    """Monthly campaign point: season volumes, achats vs exports, vs N-1."""
    try:
        payload = await get_campaign(db, season=season, month=month)
    except OriginDataUnavailableError as exc:
        raise _unavailable(exc) from exc
    return OriginCampaignResponse.model_validate(payload)


@router.get(
    "/market-views",
    response_model=OriginMarketViewsResponse,
    dependencies=[Depends(require_any_entitlement(ent.WATCHAI_MARKET_VIEWS))],
)
@limiter.limit("60/minute")
async def get_origin_market_views(
    request: Request,
    season: str | None = _SEASON_QUERY,
    db: AsyncSession = Depends(get_db),
) -> OriginMarketViewsResponse:
    """Aggregated views: monthly, season comparison, product mix, transformation.

    The transformation block carries the material balance on all operators and the
    STATSER confrontation on the GEPEX perimeter — two different windows and two
    different populations, each labelled, because comparing across them is what
    business-rules §6 forbids.
    """
    try:
        payload = await get_market_views(db, season=season)
    except OriginDataUnavailableError as exc:
        raise _unavailable(exc) from exc
    return OriginMarketViewsResponse.model_validate(payload)


def _unavailable(exc: OriginDataUnavailableError) -> HTTPException:
    """503, not 404: the subsystem has no data because the manual ingestion has
    not run, which is an operational state rather than a bad request."""
    logger.warning("origin data unavailable: %s", exc)
    return HTTPException(
        status_code=503,
        detail="Origin flow data has not been loaded yet.",
    )


@router.get(
    "/destinations",
    response_model=OriginDestinationsResponse,
    dependencies=[Depends(require_any_entitlement(ent.WATCHAI_DESTINATIONS))],
    summary="Aggregated export destinations and ports",
)
async def get_origin_destinations(
    season: str | None = Query(None, description="Season label, e.g. 2025-2026"),
    db: AsyncSession = Depends(get_db),
) -> OriginDestinationsResponse:
    """Matrix block ② row "Destinations & ports agrégés" — Export Essentiel and up.

    Single gate, no any-of: unlike the campaign row there is no reduced variant of
    this view. A tier either buys the destination breakdown or does not see it.
    """
    try:
        payload = await get_destinations(db, season=season)
    except OriginDataUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return OriginDestinationsResponse.model_validate(payload)


@router.get(
    "/exporters",
    response_model=OriginExportersResponse,
    dependencies=[Depends(require_any_entitlement(ent.WATCHAI_NOMINATIVE))],
    summary="Named exporter flows and apparent balances",
)
async def get_origin_exporters(
    season: str | None = Query(None, description="Season label, e.g. 2025-2026"),
    db: AsyncSession = Depends(get_db),
) -> OriginExportersResponse:
    """Matrix block ② row "Flux nominatifs & solde apparent" — Export Premium and up.

    The tightest gate in the section: this is the only endpoint that returns an
    operator's name. A tier that reaches the campaign, the market views and the
    destinations still gets 403 here unless it bought this row specifically.
    """
    try:
        payload = await get_exporters(db, season=season)
    except OriginDataUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return OriginExportersResponse.model_validate(payload)


@router.get(
    "/benchmark",
    response_model=OriginBenchmarkResponse,
    dependencies=[Depends(require_any_entitlement(ent.WATCHAI_BENCHMARK))],
    summary="Your flows against the origin",
)
async def get_origin_benchmark(
    season: str | None = Query(None, description="Season label, e.g. 2025-2026"),
    principal: TenantPrincipal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> OriginBenchmarkResponse:
    """Matrix block ② row "Benchmark « vos flux vs marché »" — Export Premium/Pro.

    The identity comes from the **principal**, never from a query parameter: a
    client-supplied exporter id would let any Export Premium account read any
    competitor's book, which is the worst failure this codebase can produce.

    An unmapped account gets ``applicable=false`` rather than 403 — it bought the
    row, it simply has no identity yet.
    """
    try:
        payload = await get_benchmark(db, principal.exporter_entity_id, season=season)
    except OriginDataUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return OriginBenchmarkResponse.model_validate(payload)
