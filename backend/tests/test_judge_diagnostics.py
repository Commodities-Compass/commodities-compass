"""Judge diagnostics — the Campaign-6 replacement for the ensemble conviction panel.

The endpoint is the commercial successor of ``/ensemble-diagnostics`` +
``/specialist-votes``: same "Conviction" row of the offer matrix, different
machinery. These tests pin the two things that make it correct rather than
merely present:

  * ``rationale`` never leaves the database. It is the deterministic fuse trace,
    written for the judge's own replay, and the product decision was that it is
    judge-only — not in the brief prompt, not on the wire.
  * a missing overlay degrades to the technical call rather than to a fabricated
    neutral verdict. The regime row IS the decision; the judge is an overlay on
    top of it, and reporting "the macro layer said nothing" is honest where
    reporting a synthetic MONITOR would not be.
"""

from __future__ import annotations

import uuid
from datetime import date as date_cls
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline import (
    PlAlgorithmVersion,
    PlIndicatorDaily,
    PlJudgeShadow,
    PlRegimeShadow,
)
from app.models.reference import RefCommodity, RefContract, RefExchange
from app.services.judge_diagnostics_service import get_judge_diagnostics

SESSION = date_cls(2026, 8, 17)

# The exact string the judge writes into pl_judge_shadow.rationale — a fuse trace,
# not prose. If it ever appears in an API payload, the audit trail has leaked
# into the product.
FUSE_TRACE = "ABSTAIN HEDGE->MONITOR: judge contradicts at conf=3"


async def _seed_contract(db: AsyncSession, code: str = "CAU26") -> uuid.UUID:
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


async def _seed_version(db: AsyncSession, name: str = "regime") -> uuid.UUID:
    v = PlAlgorithmVersion(
        name=name,
        version="1.0.0",
        horizon="short_term",
        is_active=False,
        compute_enabled=False,
        algorithm_kind="ml_regime",
        description="Test regime",
    )
    db.add(v)
    await db.flush()
    return v.id


async def _seed_regime(
    db: AsyncSession,
    contract_id: uuid.UUID,
    algo_id: uuid.UUID,
    *,
    decision: str = "HEDGE",
) -> None:
    db.add(
        PlRegimeShadow(
            date=SESSION,
            contract_id=contract_id,
            algorithm_version_id=algo_id,
            decision=decision,
            regime="high_vol_down",
            specialist="spec_hv_down",
            prob_up=Decimal("0.3820"),
        )
    )
    await db.flush()


async def _seed_judge(
    db: AsyncSession,
    contract_id: uuid.UUID,
    algo_id: uuid.UUID,
    *,
    evidence: list | None = None,
) -> None:
    db.add(
        PlJudgeShadow(
            date=SESSION,
            contract_id=contract_id,
            algorithm_version_id=algo_id,
            base_source="regime",
            base_decision="HEDGE",
            base_confidence=Decimal("0.62"),
            base_direction_label="bearish",
            regime_source_date=SESSION,
            regime="high_vol_down",
            specialist="spec_hv_down",
            prob_up=Decimal("0.3820"),
            judge_direction="UP",
            judge_stance="ABSTAIN",
            judge_confidence=3,
            is_anomaly=False,
            evidence=evidence
            if evidence is not None
            else [{"quote": "Ghana arrivals"}],
            drift_summary="Rainfall improving across the western belt.",
            disconfirming_case="Grindings still soft in Europe.",
            key_risk="A harmattan onset would reverse the read.",
            weather_series=[1, 2, 3],
            weather_delta=Decimal("-0.400"),
            drift_notes=["note"],
            n_days_window=5,
            final_decision="MONITOR",
            changed=True,
            rationale=FUSE_TRACE,
            prompt_version="judge_prompt_v2",
            model_id="o4-mini",
        )
    )
    await db.flush()


