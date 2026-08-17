"""Material balance for origin physical flows — pure arithmetic, no I/O.

Spec: `docs/watchai/business-rules.md` §4-§6.

This module is deliberately free of database and HTTP concerns: it takes monthly
tonnages in, returns computed blocks out. That is what makes the invariants below
testable without a fixture, and it is where the one bug that matters lives.

**The bug this module exists to not reproduce.** v1 computed
``(exports_all_products + grinding) / achats``. Transformed exports are the
*output* of grinding, so the same matter was counted twice: the beans had already
been consumed. It showed a `taux de sortie` of 124 % — shipping out more than was
bought — and a negative balance. Signalled 2026-07-17, fixed upstream in v2.

The fix is to convert transformed exports **back to bean equivalent** before they
enter the balance. ``grinding_derived_t`` is therefore *larger* than the product
weight it comes from — that is the point, not an error.

Two consequences of deriving grinding rather than reading STATSER:

* the balance no longer depends on a third-party source, and recovers the 2-3
  months STATSER lags by (it stops at 2026-04 while exports and purchases run to
  2026-07);
* STATSER becomes a **confrontation** instead of an input (§5) — the gap between
  derived and declared is published as a consistency signal, on STATSER's own
  window and its own GEPEX perimeter.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Final, Literal

# Grinding yield: 1 t of beans yields 0,80 t of transformed product
# (`api/app/data.py:292` on watch-ai `refonte-da-v2` @ `11336ef`).
#
# **The single constant whose silent drift would restate every balance we
# publish** — integration doc risk #1, on an actively developed upstream branch.
# On any re-sync of the spec, diff `data.py` / `saison.py` and re-run the
# reconciliation before touching this value.
#
# It lives here rather than in `scripts/watchai_sync/config.py` because this is
# the layer that consumes it, and `app/` must not import from `scripts/`.
RENDEMENT_BROYAGE: Final[float] = 0.80

# Perimeter labels carried in payloads. Any composite ratio must state which one
# it was computed on: STATSER is GEPEX-only, exports and purchases are all-CI, and
# silently mixing them is the ~3x bias business-rules §4.5 warns about.
PERIMETER_ALL = "all_operators"
PERIMETER_GEPEX = "gepex"

StockSignal = Literal["entree_stock", "sortie_stock"]
SeasonStockSignal = Literal["stock_constitue", "stock_n1_mobilise"]


@dataclass(frozen=True)
class MonthlyOriginSeries:
    """One month of the three flows. **Everything in tonnes.**

    ``grinding_declared_t`` is ``None`` where STATSER has not published yet —
    which is the normal state for the most recent 2-3 months and must not be
    read as zero.
    """

    period: date
    purchases_t: float
    exports_beans_t: float
    exports_transformed_t: float
    grinding_declared_t: float | None = None

    @property
    def exports_total_t(self) -> float:
        return self.exports_beans_t + self.exports_transformed_t


@dataclass(frozen=True)
class MonthlyBalance:
    """The balance for one month, plus the two export figures a UI may show.

    Both ``exports_beans_t`` and ``exports_total_t`` are carried so the brut/fèves
    display toggle can switch which one it prints. The toggle **cannot** change
    the balance: this dataclass takes no mode, so mode-independence (§4.4) is
    structural here rather than something a test has to police.
    """

    period: date
    purchases_t: float
    exports_beans_t: float
    exports_transformed_t: float
    grinding_derived_t: float
    balance_t: float

    @property
    def exports_total_t(self) -> float:
        return self.exports_beans_t + self.exports_transformed_t

    @property
    def signal(self) -> StockSignal:
        """A single month may legitimately go negative — off-season shipments
        draw on stock bought earlier. It is the *season* balance that cannot
        (§4.3)."""
        return "entree_stock" if self.balance_t >= 0 else "sortie_stock"


@dataclass(frozen=True)
class BalanceRatios:
    """The three derived ratios (§4.3), all over **purchases**.

    ``None`` when purchases are zero — a ratio over an empty denominator is not 0,
    it is undefined.

    ⚠️ ``transformation_rate_pct`` is grinding over **achats** and is NOT the
    transformed share of the export mix. On `11336ef` for 2025-2026 the two are
    20,4 % and 19,9 % respectively — close enough to be mistaken for each other,
    different enough that publishing one under the other's label is wrong. Both
    are legitimately called "taux de transformation" in conversation; only this one
    is the §4.3 ratio.
    """

    balance_pct: float | None
    transformation_rate_pct: float | None
    outflow_rate_pct: float | None


@dataclass(frozen=True)
class SeasonBalance:
    """Season-to-date balance over the achats ∩ exports window (§4.2)."""

    season: str
    months: tuple[date, ...]
    purchases_t: float
    exports_beans_t: float
    exports_transformed_t: float
    grinding_derived_t: float
    balance_t: float
    ratios: BalanceRatios
    monthly: tuple[MonthlyBalance, ...]
    perimeter: str = PERIMETER_ALL

    @property
    def window_from(self) -> date | None:
        return self.months[0] if self.months else None

    @property
    def window_to(self) -> date | None:
        return self.months[-1] if self.months else None

    @property
    def exports_total_t(self) -> float:
        return self.exports_beans_t + self.exports_transformed_t

    @property
    def stock_signal(self) -> SeasonStockSignal:
        return "stock_constitue" if self.balance_t >= 0 else "stock_n1_mobilise"

    @property
    def outflow_exceeds_purchases(self) -> bool:
        """More matter left than was bought over this window.

        **A publishable state, not an error.** Two structural causes, both real:
        stock carries across seasons, and the achats master covers fewer operators
        than the customs export data (on `11336ef`, 81 purchase-side vs 102
        export-side exporters in 2025-2026; in 2021-2022, 34 exporters shipping
        102 829 t never appear in achats at all). That season lands at 108 %.

        This is precisely why WatchAI calls it *solde **apparent***: numerator and
        denominator come from populations that do not coincide. Serving layers must
        surface this flag alongside the figure, never suppress the season.
        """
        return self.balance_t < 0


@dataclass(frozen=True)
class StatserConfrontation:
    """Derived vs declared grinding — a consistency signal, never an input (§5).

    Computed on the three-source intersection, because that is the only window
    where a comparison means anything, and flagged ``gepex`` because STATSER only
    ever covers those 11 operators.
    """

    months: tuple[date, ...]
    derived_t: float
    declared_t: float
    gap_t: float
    gap_pct: float | None
    perimeter: str

    @property
    def window_from(self) -> date | None:
        return self.months[0] if self.months else None

    @property
    def window_to(self) -> date | None:
        return self.months[-1] if self.months else None


@dataclass(frozen=True)
class YtdBlock:
    """One source's season-to-date total against its own N-1 equivalent (§6).

    Per source, never a shared window: the three publications stop at different
    months, so *« comparer chacune à son propre équivalent N-1 est le seul "vs an
    dernier" honnête »*. ``months`` is carried so a UI can state the window it is
    comparing rather than implying a full season.
    """

    source: str
    season: str
    previous_season: str
    months: tuple[date, ...]
    current_t: float
    previous_t: float
    delta_pct: float | None

    @property
    def window_from(self) -> date | None:
        return self.months[0] if self.months else None

    @property
    def window_to(self) -> date | None:
        return self.months[-1] if self.months else None

    @property
    def month_count(self) -> int:
        return len(self.months)


# ---------------------------------------------------------------------------
# core arithmetic
# ---------------------------------------------------------------------------
def derive_grinding(exports_transformed_t: float) -> float:
    """Bean equivalent of a transformed-product weight (§4.1).

    ``1 t`` of beans yields ``RENDEMENT_BROYAGE`` tonnes of product, so recovering
    the bean input means dividing, and the result is deliberately **larger** than
    the input weight.
    """
    return exports_transformed_t / RENDEMENT_BROYAGE


def monthly_balance(series: MonthlyOriginSeries) -> MonthlyBalance:
    """``achats − exports_fèves − (exports_transformés / rendement)``.

    Note what is *not* here: STATSER's declared grinding. Adding it would
    double-count, because the transformed exports already stand for it.
    """
    grinding_derived_t = derive_grinding(series.exports_transformed_t)
    return MonthlyBalance(
        period=series.period,
        purchases_t=series.purchases_t,
        exports_beans_t=series.exports_beans_t,
        exports_transformed_t=series.exports_transformed_t,
        grinding_derived_t=grinding_derived_t,
        balance_t=series.purchases_t - series.exports_beans_t - grinding_derived_t,
    )


def compute_ratios(
    purchases_t: float,
    exports_beans_t: float,
    grinding_derived_t: float,
    balance_t: float,
) -> BalanceRatios:
    """The three ratios of §4.3, all over purchases."""
    if purchases_t <= 0:
        return BalanceRatios(None, None, None)
    return BalanceRatios(
        balance_pct=balance_t / purchases_t * 100,
        transformation_rate_pct=grinding_derived_t / purchases_t * 100,
        outflow_rate_pct=(exports_beans_t + grinding_derived_t) / purchases_t * 100,
    )


def balance_window(series: list[MonthlyOriginSeries]) -> tuple[date, ...]:
    """Months where **both** purchases and exports are present (§4.2).

    Explicitly *not* the three-source intersection: grinding is derived, so
    STATSER's publication lag no longer truncates the balance. A month with
    purchases but no exports (or the reverse) is excluded — a one-sided month
    would look like a huge surplus or deficit that is really just missing data.
    """
    return tuple(
        sorted(
            row.period
            for row in series
            if row.purchases_t > 0 and row.exports_total_t > 0
        )
    )


def compute_season_balance(
    season: str, series: list[MonthlyOriginSeries]
) -> SeasonBalance:
    """Aggregate the balance over the season's achats ∩ exports window."""
    window = balance_window(series)
    in_window = [row for row in series if row.period in set(window)]
    monthly = tuple(monthly_balance(row) for row in sorted(in_window, key=_period))

    purchases_t = sum(row.purchases_t for row in monthly)
    exports_beans_t = sum(row.exports_beans_t for row in monthly)
    exports_transformed_t = sum(row.exports_transformed_t for row in monthly)
    grinding_derived_t = sum(row.grinding_derived_t for row in monthly)
    balance_t = purchases_t - exports_beans_t - grinding_derived_t

    return SeasonBalance(
        season=season,
        months=window,
        purchases_t=purchases_t,
        exports_beans_t=exports_beans_t,
        exports_transformed_t=exports_transformed_t,
        grinding_derived_t=grinding_derived_t,
        balance_t=balance_t,
        ratios=compute_ratios(
            purchases_t, exports_beans_t, grinding_derived_t, balance_t
        ),
        monthly=monthly,
    )


