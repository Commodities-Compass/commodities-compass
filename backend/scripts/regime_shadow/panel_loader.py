"""Slice the per-date DecideRequest panel out of the self-computed feature chain.

The features come from ``feature_engine.build_selfcomputed_features`` (roll-neutralized,
computed over the full front-month chain, never touching pl_derived_indicators). Here
we cut the trailing window ending on ``end_date`` that ``RegimePipeline.decide`` needs:
``date`` + the 9 passthrough columns, >= 60 rows so the router's trend60/vol20 windows
are well-defined.
"""

from __future__ import annotations

import logging
from datetime import date as date_cls

import pandas as pd
from typing import cast

from regime.config import DERIVED_PASSTHROUGH

logger = logging.getLogger(__name__)

# The router needs trend60 (60-row window); require >= 60 trailing rows before today.
MIN_TRAILING_ROWS = 61
# Rows to carry into the DecideRequest. The router's trend/vol are base-invariant
# over the window, so any size >= MIN_TRAILING_ROWS yields the same decision; 150
# is a comfortable margin.
WINDOW_ROWS = 150


class RegimePanelError(RuntimeError):
    """Raised when the target date is absent or the trailing window is too short."""


def slice_panel(
    features: pd.DataFrame,
    end_date: date_cls,
    *,
    min_rows: int = MIN_TRAILING_ROWS,
    window_rows: int = WINDOW_ROWS,
) -> tuple[pd.DataFrame, str]:
    """Return ``(panel, front_month_contract_id)`` for the window ending ``end_date``.

    ``panel`` carries ``date`` + the 9 passthrough columns, one row per session.
    ``front_month_contract_id`` is the contract front-month on ``end_date`` (the FK
    for the shadow row).
    """
    ts = pd.Timestamp(end_date)
    hist = features[features["date"] <= ts]
    if hist.empty or hist["date"].max() != ts:
        latest = None if hist.empty else hist["date"].max().date()
        raise RegimePanelError(
            f"target end_date {end_date} not in the self-computed chain "
            f"(latest available {latest})"
        )

    hist = cast(pd.DataFrame, hist)
    contract_id = str(hist.loc[hist["date"].idxmax(), "contract_id"])
    panel = cast(
        pd.DataFrame,
        hist[["date", *DERIVED_PASSTHROUGH]].tail(window_rows).reset_index(drop=True),
    )
    if len(panel) < min_rows:
        raise RegimePanelError(
            f"window ending {end_date} has {len(panel)} rows < {min_rows} required "
            "for the router's trend60/vol20"
        )
    return panel, contract_id