async def _seed_served_row(
    db: AsyncSession,
    contract_id: uuid.UUID,
    algo_id: uuid.UUID,
    *,
    language: str,
    confidence: int,
    rationale: str,
) -> None:
    db.add(
        PlIndicatorDaily(
            date=SESSION,
            contract_id=contract_id,
            algorithm_version_id=algo_id,
            language=language,
            decision="MONITOR",
            confidence=confidence,
            confidence_rationale=rationale,
        )
    )
    await db.flush()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_returns_none_without_a_regime_row(db_session: AsyncSession) -> None:
    """No technical call means no panel — the caller maps this to 404."""
    contract_id = await _seed_contract(db_session, "CAU26")
    algo_id = await _seed_version(db_session)

    out = await get_judge_diagnostics(
        db_session,
        SESSION,
        contract_id=contract_id,
        algo_id=algo_id,
        algo_name="regime",
    )
    assert out is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_payload_carries_both_layers(db_session: AsyncSession) -> None:
    contract_id = await _seed_contract(db_session, "CAZ26")
    algo_id = await _seed_version(db_session)
    await _seed_regime(db_session, contract_id, algo_id)
    await _seed_judge(db_session, contract_id, algo_id)
    await _seed_served_row(
        db_session,
        contract_id,
        algo_id,
        language="fr",
        confidence=3,
        rationale="Météo porteuse, grindings en retrait.",
    )

    out = await get_judge_diagnostics(
        db_session,
        SESSION,
        contract_id=contract_id,
        algo_id=algo_id,
        algo_name="regime",
    )
    assert out is not None

    # Layer 1+2
    assert out["regime"] == "high_vol_down"
    assert out["specialist"] == "spec_hv_down"
    assert out["prob_up"] == pytest.approx(0.382)
    assert out["base_decision"] == "HEDGE"

    # Layer 3
    assert out["judge_stance"] == "ABSTAIN"
    assert out["judge_confidence"] == 3
    assert out["changed"] is True
    assert out["final_decision"] == "MONITOR"
    assert out["key_risk"].startswith("A harmattan")
    assert out["n_days_window"] == 5

    # Served narrative
    assert out["confidence"] == 3
    assert out["confidence_rationale"] == "Météo porteuse, grindings en retrait."