def cumulative_balance(monthly: tuple[MonthlyBalance, ...]) -> tuple[float, ...]:
    """Running season balance, month by month, in season order.

    The caller is responsible for passing months already in season order
    (Oct→Sep), which is what ``compute_season_balance`` produces.
    """
    running = 0.0
    out: list[float] = []
    for row in monthly:
        running += row.balance_t
        out.append(running)
    return tuple(out)


# ---------------------------------------------------------------------------
# STATSER confrontation (§5)
# ---------------------------------------------------------------------------
def confront_statser(
    series: list[MonthlyOriginSeries], *, perimeter: str
) -> StatserConfrontation | None:
    """Compare derived grinding against STATSER's declaration.

    Returns ``None`` when no month has all three sources — there is nothing to
    compare, and inventing a zero would publish a fake gap.

    ``perimeter`` is **required and not defaulted** on purpose. STATSER only ever
    covers the 11 GEPEX operators, so a meaningful comparison needs the derived
    side computed on those same operators. Passing all-operator exports here
    produces a number, and that number is the ~3x perimeter bias business-rules
    §4.5 warns about — measured on `11336ef`, all-CI derived (284 216 t) against
    GEPEX declared (381 169 t) over the same 7 months is a -25 % gap that says
    nothing. Making the caller name the perimeter is what stops the mislabelling.

    A genuine gap is interesting rather than wrong: either STATSER under-reports,
    or ground beans do not leave as exports (domestic use, product stock). It is
    the most novel analytic in block (2) and has no v1 equivalent.
    """
    comparable = sorted(
        (
            row
            for row in series
            if row.grinding_declared_t is not None
            and row.purchases_t > 0
            and row.exports_total_t > 0
        ),
        key=_period,
    )
    if not comparable:
        return None

    derived_t = sum(derive_grinding(row.exports_transformed_t) for row in comparable)
    declared_t = sum(row.grinding_declared_t or 0.0 for row in comparable)
    gap_t = derived_t - declared_t
    return StatserConfrontation(
        months=tuple(row.period for row in comparable),
        derived_t=derived_t,
        declared_t=declared_t,
        gap_t=gap_t,
        gap_pct=(gap_t / declared_t * 100) if declared_t > 0 else None,
        perimeter=perimeter,
    )


