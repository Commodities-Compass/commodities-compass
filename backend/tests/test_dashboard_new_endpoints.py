"""Integration tests for the 4 new dashboard services (Phase 1.3).

Covers:
- macro_panel_service: FX lookup (latest business day), ENSO lag, orchestrator join.
- positioning_service: COT EU lookup, stocks (date-fallback), EU/US ratio in tonnes.
- ensemble_diagnostics_service: orchestrator + specialist votes + cluster mapping JSON.
"""

from __future__ import annotations

import json
import uuid
from datetime import date as date_cls
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline import (
    PlAlgorithmConfig,
    PlAlgorithmVersion,
    PlContractDataDaily,
    PlCotEuWeekly,
    PlCotUsWeekly,
    PlExternalIndicator,
    PlOrchestratorDecision,
    PlSpecialistPrediction,
    PlStockObservation,
)
from app.models.reference import RefCommodity, RefContract, RefExchange
from app.services.ensemble_diagnostics_service import (
    get_ensemble_diagnostics,
    get_specialist_votes,
)
from app.services.macro_panel_service import ENSO_LAG_DAYS, get_macro_panel
from app.services.positioning_service import get_positioning


async def _seed_chain(db: AsyncSession, code: str = "CAK26") -> uuid.UUID:
    exchange = RefExchange(code=f"ICE-{code}", name="ICE", timezone="UTC")
    db.add(exchange)
    await db.flush()
    commodity = RefCommodity(
        code=f"COCOA-{code}", name="Cocoa", exchange_id=exchange.id
    )
    db.add(commodity)
    await db.flush()
    contract = RefContract(
        commodity_id=commodity.id,
        code=code,
        contract_month=code[-3:],
        is_active=False,
    )
    db.add(contract)
    await db.flush()
    return contract.id


async def _seed_version(db: AsyncSession, name: str) -> uuid.UUID:
    v = PlAlgorithmVersion(
        name=name,
        version="1.0.0",
        horizon="short_term",
        is_active=False,
        compute_enabled=True,
        description=f"Test {name}",
    )
    db.add(v)
    await db.flush()
    return v.id


# ---------------------------------------------------------------------------
# macro_panel_service
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_macro_panel_picks_latest_fx_and_lagged_enso(
    db_session: AsyncSession,
) -> None:
    contract = await _seed_chain(db_session, "CAK26")
    version = await _seed_version(db_session, "ensemble_v1_softgate_wrapper")

    target = date_cls(2026, 5, 15)

    # FX rows — one too recent (after target), one on target, one earlier
    db_session.add_all(
        [
            PlExternalIndicator(
                date=date_cls(2026, 5, 14),
                fx_dxy_proxy=Decimal("0.95"),
                fx_gbpusd=Decimal("1.27"),
                fx_eurusd=Decimal("0.95"),
                fx_gbpeur=Decimal("0.85"),
            ),
            PlExternalIndicator(
                date=date_cls(2026, 5, 15),
                fx_dxy_proxy=Decimal("0.96"),
                fx_gbpusd=Decimal("1.28"),
                fx_eurusd=Decimal("0.96"),
                fx_gbpeur=Decimal("0.86"),
            ),
            PlExternalIndicator(
                date=date_cls(2026, 5, 20),  # after target — must be ignored
                fx_dxy_proxy=Decimal("0.99"),
                fx_gbpusd=Decimal("1.30"),
                fx_eurusd=Decimal("0.99"),
                fx_gbpeur=Decimal("0.88"),
            ),
        ]
    )

    # ENSO rows — one inside lag window (must be ignored), one outside
    db_session.add_all(
        [
            PlExternalIndicator(
                date=date_cls(2026, 4, 1),
                enso_oni_month=Decimal("0.30"),
                enso_nino34_anomaly=Decimal("0.40"),
            ),
            PlExternalIndicator(
                date=date_cls(2026, 5, 10),  # within lag window → ignored
                enso_oni_month=Decimal("0.50"),
                enso_nino34_anomaly=Decimal("0.60"),
            ),
        ]
    )

    db_session.add(
        PlOrchestratorDecision(
            date=target,
            contract_id=contract,
            algorithm_version_id=version,
            soft_gate_decision="OPEN",
            net_score=Decimal("0.55"),
            weights_sum=Decimal("11.0"),
            n_committed_specialists=12,
            decision_wrapped="OPEN",
            wrapper_active=False,
            fired_running_acc=False,
            fired_trend=False,
            fired_dispersion=False,
            fired_three_way=False,
            macro_direction=1,
            macro_surprise=Decimal("0.12"),
            macro_half_life_days=6,
        )
    )
    await db_session.flush()

    out = await get_macro_panel(
        db_session, target, contract_id=contract, algo_id=version
    )

    # FX picks 2026-05-15 (latest <= target)
    assert out["fx_dxy_proxy"] == 0.96
    assert out["fx_gbpusd"] == 1.28
    # XOF/GBP derived from fixed EUR/XOF peg through the picked row's fx_gbpeur=0.86
    assert out["fx_xofgbp"] == pytest.approx(655.957 / 0.86)
    # ENSO must respect the 14-day lag — only 2026-04-01 is old enough
    assert out["enso_oni_month"] == 0.30
    assert out["enso_reference_date"] == "2026-04-01"
    cutoff = target.toordinal() - ENSO_LAG_DAYS
    assert date_cls.fromordinal(cutoff).isoformat() >= out["enso_reference_date"]
    # Ensemble macro context populated
    assert out["macro_direction"] == 1
    assert out["macro_surprise"] == pytest.approx(0.12)
    assert out["macro_half_life_days"] == 6