@pytest.mark.integration
@pytest.mark.asyncio
async def test_rationale_never_reaches_the_payload(db_session: AsyncSession) -> None:
    """The fuse trace is audit material — judge-only, by explicit decision.

    Asserted on the whole serialised payload rather than on a missing key: a
    future refactor could just as easily leak it inside ``evidence`` or a
    concatenated summary, and the key check would still pass.
    """
    contract_id = await _seed_contract(db_session, "CAH27")
    algo_id = await _seed_version(db_session)
    await _seed_regime(db_session, contract_id, algo_id)
    await _seed_judge(db_session, contract_id, algo_id)

    out = await get_judge_diagnostics(
        db_session,
        SESSION,
        contract_id=contract_id,
        algo_id=algo_id,
        algo_name="regime",
    )
    assert out is not None
    assert "rationale" not in out
    assert FUSE_TRACE not in str(out)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_missing_overlay_degrades_to_the_technical_call(
    db_session: AsyncSession,
) -> None:
    """No judge row: report the base call, do not invent a neutral verdict."""
    contract_id = await _seed_contract(db_session, "CAK27")
    algo_id = await _seed_version(db_session)
    await _seed_regime(db_session, contract_id, algo_id, decision="OPEN")

    out = await get_judge_diagnostics(
        db_session,
        SESSION,
        contract_id=contract_id,
        algo_id=algo_id,
        algo_name="regime",
    )
    assert out is not None
    assert out["base_decision"] == "OPEN"
    # The served decision falls back to the base call, not to MONITOR.
    assert out["final_decision"] == "OPEN"
    assert out["judge_stance"] is None
    assert out["judge_confidence"] is None
    assert out["changed"] is None
    assert out["evidence"] == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_confidence_rationale_is_read_in_the_requested_language(
    db_session: AsyncSession,
) -> None:
    """Each edition carries its own natively-composed sentence.

    Borrowing the other language's rationale would put French prose under an
    English headline — the exact failure the native-composition decision exists
    to prevent.
    """
    contract_id = await _seed_contract(db_session, "CAN27")
    algo_id = await _seed_version(db_session)
    await _seed_regime(db_session, contract_id, algo_id)
    await _seed_judge(db_session, contract_id, algo_id)
    await _seed_served_row(
        db_session, contract_id, algo_id, language="fr", confidence=3, rationale="FR"
    )
    await _seed_served_row(
        db_session, contract_id, algo_id, language="en", confidence=4, rationale="EN"
    )

    fr = await get_judge_diagnostics(
        db_session,
        SESSION,
        contract_id=contract_id,
        algo_id=algo_id,
        algo_name="regime",
        language="fr",
    )
    en = await get_judge_diagnostics(
        db_session,
        SESSION,
        contract_id=contract_id,
        algo_id=algo_id,
        algo_name="regime",
        language="en",
    )
    assert fr is not None and en is not None
    assert (fr["confidence_rationale"], fr["confidence"]) == ("FR", 3)
    assert (en["confidence_rationale"], en["confidence"]) == ("EN", 4)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_unenriched_row_yields_no_narrative_rather_than_a_borrowed_one(
    db_session: AsyncSession,
) -> None:
    """cc-regime-brief has not run yet: score and caption are simply absent."""
    contract_id = await _seed_contract(db_session, "CAU27")
    algo_id = await _seed_version(db_session)
    await _seed_regime(db_session, contract_id, algo_id)
    await _seed_judge(db_session, contract_id, algo_id)

    out = await get_judge_diagnostics(
        db_session,
        SESSION,
        contract_id=contract_id,
        algo_id=algo_id,
        algo_name="regime",
    )
    assert out is not None
    assert out["confidence"] is None
    assert out["confidence_rationale"] is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_malformed_evidence_entries_are_dropped(
    db_session: AsyncSession,
) -> None:
    """Evidence is LLM-written JSONB — a stray string would render as an empty card."""
    contract_id = await _seed_contract(db_session, "CAZ27")
    algo_id = await _seed_version(db_session)
    await _seed_regime(db_session, contract_id, algo_id)
    await _seed_judge(
        db_session,
        contract_id,
        algo_id,
        evidence=[{"quote": "kept"}, "dropped", 42, {"quote": "kept too"}],
    )

    out = await get_judge_diagnostics(
        db_session,
        SESSION,
        contract_id=contract_id,
        algo_id=algo_id,
        algo_name="regime",
    )
    assert out is not None
    assert out["evidence"] == [{"quote": "kept"}, {"quote": "kept too"}]


# ---------------------------------------------------------------------------
# The endpoint guard
# ---------------------------------------------------------------------------


@pytest.fixture
def authenticated():
    """Stand in for a logged-in user for the duration of one test.

    The shared ``client`` fixture only overrides the DB dependency, so an
    endpoint test that does not set this hits real Auth0 verification and gets a
    401. It passed locally purely because another module had left an override in
    place — order-dependent, and CI ran it in a different order.
    """
    from app.core.auth import get_current_user
    from app.main import app

    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "auth0|judge-diagnostics-test",
        "email": "t@example.com",
        "name": "T",
        "permissions": [],
    }
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_endpoint_is_silent_while_regime_is_not_served(
    client, db_session: AsyncSession, authenticated
) -> None:
    """Before the flip, the panel must not appear.

    The endpoint keys off the SERVED algorithm, not off the presence of shadow
    rows — regime writes every night while carrying no ``serving_rank``, and a
    conviction panel describing a decision nobody is shown would contradict the
    signal on screen.
    """
    contract_id = await _seed_contract(db_session, "CAX26")
    regime_id = await _seed_version(db_session, "regime")
    await _seed_regime(db_session, contract_id, regime_id)

    # Ensemble is the served head; regime carries no rank (the shadow state).
    ensemble = PlAlgorithmVersion(
        name="ensemble_v1_softgate_wrapper",
        version="1.0.0",
        horizon="short_term",
        is_active=False,
        serving_rank=1,
    )
    db_session.add(ensemble)
    await db_session.flush()

    r = await client.get(
        "/v1/dashboard/judge-diagnostics", params={"target_date": SESSION.isoformat()}
    )
    assert r.status_code == 404
