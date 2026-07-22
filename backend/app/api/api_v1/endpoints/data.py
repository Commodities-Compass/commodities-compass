"""Data export endpoints — CSV series download (honest bridge before the API).

``GET /v1/data/export?series=…&from=…&to=…&format=csv`` streams an
already-prepared ``pl_*`` series as an attachment. Auth-gated (any valid Auth0
user); no keys / quotas / metering yet — that's the co-construct Enterprise API.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.services.export_service import (
    available_series,
    stream_series_csv,
)
from app.utils.date_utils import parse_date_string

logger = logging.getLogger(__name__)

router = APIRouter()

_SUPPORTED_FORMATS = {"csv"}


@router.get("/export")
@limiter.limit("30/minute")
async def export_series(
    request: Request,
    series: str = Query(..., description=f"One of: {', '.join(available_series())}"),
    date_from: str = Query(..., alias="from", description="Start date (YYYY-MM-DD)"),
    date_to: str = Query(..., alias="to", description="End date (YYYY-MM-DD)"),
    format: str = Query("csv", description="Output format (csv only for now)"),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Stream a data series as CSV over an inclusive date range.

    Validates the series key, format, and date range at the boundary, then
    delegates the row streaming to ``export_service``. Fails loud (400) on any
    bad input rather than returning an empty/partial file.
    """
    if series not in available_series():
        raise HTTPException(
            status_code=400,
            detail=f"Unknown series '{series}'. Available: {available_series()}",
        )
    if format.lower() not in _SUPPORTED_FORMATS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format '{format}'. Only 'csv' is available.",
        )
    try:
        parsed_from = parse_date_string(date_from)
        parsed_to = parse_date_string(date_to)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if parsed_from > parsed_to:
        raise HTTPException(
            status_code=400,
            detail=f"'from' ({date_from}) must be on or before 'to' ({date_to}).",
        )

    filename = f"compass-{series}-{date_from}-to-{date_to}.csv"
    return StreamingResponse(
        stream_series_csv(db, series, parsed_from, parsed_to),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
