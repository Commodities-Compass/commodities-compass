"""Response models for the origin flow endpoints (matrix block ②).

Every payload carries ``data_as_of`` (decision #15): ingestion is manual, so there
is no execution log to alert on and staleness is made visible to the user instead
of alerted to ops.

Every *block* additionally carries its own ``window`` and ``perimeter``. That is
not decoration — the three sources stop at different months and the STATSER
confrontation runs on a different population than the balance, so a payload that
omitted them would invite exactly the comparison business-rules §6 forbids.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class Window(BaseModel):
    """The period range a figure actually covers."""

    from_: Optional[date] = Field(None, alias="from")
    to: Optional[date] = None
    months: int = Field(0, description="Number of months in the window")

    model_config = {"populate_by_name": True}


class MonthlyFlow(BaseModel):
    """One month of the three flows, in tonnes."""

    period: date
    purchases_t: float
    exports_beans_t: float
    exports_transformed_t: float
    exports_total_t: float
    grinding_declared_t: Optional[float] = Field(
        None,
        description="STATSER declaration. NULL means not yet published — it trails "
        "the other two sources by 2-3 months — never zero.",
    )
    grinding_derived_t: float = Field(
        description="Transformed exports converted back to bean equivalent "
        "(/ 0.80). NOT the STATSER declaration above."
    )
    balance_t: float = Field(
        description="achats − exports fèves − broyage déduit, for this month. "
        "Served rather than recomputed client-side so the arithmetic has one "
        "implementation. May be negative for a single month — off-season "
        "shipments draw on stock bought earlier."
    )


class YtdComparison(BaseModel):
    """Season-to-date for ONE source against its own N-1 window (§6).

    Never a shared window across sources: comparing grinding's 7 published months
    against exports' 10 manufactures a collapse that is purely a publication lag.
    """

    source: str = Field(description="exports | purchases | grinding")
    season: str
    previous_season: str
    window: Window
    current_t: float
    previous_t: float
    delta_pct: Optional[float] = Field(
        None, description="NULL against a zero baseline — growth off zero is undefined"
    )


class MonthSynthesis(BaseModel):
    """The four published figures for one month."""

    period: date
    exports_t: float
    purchases_t: float
    valcaf_fcfa: float
    duties_taxes_fcfa: float


class ProductMixLine(BaseModel):
    """One canonical product's share of the season's exports.

    ``is_bean_equivalent`` travels with the line so a consumer can see which
    denominator any "transformation" figure used: the published WatchAI report
    counts HORS GRADE as transformed (27,7 %), Compass counts it as a bean
    (19,9 %). Both are computable from this list; only one is labelled
    transformation.
    """

    product_code: str
    is_bean_equivalent: bool
    export_tonnes: float
    share_pct: Optional[float] = None


class StatserConfrontation(BaseModel):
    """Derived grinding vs STATSER's declaration — a consistency signal (§5).

    Both sides are computed on the GEPEX perimeter. STATSER only covers those 11
    operators, so comparing it to all-country derived grinding would blend a real
    signal with a population mismatch.
    """

    perimeter: str
    window: Window
    derived_t: float = Field(
        description="Transformed exports / 0.80, GEPEX exporters only. Caveat worth "
        "stating in the UI: a group may grind under one legal entity and export "
        "under another, so entity-level filtering can understate this side. The gap "
        "is robust to that — even taking every transformed export in the country as "
        "the numerator it stays negative — but its exact size is not."
    )
    declared_t: float
    gap_t: float = Field(description="derived − declared; either sign is informative")
    gap_pct: Optional[float] = None


class TransformationBlock(BaseModel):
    """Material balance (§4) — bean-equivalent, STATSER not an input."""

    perimeter: str
    window: Window
    purchases_t: float
    exports_beans_t: float
    exports_transformed_t: float
    exports_total_t: float
    grinding_derived_t: float = Field(
        description="Transformed exports converted back to bean equivalent "
        "(/ 0.80). Larger than the product weight by construction."
    )
    balance_t: float
    balance_pct: Optional[float] = None
    transformation_rate_pct: Optional[float] = Field(
        None,
        description="Derived grinding over PURCHASES (§4.3). NOT the transformed "
        "share of the export mix — different denominator, ~0.5 pt apart.",
    )
    outflow_rate_pct: Optional[float] = None
    stock_signal: str
    outflow_exceeds_purchases: bool = Field(
        description="More matter left than was bought over this window. A "
        "publishable state, not an error: stock carries across seasons and the "
        "purchase master covers fewer operators than customs exports (81 vs 102 "
        "on the current batch). This is why it is a solde *apparent*."
    )
    cumulative_balance_t: float
    monthly_cumulative_t: list[float]
    statser_confrontation: Optional[StatserConfrontation] = None


class OriginCampaignResponse(BaseModel):
    """`GET /v1/dashboard/origin/campaign` — the row every tier holds.

    Carries no exporter, destination or port: those are gated by other keys, and
    this endpoint is reachable by tiers that hold neither.
    """

    data_as_of: date
    season: str
    available_seasons: list[str]
    perimeter: str
    monthly: list[MonthlyFlow]
    ytd: list[YtdComparison]
    month: Optional[MonthSynthesis] = None


class OriginMarketViewsResponse(BaseModel):
    """`GET /v1/dashboard/origin/market-views` — aggregated views + transformation."""

    data_as_of: date
    season: str
    available_seasons: list[str]
    season_totals: list["SeasonTotal"]
    monthly: list[MonthlyFlow]
    product_mix: list[ProductMixLine]
    transformation: Optional[TransformationBlock] = Field(
        None,
        description="NULL for seasons before the purchase master starts (2020-10): "
        "there are exports and a product mix, but no balance to compute. Zeros "
        "would read as a measurement.",
    )


class SeasonTotal(BaseModel):
    """Season headline, for the season-comparison view."""

    season: str
    exports_t: float
    purchases_t: Optional[float] = Field(
        None, description="NULL for seasons before the purchase master starts (2020-10)"
    )


OriginMarketViewsResponse.model_rebuild()
