"""Computed totals vs the published golden values.

The gate on Phase 1 (integration doc §9). Three properties matter:

* **The fixtures are already verified upstream.** The doc records 8/8 exact
  against `refonte-da-v2` @ `11336ef`, including both product mixes. Phase 1's
  job is to *reproduce a verified result*, not to discover one — so any
  divergence is a bug in our implementation and never a reason to adjust a value.
* **Period-driven, never hardcoded to a month.** Which checks run is decided by
  what the loaded batch actually covers. A golden entry whose period is not yet
  in the data is reported as *skipped* and starts being enforced automatically
  once that month lands.
* **Coverage is per source** (business-rules §6). The three sources stop at
  different months — on `11336ef`: exports 2026-07, achats 2026-07, broyage
  2026-04 — so an exports check and an achats check are gated independently.
  Comparing a source's YTD against a window it does not cover is the one thing
  §6 forbids outright.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import text
from sqlalchemy.orm import Session

from scripts.watchai_sync import config
from scripts.watchai_sync.errors import ReconciliationError

logger = logging.getLogger(__name__)

# YTD is the month-set intersection, not a date cutoff: business-rules §6 keeps
# the month-set logic and applies it per source. Both golden YTD lines are
# "through July", i.e. season months {10,11,12,1..7}.
YTD_THROUGH_MONTH = 7

EXPORTS = "exports"
PURCHASES = "purchases"


@dataclass(frozen=True)
class GoldenMonth:
    """One calendar month as published — the July 2026 synthèse."""

    year: int
    month: int
    exports_tonnes: float
    purchases_tonnes: float
    valcaf_fcfa_millions: float
    taxes_fcfa_millions: float


@dataclass(frozen=True)
class GoldenSeasonYtd:
    """Season-to-date totals as published, in tonnes and millions of FCFA.

    ``taxes_fcfa_millions`` is optional: the current doc prints taxes only for
    the July month, but both season figures were verified exact on the same data
    and are kept as Compass-side checks — a free extra constraint on the
    duties_taxes column that nothing else exercises at season scale.
    """

    season: str
    through_month: int
    exports_tonnes: float
    purchases_tonnes: float
    taxes_fcfa_millions: float | None = None


@dataclass(frozen=True)
class GoldenProductMix:
    """Season-to-date export tonnage per published product bucket.

    Buckets are WatchAI's collapse, so ``MASSE`` is printed as
    "MASSE/PATE/LIQUEUR" in the report; our canonical ``MASSE`` is the same set.
    """

    season: str
    through_month: int
    tonnes_by_product: dict[str, float]


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: Literal["passed", "skipped", "failed"]
    detail: str
    expected: float | None = None
    actual: float | None = None


@dataclass(frozen=True)
class ReconciliationReport:
    results: tuple[CheckResult, ...] = field(default_factory=tuple)

    @property
    def failures(self) -> tuple[CheckResult, ...]:
        return tuple(r for r in self.results if r.status == "failed")

    @property
    def passed(self) -> tuple[CheckResult, ...]:
        return tuple(r for r in self.results if r.status == "passed")

    @property
    def skipped(self) -> tuple[CheckResult, ...]:
        return tuple(r for r in self.results if r.status == "skipped")


# --- Published golden values ------------------------------------------------
# Source: the July 2026 WatchAI monthly report. Scope: all operators (GEPEX
# toggle OFF), all products, all ports. Verified 8/8 exact against
# `refonte-da-v2` @ `11336ef` on 2026-08-17, both product mixes included.
GOLDEN_MONTHS: tuple[GoldenMonth, ...] = (
    GoldenMonth(
        year=2026,
        month=7,
        exports_tonnes=147_866,
        purchases_tonnes=81_582,
        valcaf_fcfa_millions=326_784,
        taxes_fcfa_millions=40_765,
    ),
)

GOLDEN_SEASON_YTD: tuple[GoldenSeasonYtd, ...] = (
    GoldenSeasonYtd(
        season="2025-2026",
        through_month=YTD_THROUGH_MONTH,
        exports_tonnes=1_710_347,
        purchases_tonnes=2_087_867,
        taxes_fcfa_millions=883_664,
    ),
    # The N-1 comparison line of the same report.
    GoldenSeasonYtd(
        season="2024-2025",
        through_month=YTD_THROUGH_MONTH,
        exports_tonnes=1_428_071,
        purchases_tonnes=1_622_077,
        taxes_fcfa_millions=532_611,
    ),
)

GOLDEN_PRODUCT_MIX: tuple[GoldenProductMix, ...] = (
    GoldenProductMix(
        season="2025-2026",
        through_month=YTD_THROUGH_MONTH,
        tonnes_by_product={
            "FEVES": 1_236_439,
            "MASSE": 180_891,  # published as "MASSE/PATE/LIQUEUR"
            "HORS_GRADE": 133_840,
            "BEURRE": 109_329,
            "CHOCOLAT": 38_793,
            "POUDRE": 11_055,
        },
    ),
    GoldenProductMix(
        season="2024-2025",
        through_month=YTD_THROUGH_MONTH,
        tonnes_by_product={
            "FEVES": 948_931,
            "MASSE": 159_761,
            "HORS_GRADE": 151_436,
            "BEURRE": 110_085,
            "CHOCOLAT": 44_303,
            "POUDRE": 13_556,
        },
    ),
)

# The report also prints "TOTAL TRANSFORMÉ 473 907 t (27,7 %)" for 2025-2026 YTD.
# That figure counts HORS GRADE as transformed; business-rules §2 establishes it
# is a bean (weighted CAF at 96,8 % of the fève price, POSTAR 1802 being a fiscal
# choice, and v2's own tested code), so Compass publishes 340 068 t (19,9 %).
#
# Integration doc §9 asks that the delta be pinned to its single known cause
# rather than tolerated as an approximate match — that assertion lives in the
# test suite, and these two constants are what it asserts against.
WATCHAI_TOTAL_TRANSFORME_INCLUDES_HORS_GRADE = 473_907
COMPASS_TOTAL_TRANSFORME = 340_068

# The published figures are rounded to whole tonnes / whole millions, so one unit
# of slack is rounding, not laxity. Observed worst case: 0,47 t.
TONNES_TOLERANCE = 1.0
FCFA_MILLIONS_TOLERANCE = 1.0


def reconcile(session: Session, batch_id: uuid.UUID) -> ReconciliationReport:
    """Run every golden check the loaded batch has the data to support."""
    coverage = _coverage(session, batch_id)
    results: list[CheckResult] = []

    for golden in GOLDEN_MONTHS:
        results.extend(_check_month(session, batch_id, golden, coverage))
    for golden in GOLDEN_SEASON_YTD:
        results.extend(_check_season_ytd(session, batch_id, golden, coverage))
    for golden in GOLDEN_PRODUCT_MIX:
        results.extend(_check_product_mix(session, batch_id, golden, coverage))

    report = ReconciliationReport(results=tuple(results))
    logger.info(
        "reconciliation: %d passed, %d skipped, %d failed",
        len(report.passed),
        len(report.skipped),
        len(report.failures),
    )
    return report


def raise_on_failure(report: ReconciliationReport) -> None:
    """Abort the run if any applicable golden value diverged."""
    if not report.failures:
        return
    lines = [
        f"  {r.name}: expected {r.expected:,.0f}, got {r.actual:,.0f} "
        f"(delta {r.actual - r.expected:+,.0f})"
        for r in report.failures
        if r.expected is not None and r.actual is not None
    ]
    raise ReconciliationError(
        f"{len(report.failures)} golden value(s) diverged:\n"
        + "\n".join(lines)
        + "\n\nThese fixtures are verified exact against "
        f"{config.SPEC_SOURCE_BRANCH}@{config.SPEC_SOURCE_COMMIT[:12]} "
        f"({config.SPEC_VERIFIED_ON}), so this is a bug in our transform — a "
        "taxonomy (business-rules §2) or unit (§1) error. Do not adjust the "
        "expected values."
    )


# ---------------------------------------------------------------------------
# individual checks
# ---------------------------------------------------------------------------
def _check_month(
    session: Session,
    batch_id: uuid.UUID,
    golden: GoldenMonth,
    coverage: dict[str, dict[str, set[int]]],
) -> list[CheckResult]:
    """The monthly synthèse — exports, achats, VALCAF, taxes for one month."""
    season = _season_of(golden.year, golden.month)
    label = f"{golden.year}-{golden.month:02d}"
    results: list[CheckResult] = []

    exports_ready = _covers(coverage, EXPORTS, season, {golden.month})
    purchases_ready = _covers(coverage, PURCHASES, season, {golden.month})

    if exports_ready:
        row = session.execute(
            text(
                """
                SELECT COALESCE(SUM(export_tonnes), 0),
                       COALESCE(SUM(valcaf), 0) / 1000000,
                       COALESCE(SUM(duties_taxes), 0) / 1000000
                  FROM pl_origin_flow_monthly
                 WHERE ingest_batch_id = :batch_id AND period_date = :period
                """
            ),
            {"batch_id": batch_id, "period": f"{golden.year}-{golden.month:02d}-01"},
        ).one()
        results.append(
            _compare(
                f"{label} exports (t)",
                golden.exports_tonnes,
                float(row[0]),
                TONNES_TOLERANCE,
            )
        )
        results.append(
            _compare(
                f"{label} VALCAF (M FCFA)",
                golden.valcaf_fcfa_millions,
                float(row[1]),
                FCFA_MILLIONS_TOLERANCE,
            )
        )
        results.append(
            _compare(
                f"{label} taxes (M FCFA)",
                golden.taxes_fcfa_millions,
                float(row[2]),
                FCFA_MILLIONS_TOLERANCE,
            )
        )
    else:
        results.append(_skip(f"{label} exports/VALCAF/taxes", EXPORTS, label))

    if purchases_ready:
        purchases = _scalar(
            session,
            f"""
            SELECT COALESCE(SUM(net_weight_kg), 0) / {config.KG_PER_TONNE}
              FROM pl_origin_purchase_monthly
             WHERE ingest_batch_id = :batch_id AND period_date = :period
            """,
            {"batch_id": batch_id, "period": f"{golden.year}-{golden.month:02d}-01"},
        )
        results.append(
            _compare(
                f"{label} achats (t)",
                golden.purchases_tonnes,
                purchases,
                TONNES_TOLERANCE,
            )
        )
    else:
        results.append(_skip(f"{label} achats", PURCHASES, label))

    return results


def _check_season_ytd(
    session: Session,
    batch_id: uuid.UUID,
    golden: GoldenSeasonYtd,
    coverage: dict[str, dict[str, set[int]]],
) -> list[CheckResult]:
    label = f"{golden.season} YTD(Oct→M{golden.through_month})"
    required = _ytd_month_set(golden.through_month)
    months = list(required)
    results: list[CheckResult] = []

    if _covers(coverage, EXPORTS, golden.season, required):
        exports, taxes = session.execute(
            text(
                """
                SELECT COALESCE(SUM(export_tonnes), 0),
                       COALESCE(SUM(duties_taxes), 0) / 1000000
                  FROM pl_origin_flow_monthly
                 WHERE ingest_batch_id = :batch_id
                   AND season = :season
                   AND EXTRACT(MONTH FROM period_date) = ANY(:months)
                """
            ),
            {"batch_id": batch_id, "season": golden.season, "months": months},
        ).one()
        results.append(
            _compare(
                f"{label} exports (t)",
                golden.exports_tonnes,
                float(exports),
                TONNES_TOLERANCE,
            )
        )
        if golden.taxes_fcfa_millions is not None:
            results.append(
                _compare(
                    f"{label} taxes (M FCFA)",
                    golden.taxes_fcfa_millions,
                    float(taxes),
                    FCFA_MILLIONS_TOLERANCE,
                )
            )
    else:
        results.append(
            _skip(f"{label} exports", EXPORTS, golden.season, required, coverage)
        )

    if _covers(coverage, PURCHASES, golden.season, required):
        purchases = _scalar(
            session,
            f"""
            SELECT COALESCE(SUM(net_weight_kg), 0) / {config.KG_PER_TONNE}
              FROM pl_origin_purchase_monthly
             WHERE ingest_batch_id = :batch_id
               AND season = :season
               AND EXTRACT(MONTH FROM period_date) = ANY(:months)
            """,
            {"batch_id": batch_id, "season": golden.season, "months": months},
        )
        results.append(
            _compare(
                f"{label} achats (t)",
                golden.purchases_tonnes,
                purchases,
                TONNES_TOLERANCE,
            )
        )
    else:
        results.append(
            _skip(f"{label} achats", PURCHASES, golden.season, required, coverage)
        )

    return results


def _check_product_mix(
    session: Session,
    batch_id: uuid.UUID,
    golden: GoldenProductMix,
    coverage: dict[str, dict[str, set[int]]],
) -> list[CheckResult]:
    label = f"{golden.season} YTD(Oct→M{golden.through_month}) mix"
    required = _ytd_month_set(golden.through_month)
    if not _covers(coverage, EXPORTS, golden.season, required):
        return [_skip(label, EXPORTS, golden.season, required, coverage)]

    actual = {
        product: float(tonnes)
        for product, tonnes in session.execute(
            text(
                """
                SELECT product_code, SUM(export_tonnes)
                  FROM pl_origin_flow_monthly
                 WHERE ingest_batch_id = :batch_id
                   AND season = :season
                   AND EXTRACT(MONTH FROM period_date) = ANY(:months)
                 GROUP BY product_code
                """
            ),
            {"batch_id": batch_id, "season": golden.season, "months": list(required)},
        )
    }
    return [
        _compare(
            f"{label} {product}", expected, actual.get(product, 0.0), TONNES_TOLERANCE
        )
        for product, expected in sorted(golden.tonnes_by_product.items())
    ]


def _compare(
    name: str, expected: float, actual: float, tolerance: float
) -> CheckResult:
    delta = actual - expected
    if abs(delta) <= tolerance:
        return CheckResult(
            name=name,
            status="passed",
            detail=f"{actual:,.0f} (Δ {delta:+.3f})",
            expected=expected,
            actual=actual,
        )
    return CheckResult(
        name=name,
        status="failed",
        detail=f"expected {expected:,.0f}, got {actual:,.0f}",
        expected=expected,
        actual=actual,
    )


def _skip(
    name: str,
    source: str,
    period: str,
    required: set[int] | None = None,
    coverage: dict[str, dict[str, set[int]]] | None = None,
) -> CheckResult:
    """A skip must be actionable — it names the source and the missing months, so
    an operator can tell "waiting on data" from "broken"."""
    detail = f"{source} does not cover {period}"
    if required is not None and coverage is not None:
        missing = sorted(required - coverage.get(source, {}).get(period, set()))
        if missing:
            detail = f"{source} does not cover month(s) {missing} of {period}"
    return CheckResult(
        name=name,
        status="skipped",
        detail=detail + "; activates on its own once it lands",
    )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _ytd_month_set(through_month: int) -> set[int]:
    """Season months from October through ``through_month``.

    business-rules §6 keeps the month-set logic over the date-cutoff variant: it
    handles gaps (a missing month in N does not inflate N-1) and needs no
    leap-year special case.
    """
    months = {10, 11, 12}
    months.update(range(1, through_month + 1))
    return months


def _season_of(year: int, month: int) -> str:
    if month >= config.SEASON_START_MONTH:
        return f"{year}-{year + 1}"
    return f"{year - 1}-{year}"


def _covers(
    coverage: dict[str, dict[str, set[int]]],
    source: str,
    season: str,
    required: set[int],
) -> bool:
    return required <= coverage.get(source, {}).get(season, set())


def _coverage(session: Session, batch_id: uuid.UUID) -> dict[str, dict[str, set[int]]]:
    """Which (season, month) pairs each source actually holds, per source.

    Per-source rather than global because the three publications stop at
    different months (business-rules §6). Checking an achats total against a
    window achats does not cover would produce a false failure — which is exactly
    what §6 forbids.
    """
    queries = {
        EXPORTS: """
            SELECT DISTINCT season, EXTRACT(MONTH FROM period_date)::int
              FROM pl_origin_flow_monthly WHERE ingest_batch_id = :batch_id
        """,
        PURCHASES: """
            SELECT DISTINCT season, EXTRACT(MONTH FROM period_date)::int
              FROM pl_origin_purchase_monthly WHERE ingest_batch_id = :batch_id
        """,
    }
    coverage: dict[str, dict[str, set[int]]] = {}
    for source, sql in queries.items():
        per_season: dict[str, set[int]] = {}
        for season, month in session.execute(text(sql), {"batch_id": batch_id}):
            per_season.setdefault(season, set()).add(int(month))
        coverage[source] = per_season
    return coverage


def _scalar(session: Session, sql: str, params: dict) -> float:
    return float(session.execute(text(sql), params).scalar_one())
