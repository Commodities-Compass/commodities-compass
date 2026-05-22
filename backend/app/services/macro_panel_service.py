"""Macro panel service — FX (daily) + ENSO (monthly, lagged) + ensemble macro context.

Reads:
  * ``pl_external_indicator`` for FX (business days) and ENSO (1st of month).
  * ``pl_orchestrator_decision`` for the ensemble-derived macro signal
    (``macro_direction``, ``macro_surprise``, ``macro_half_life_days``).
    These come from MacroEventLayer fed by ``pl_article_segment`` — only
    populated on ensemble dates (≥ 2025-12-15).

Lookback strategy:
  * FX: most recent row on or before the target date (ECB business-day gaps OK).
  * ENSO: most recent monthly row whose ``date + 14 days <= target_date``
    (mirrors the 14-day lag policy applied by the engine at compute-time —
    we don't precompute the lagged view here, we replicate the query).
"""

from __future__ import annotations

import logging
import uuid
from datetime import date as date_cls
from datetime import timedelta
from typing import Any, Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline import PlExternalIndicator, PlOrchestratorDecision

logger = logging.getLogger(__name__)

# ENSO publication lag — applied at query time to avoid look-ahead bias.
ENSO_LAG_DAYS = 14


async def get_macro_panel(
    db: AsyncSession,
    target_date: date_cls,
    *,
    contract_id: Optional[uuid.UUID] = None,
    algo_id: Optional[uuid.UUID] = None,
) -> dict[str, Any]:
    """Return FX + ENSO + ensemble macro context for ``target_date``.

    Caller passes ``algo_id`` resolved via the date-aware resolver — when the
    date is in ensemble range, the orchestrator row exists; otherwise the
    macro_* fields are NULL.
    """
    # FX — most recent business day on or before target_date
    fx_row = (
        await db.execute(
            select(PlExternalIndicator)
            .where(
                PlExternalIndicator.date <= target_date,
                PlExternalIndicator.fx_dxy_proxy.is_not(None),
            )
            .order_by(desc(PlExternalIndicator.date))
            .limit(1)
        )
    ).scalar_one_or_none()

    # ENSO — most recent monthly row on/before target_date - LAG_DAYS
    enso_cutoff = target_date - timedelta(days=ENSO_LAG_DAYS)
    enso_row = (
        await db.execute(
            select(PlExternalIndicator)
            .where(
                PlExternalIndicator.date <= enso_cutoff,
                PlExternalIndicator.enso_oni_month.is_not(None),
            )
            .order_by(desc(PlExternalIndicator.date))
            .limit(1)
        )
    ).scalar_one_or_none()

    # Ensemble macro context — only present on ensemble dates
    orch_query = select(
        PlOrchestratorDecision.macro_direction,
        PlOrchestratorDecision.macro_surprise,
        PlOrchestratorDecision.macro_half_life_days,
    ).where(PlOrchestratorDecision.date == target_date)
    if contract_id is not None:
        orch_query = orch_query.where(PlOrchestratorDecision.contract_id == contract_id)
    if algo_id is not None:
        orch_query = orch_query.where(
            PlOrchestratorDecision.algorithm_version_id == algo_id
        )
    orch_row = (await db.execute(orch_query.limit(1))).one_or_none()

    return {
        "date": target_date.isoformat(),
        "fx_dxy_proxy": _to_float(fx_row.fx_dxy_proxy) if fx_row else None,
        "fx_gbpusd": _to_float(fx_row.fx_gbpusd) if fx_row else None,
        "fx_eurusd": _to_float(fx_row.fx_eurusd) if fx_row else None,
        "fx_gbpeur": _to_float(fx_row.fx_gbpeur) if fx_row else None,
        "enso_oni_month": _to_float(enso_row.enso_oni_month) if enso_row else None,
        "enso_nino34_anomaly": (
            _to_float(enso_row.enso_nino34_anomaly) if enso_row else None
        ),
        "enso_reference_date": (
            enso_row.date.isoformat() if enso_row is not None else None
        ),
        "macro_direction": int(orch_row.macro_direction)
        if orch_row and orch_row.macro_direction is not None
        else None,
        "macro_surprise": _to_float(orch_row.macro_surprise) if orch_row else None,
        "macro_half_life_days": int(orch_row.macro_half_life_days)
        if orch_row and orch_row.macro_half_life_days is not None
        else None,
    }


def _to_float(v: Any) -> Optional[float]:
    """Decimal/None passthrough to float. Keeps the service responsible for casts."""
    return float(v) if v is not None else None