@pytest.mark.integration
@pytest.mark.asyncio
async def test_macro_panel_legacy_date_has_null_macro_fields(
    db_session: AsyncSession,
) -> None:
    contract = await _seed_chain(db_session, "CAH24")
    legacy = await _seed_version(db_session, "legacy")
    target = date_cls(2024, 6, 15)

    db_session.add(
        PlExternalIndicator(
            date=date_cls(2024, 6, 14),
            fx_dxy_proxy=Decimal("0.90"),
            fx_gbpusd=Decimal("1.25"),
            fx_eurusd=Decimal("0.90"),
            fx_gbpeur=Decimal("0.84"),
        )
    )
    await db_session.flush()

    out = await get_macro_panel(
        db_session, target, contract_id=contract, algo_id=legacy
    )
    assert out["fx_dxy_proxy"] == 0.90
    assert out["macro_direction"] is None
    assert out["macro_surprise"] is None


# ---------------------------------------------------------------------------
# positioning_service
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_positioning_returns_cot_stocks_and_ratio(
    db_session: AsyncSession,
) -> None:
    contract = await _seed_chain(db_session, "CAK26")
    target = date_cls(2026, 5, 15)

    db_session.add(
        PlCotEuWeekly(
            release_date=date_cls(2026, 5, 9),
            report_date=date_cls(2026, 5, 6),
            contract_market="cocoa",
            prod_merc_long=80_000,
            prod_merc_short=60_000,
            m_money_long=40_000,
            m_money_short=22_000,
            other_rept_long=10_000,
            other_rept_short=15_000,
            non_rept_long=5_000,
            non_rept_short=4_000,
            open_interest=200_000,
        )
    )
    db_session.add(
        PlCotUsWeekly(
            release_date=date_cls(2026, 5, 8),
            report_date=date_cls(2026, 5, 5),
            contract_market="cocoa",
            prod_merc_long=70_000,
            prod_merc_short=55_000,
            m_money_long=30_000,
            m_money_short=18_000,
            open_interest=150_000,
        )
    )
    db_session.add(
        PlStockObservation(
            region="eu",
            report_date=date_cls(2026, 5, 13),
            value_native=Decimal("2500000"),  # 2.5M bags
            unit_native="bags_60kg",
            value_tonnes=Decimal("150000"),  # 2.5M × 60 / 1000
            contract_market="cocoa",
            source="barchart_ic345drw",
        )
    )
    db_session.add(
        PlStockObservation(
            region="us",
            report_date=date_cls(2026, 5, 14),
            value_native=Decimal("30000"),
            unit_native="tonnes",
            value_tonnes=Decimal("30000"),
            contract_market="cocoa",
            source="ice_us_report41",
        )
    )
    db_session.add(
        PlContractDataDaily(
            date=target,
            contract_id=contract,
            close=Decimal("8000"),
            volume=1000,
            oi=50000,
        )
    )
    await db_session.flush()

    out = await get_positioning(db_session, target, contract_id=contract)

    # ICE EU COT
    assert out["cot_managed_money_net"] == 18_000
    assert out["cot_producer_merchant_net"] == 20_000
    assert out["cot_open_interest"] == 200_000
    assert out["cot_release_date"] == "2026-05-09"
    # CFTC US COT (new since 2026-05-27)
    assert out["cot_us_managed_money_net"] == 12_000
    assert out["cot_us_producer_merchant_net"] == 15_000
    assert out["cot_us_open_interest"] == 150_000
    assert out["cot_us_release_date"] == "2026-05-08"
    # Stocks in tonnes — single canonical unit, both gauges + ratio
    assert out["stock_eu_tonnes"] == 150_000.0
    assert out["stock_eu_native_value"] == 2_500_000.0
    assert out["stock_eu_native_unit"] == "bags_60kg"
    assert out["stock_eu_report_date"] == "2026-05-13"
    assert out["stock_us_tonnes"] == 30_000.0
    assert out["stock_us_report_date"] == "2026-05-14"
    assert out["stock_eu_us_ratio"] == 5.0  # 150_000 / 30_000