# ---------------------------------------------------------------------------
# per-source YTD (§6)
# ---------------------------------------------------------------------------
def ytd_block(
    source: str,
    season: str,
    per_month: dict[date, float],
    previous_per_month: dict[date, float],
) -> YtdBlock:
    """Season-to-date for one source vs the same campaign months a year earlier.

    ``previous_per_month`` is looked up at the **same month shifted back one
    year**, so a source that has published 10 months this season is compared
    against exactly those 10 months last season — never against a full season it
    does not cover.
    """
    months = tuple(sorted(period for period, value in per_month.items() if value))
    current_t = sum(per_month[period] for period in months)
    previous_t = sum(
        previous_per_month.get(_shift_back_one_year(p), 0.0) for p in months
    )
    return YtdBlock(
        source=source,
        season=season,
        previous_season=_previous_season(season),
        months=months,
        current_t=current_t,
        previous_t=previous_t,
        delta_pct=(current_t / previous_t - 1) * 100 if previous_t > 0 else None,
    )


# ---------------------------------------------------------------------------
# invariants (§4.3) — the signature of a double-count
# ---------------------------------------------------------------------------
class BalanceInvariantError(Exception):
    """A computed balance violates an invariant that arithmetic guarantees.

    Both conditions are impossible on coherent data, so either failing means the
    computation double-counted — exactly the v1 bug. Raising is correct: serving a
    124 % outflow rate to a client is worse than serving an error.
    """


