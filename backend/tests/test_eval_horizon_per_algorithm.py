"""An algorithm is scored on the horizon it actually predicts.

``YTD_EVAL_HORIZON_DAYS = 4`` was tuned for ensemble v1.0.0 (J+4-J+5) and was,
until this change, applied to every algorithm. Regime decides for the NEXT
session — and the brief prints "Horizon de décision : prochaine séance" a few
lines above the YTD figure. Scoring that decision four sessions out measures
drift the track never claimed, right underneath a label that says otherwise.

The bug is invisible by inspection: both horizons produce a plausible percentage.
Only a series where the two disagree exposes it, which is what these tests build.
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
    calculate_ytd_performance,
    compute_running_accuracy,
    eval_horizon_for,
)
from app.utils.contract_resolver import (
    ENSEMBLE_VERSION_NAME,
    REGIME_VERSION_NAME,
    _cache,
)
from app.utils.serving_chain import reset_cache as reset_serving_cache

# 12 weekday sessions in Jan 2026.
_SESSIONS = [date_cls(2026, 1, d) for d in (5, 6, 7, 8, 9, 12, 13, 14, 15, 16, 19, 20)]

# A saw-tooth riding an uptrend: +20 then -10, session after session. An OPEN
# call loses every other day at J+1, yet wins on EVERY comparison at J+4, because
# four steps of the tooth net out to +20. This is exactly how a horizon mismatch
# hides — both readings are believable percentages, and only the label says which
# one the track earned.
_CLOSES: list[float] = [100, 120, 110, 130, 120, 140, 130, 150, 140, 160, 150, 170]


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    _cache.clear()
    reset_serving_cache()


async def _contract(db: AsyncSession, code: str) -> uuid.UUID:
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
        is_active=True,
        active_from=_SESSIONS[0],
    )
    db.add(c)
    await db.flush()
    return c.id


async def _version(db: AsyncSession, name: str, *, rank: int | None) -> uuid.UUID:
    v = PlAlgorithmVersion(
        name=name,
        version="1.0.0",
        horizon="short_term",
        is_active=False,
        serving_rank=rank,
    )
    db.add(v)
    await db.flush()
    return v.id


async def _seed(db: AsyncSession, *, served: str) -> None:
    """One contract, one served algorithm, OPEN every session."""
    contract = await _contract(db, "CAU26")
    algo = await _version(db, served, rank=1)
    for session, close in zip(_SESSIONS, _CLOSES):
        db.add(
            PlContractDataDaily(
                date=session,
                contract_id=contract,
                close=Decimal(str(close)),
                volume=1000,
                oi=1000,
            )
        )
        db.add(
            PlIndicatorDaily(
                date=session,
                contract_id=contract,
                algorithm_version_id=algo,
                decision="OPEN",
                conclusion="seeded",
            )
        )
    await db.flush()
    _cache.clear()
    reset_serving_cache()


# ---------------------------------------------------------------------------
# The mapping itself
# ---------------------------------------------------------------------------


def test_regime_is_scored_at_the_next_session() -> None:
    assert eval_horizon_for(REGIME_VERSION_NAME) == 1


def test_ensemble_keeps_its_tuned_horizon() -> None:
    assert eval_horizon_for(ENSEMBLE_VERSION_NAME) == YTD_EVAL_HORIZON_DAYS == 4


@pytest.mark.parametrize("name", [None, "", "legacy", "some_future_algorithm"])
def test_unknown_algorithms_fall_back_to_the_default(name: str | None) -> None:
    """A new track is scored like its predecessors until someone decides otherwise.

    Visible in the figure, rather than a KeyError on the dashboard's hot path.
    """
    assert eval_horizon_for(name) == YTD_EVAL_HORIZON_DAYS


# ---------------------------------------------------------------------------
# The YTD walk honours it
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ytd_scores_regime_on_its_own_horizon(db_session: AsyncSession) -> None:
    await _seed(db_session, served="regime")

    at_j1 = await calculate_ytd_performance(
        db_session, reference_date=_SESSIONS[-1], algorithm_name="regime"
    )
    at_j4 = await calculate_ytd_performance(
        db_session, reference_date=_SESSIONS[-1], algorithm_name=ENSEMBLE_VERSION_NAME
    )

    # J+4 skips over every dip: all 8 comparisons win, a flawless 125%. J+1 sees
    # the dips and pays for them.
    assert at_j4 == pytest.approx(125.0, abs=0.01)
    assert at_j1 < at_j4
    # Pinning the value, not just the ordering — a refactor that silently
    # reverted the horizon would still satisfy a `<` assertion if it also
    # changed the scoring.
    assert at_j1 == pytest.approx(61.62, abs=0.01)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ytd_defaults_to_the_head_of_the_serving_chain(
    db_session: AsyncSession,
) -> None:
    """Callers that do not pass a name get the algorithm the figure describes.

    The headline YTD is "how the served system did"; the head of the chain is
    that system, so it decides the horizon.
    """
    await _seed(db_session, served="regime")

    implicit = await calculate_ytd_performance(db_session, reference_date=_SESSIONS[-1])
    explicit = await calculate_ytd_performance(
        db_session, reference_date=_SESSIONS[-1], algorithm_name="regime"
    )
    assert implicit == pytest.approx(explicit, abs=0.001)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_running_accuracy_honours_the_same_horizon(
    db_session: AsyncSession,
) -> None:
    """The tile and the headline must never be computed on different horizons."""
    await _seed(db_session, served="regime")

    at_j1 = await compute_running_accuracy(
        db_session, _SESSIONS[-1], algorithm_name="regime", window=5
    )
    at_j4 = await compute_running_accuracy(
        db_session, _SESSIONS[-1], algorithm_name=ENSEMBLE_VERSION_NAME, window=5
    )

    # Saw-tooth again: at J+4 every OPEN wins, at J+1 three of the last five do.
    assert at_j4 == pytest.approx(1.0)
    assert at_j1 == pytest.approx(0.6)