@pytest.mark.integration
@pytest.mark.asyncio
async def test_positioning_falls_back_to_latest_when_target_missing(
    db_session: AsyncSession,
) -> None:
    contract = await _seed_chain(db_session, "CAK26")
    target = date_cls(2026, 5, 16)
    db_session.add(
        PlStockObservation(
            region="eu",
            report_date=date_cls(2026, 5, 13),
            value_native=Decimal("1000000"),
            unit_native="bags_60kg",
            value_tonnes=Decimal("60000"),
            contract_market="cocoa",
            source="barchart_ic345drw",
        )
    )
    db_session.add(
        PlStockObservation(
            region="us",
            report_date=date_cls(2026, 5, 14),
            value_native=Decimal("10000"),
            unit_native="tonnes",
            value_tonnes=Decimal("10000"),
            contract_market="cocoa",
            source="ice_us_report41",
        )
    )
    await db_session.flush()

    out = await get_positioning(db_session, target, contract_id=contract)
    assert out["stock_eu_tonnes"] == 60_000.0
    assert out["stock_us_tonnes"] == 10_000.0
    assert out["stock_eu_us_ratio"] == 6.0  # 60_000 / 10_000


# ---------------------------------------------------------------------------
# ensemble_diagnostics_service
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_diagnostics_returns_orchestrator_row(db_session: AsyncSession) -> None:
    contract = await _seed_chain(db_session, "CAK26")
    version = await _seed_version(db_session, "ensemble_v1_softgate_wrapper")
    target = date_cls(2026, 5, 11)

    db_session.add(
        PlOrchestratorDecision(
            date=target,
            contract_id=contract,
            algorithm_version_id=version,
            soft_gate_decision="OPEN",
            net_score=Decimal("0.78"),
            weights_sum=Decimal("13.0"),
            n_committed_specialists=14,
            decision_wrapped="OPEN",
            wrapper_active=True,
            fired_running_acc=True,
            fired_trend=False,
            fired_dispersion=True,
            fired_three_way=False,
            running_acc_5d=Decimal("0.95"),
            winter_vote_signed=3,
            spring_vote_signed=-2,
        )
    )
    await db_session.flush()

    out = await get_ensemble_diagnostics(
        db_session,
        target,
        contract_id=contract,
        algo_id=version,
        algo_name="ensemble_v1_softgate_wrapper",
    )
    assert out is not None
    assert out["soft_gate_decision"] == "OPEN"
    assert out["decision_wrapped"] == "OPEN"
    assert out["fired_dispersion"] is True
    assert out["winter_vote_signed"] == 3
    assert out["spring_vote_signed"] == -2
    assert out["net_score"] == pytest.approx(0.78)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_diagnostics_returns_none_for_legacy_date(
    db_session: AsyncSession,
) -> None:
    contract = await _seed_chain(db_session, "CAH24")
    version = await _seed_version(db_session, "ensemble_v1_softgate_wrapper")
    target = date_cls(2024, 6, 15)

    out = await get_ensemble_diagnostics(
        db_session,
        target,
        contract_id=contract,
        algo_id=version,
        algo_name="ensemble_v1_softgate_wrapper",
    )
    assert out is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_specialist_votes_with_cluster_mapping(db_session: AsyncSession) -> None:
    contract = await _seed_chain(db_session, "CAK26")
    version = await _seed_version(db_session, "ensemble_v1_softgate_wrapper")
    target = date_cls(2026, 5, 11)

    cluster_map = {
        "wm_h1_a": "winter",
        "wm_h1_b": "winter",
        "sp_h1_a": "spring",
        "sp_h1_b": "spring",
    }
    db_session.add(
        PlAlgorithmConfig(
            algorithm_version_id=version,
            parameter_name="specialist_cluster_map",
            value=json.dumps(cluster_map),
        )
    )

    db_session.add_all(
        [
            PlSpecialistPrediction(
                date=target,
                contract_id=contract,
                algorithm_version_id=version,
                specialist_name="wm_h1_a",
                window_months=12,
                pred="OPEN",
            ),
            PlSpecialistPrediction(
                date=target,
                contract_id=contract,
                algorithm_version_id=version,
                specialist_name="wm_h1_b",
                window_months=12,
                pred="OPEN",
            ),
            PlSpecialistPrediction(
                date=target,
                contract_id=contract,
                algorithm_version_id=version,
                specialist_name="sp_h1_a",
                window_months=12,
                pred="HEDGE",
            ),
            PlSpecialistPrediction(
                date=target,
                contract_id=contract,
                algorithm_version_id=version,
                specialist_name="sp_h1_b",
                window_months=12,
                pred="MONITOR",
            ),
        ]
    )
    await db_session.flush()

    out = await get_specialist_votes(
        db_session,
        target,
        contract_id=contract,
        algo_id=version,
        algo_name="ensemble_v1_softgate_wrapper",
    )
    assert out is not None
    assert len(out["votes"]) == 4
    # Winter cluster: OPEN + OPEN = +2 signed
    assert out["winter_signed"] == 2
    # Spring cluster: HEDGE + MONITOR = -1 + 0 = -1 signed
    assert out["spring_signed"] == -1
    by_name = {v["specialist_name"]: v for v in out["votes"]}
    assert by_name["wm_h1_a"]["cluster"] == "winter"
    assert by_name["sp_h1_b"]["cluster"] == "spring"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_specialist_votes_missing_cluster_map(db_session: AsyncSession) -> None:
    contract = await _seed_chain(db_session, "CAK26")
    version = await _seed_version(db_session, "ensemble_v1_softgate_wrapper")
    target = date_cls(2026, 5, 11)

    db_session.add(
        PlSpecialistPrediction(
            date=target,
            contract_id=contract,
            algorithm_version_id=version,
            specialist_name="wm_h1_a",
            window_months=12,
            pred="OPEN",
        )
    )
    await db_session.flush()

    out = await get_specialist_votes(
        db_session,
        target,
        contract_id=contract,
        algo_id=version,
        algo_name="ensemble_v1_softgate_wrapper",
    )
    assert out is not None
    assert out["votes"][0]["cluster"] == "unmapped"
    # With no mapping, winter/spring sums should be None
    assert out["winter_signed"] is None
    assert out["spring_signed"] is None