def assert_balance_invariants(balance: SeasonBalance) -> None:
    """``0 ≤ taux_sortie ≤ 100`` and ``solde ≥ 0``, at season grain.

    Season grain, not monthly: a single month can legitimately show a negative
    balance (off-season shipments draw on stock bought earlier). A negative
    *season* balance means selling matter that was never purchased.
    """
    outflow = balance.ratios.outflow_rate_pct
    if outflow is not None and not (0.0 <= outflow <= 100.0):
        raise BalanceInvariantError(
            f"{balance.season}: taux de sortie {outflow:.2f}% is outside [0, 100] — "
            "you cannot ship out more matter than was bought. This is the "
            "signature of a double-count (business-rules §4)."
        )
    if balance.balance_t < 0:
        raise BalanceInvariantError(
            f"{balance.season}: solde {balance.balance_t:,.1f} t is negative — "
            "that means selling stock never purchased. Check that transformed "
            "exports were converted to bean equivalent before entering the "
            "balance (business-rules §4.1)."
        )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _period(row: MonthlyOriginSeries | MonthlyBalance) -> date:
    return row.period


def _shift_back_one_year(period: date) -> date:
    return period.replace(year=period.year - 1)


def _previous_season(season: str) -> str:
    start, end = (int(part) for part in season.split("-"))
    return f"{start - 1}-{end - 1}"
