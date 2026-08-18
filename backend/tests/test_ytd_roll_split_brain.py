"""Regression: YTD + ensemble running_acc must not freeze when OHLCV OI rolls
ahead of the contract the decisions are written on.

Prod incident (2026-07): CAZ26 (Dec) overtook the active CAU26 (Sep) in open
interest on 2026-06-23, but ``cc-ensemble-compute`` / ``cc-daily-analysis``
kept writing decisions on CAU26. The old queries picked the front-month by OI
alone (CAZ26), whose ``pl_indicator_daily`` decision was NULL, so every
post-crossover session was silently skipped — the YTD froze at 93.60% for
~3 weeks and ``running_acc_5d`` degraded to the R&D bootstrap value.

The durable fix: both consumers share the canonical roll calendar
(``ref_contract.active_from``) via ``_decision_aware_front_month_series`` — the
front-month per date is the operator's pinned contract, so a higher-OI contract
the operator never rolled to (CAZ26) can never drag the walk off the decision
series.
"""

from __future__ import annotations

import uuid
from datetime import date as date_cls
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline import (
    PlAlgorithmVersion,
    PlContractDataDaily,
    PlIndicatorDaily,
)
from app.models.reference import RefCommodity, RefContract, RefExchange
from app.services.dashboard_service import (
    YTD_EVAL_HORIZON_DAYS,
    _score_day,
    calculate_ytd_performance,
    compute_running_accuracy,
)
from app.utils.contract_resolver import (
    ENSEMBLE_VERSION_NAME,
    LEGACY_VERSION_NAME,
    _cache,
)
from app.utils.serving_chain import reset_cache as reset_serving_cache

# 12 weekday sessions in Jan 2026 (Jan 1 is a holiday, start Mon Jan 5).
_SESSIONS = [date_cls(2026, 1, d) for d in (5, 6, 7, 8, 9, 12, 13, 14, 15, 16, 19, 20)]
# CAU26 closes — the contract that actually carries the decisions. Chosen so
# the post-crossover days (i≥5) score very differently (+1.25 recoveries) from
# the pre-crossover ones, making a regression numerically obvious.
_CAU_CLOSES: list[float] = [100, 102, 104, 106, 108, 90, 92, 94, 96, 120, 122, 124]
# The crossover: from index 5 on, CAZ26 has higher OI but NO decision row.
_CROSSOVER_IDX = 5


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    _cache.clear()
    reset_serving_cache()


async def _contract(
    db: AsyncSession,
    code: str,
    *,
    active: bool,
    active_from: date_cls | None = None,
) -> uuid.UUID:
    ex = RefExchange(code=f"ICE-{code}", name="ICE", timezone="UTC")
    db.add(ex)
    await db.flush()
    com = RefCommodity(code=f"CC-{code}", name="Cocoa", exchange_id=ex.id)
    db.add(com)
    await db.flush()
    c = RefContract(
        commodity_id=com.id,
        code=code,
        contract_month=code[-3:],
        is_active=active,
        active_from=active_from,
    )
    db.add(c)
    await db.flush()
    return c.id


# Serving order now comes from the DB (pl_algorithm_version.serving_rank)
# instead of hardcoded constants — the fixtures must configure the same chain
# the production seed migration installs: ensemble preferred, legacy fallback.
_RANKS = {ENSEMBLE_VERSION_NAME: 1, LEGACY_VERSION_NAME: 2}


async def _version(db: AsyncSession, name: str, *, active: bool) -> uuid.UUID:
    v = PlAlgorithmVersion(
        name=name,
        version="1.0.0",
        horizon="short_term",
        is_active=active,
        serving_rank=_RANKS.get(name),
    )
    db.add(v)
    await db.flush()
    return v.id


async def _seed_roll_split_brain(db: AsyncSession) -> None:
    """Seed CAU26 (decisions, lower OI) + CAZ26 (higher OI, NO decision).

    From ``_CROSSOVER_IDX`` on, CAZ26 has the higher OI — an OI-only
    front-month pick would select it and drop the CAU26 decisions.
    """
    # CAU26 is the operator's front-month from the first session (roll calendar);
    # CAZ26 is never rolled to (no active_from) despite leading OI later.
    cau = await _contract(db, "CAU26", active=True, active_from=_SESSIONS[0])
    caz = await _contract(db, "CAZ26", active=False)  # higher OI, no calendar entry
    legacy = await _version(db, LEGACY_VERSION_NAME, active=True)
    await _version(db, ENSEMBLE_VERSION_NAME, active=False)  # no rows

    for i, (session, close) in enumerate(zip(_SESSIONS, _CAU_CLOSES)):
        # CAU26 OHLCV + legacy decision on every session.
        db.add(
            PlContractDataDaily(
                date=session,
                contract_id=cau,
                close=Decimal(str(close)),
                volume=1000,
                oi=1000,
            )
        )
        db.add(
            PlIndicatorDaily(
                date=session,
                contract_id=cau,
                algorithm_version_id=legacy,
                decision="OPEN",
                conclusion="seeded",
            )
        )
        # CAZ26 OHLCV with HIGHER OI from the crossover on — but NO decision.
        if i >= _CROSSOVER_IDX:
            db.add(
                PlContractDataDaily(
                    date=session,
                    contract_id=caz,
                    close=Decimal("200"),  # wildly different — must be ignored
                    volume=9999,
                    oi=99999,  # would win an OI-only front-month pick
                )
            )
    await db.flush()
    _cache.clear()
    reset_serving_cache()


def _expected_ytd(closes: list[float], decision: str) -> float:
    """Replicate the YTD walk over a single-contract series (the fixed path)."""
    horizon = YTD_EVAL_HORIZON_DAYS
    scores = [
        _score_day(decision, float(closes[i]), float(closes[i + horizon]))
        for i in range(len(closes) - horizon)
    ]
    scores = [s for s in scores if s is not None]
    return sum(scores) / len(scores) * 100


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ytd_does_not_freeze_when_oi_rolls_ahead_of_decision_contract(
    db_session: AsyncSession,
) -> None:
    await _seed_roll_split_brain(db_session)

    result = await calculate_ytd_performance(db_session, reference_date=_SESSIONS[-1])

    # The fixed walk scores ALL sessions on CAU26 (the decision series), so the
    # post-crossover +1.25 recoveries are included.
    expected = _expected_ytd(_CAU_CLOSES, "OPEN")
    assert result == pytest.approx(expected, abs=0.01)

    # Guard: had the bug survived, the post-crossover sessions (i≥5) would drop
    # out and the value would collapse toward the pre-crossover-only average.
    frozen = _expected_ytd(
        _CAU_CLOSES[: _CROSSOVER_IDX + YTD_EVAL_HORIZON_DAYS], "OPEN"
    )
    assert abs(result - frozen) > 10.0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_running_acc_survives_roll_via_shared_helper(
    db_session: AsyncSession,
) -> None:
    await _seed_roll_split_brain(db_session)

    acc = await compute_running_accuracy(db_session, _SESSIONS[-1], window=5)

    # With the shared decision-aware helper, all 8 evaluable days score on
    # CAU26. The last 5 (i=3..7) are 2 losses + 3 wins → 0.6. Pre-fix, the
    # post-crossover days dropped to CAZ26 (no decision) and the metric fell
    # back to None (→ R&D bootstrap value on the dashboard).
    assert acc == pytest.approx(0.6)
