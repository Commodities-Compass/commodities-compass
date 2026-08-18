"""The adapter row — regime+judge projected into pl_indicator_daily.

Two things must hold for the bascule to be safe, and both are easy to get
silently wrong:

  * the FRENCH row must exist even though the judge writes English, because the
    YTD series pins ``language='fr'`` and would otherwise score an empty set;
  * English prose must NEVER be stored under ``language='fr'``.

Everything regime does not compute (z-scores, macro bonus) stays NULL — never
0.0, which is a valid score.
"""

from __future__ import annotations

import uuid
from datetime import date as date_cls
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline import PlAlgorithmVersion, PlContractDataDaily
from app.models.reference import RefCommodity, RefContract, RefExchange

_SESSION = date_cls(2026, 8, 17)


async def _seed_contract(db: AsyncSession, code: str = "CAU26") -> uuid.UUID:
    ex = RefExchange(code=f"ICE-{code}", name="ICE", timezone="UTC")
    db.add(ex)
    await db.flush()
    com = RefCommodity(code=f"CC-{code}", name="Cocoa", exchange_id=ex.id)
    db.add(com)
    await db.flush()
    contract = RefContract(
        commodity_id=com.id, code=code, contract_month=code[-3:], is_active=True
    )
    db.add(contract)
    await db.flush()
    db.add(
        PlContractDataDaily(
            date=_SESSION, contract_id=contract.id, close=Decimal("8000")
        )
    )
    await db.flush()
    return contract.id


async def _seed_version(db: AsyncSession) -> uuid.UUID:
    row = PlAlgorithmVersion(
        name="regime",
        version="1.0.0",
        horizon="short_term",
        algorithm_kind="ml_regime",
        serving_rank=None,  # inert: writing the row exposes nothing
    )
    db.add(row)
    await db.flush()
    return row.id


async def _seed_regime(
    db: AsyncSession, contract_id: uuid.UUID, version_id: uuid.UUID
) -> None:
    await db.execute(
        text("""
            INSERT INTO pl_regime_shadow
                (id, date, contract_id, algorithm_version_id,
                 decision, regime, specialist, prob_up)
            VALUES (gen_random_uuid(), :d, :c, :a, 'OPEN', 'bull', 'bull', 0.6123)
        """),
        {"d": _SESSION, "c": str(contract_id), "a": str(version_id)},
    )


async def _seed_judge(
    db: AsyncSession,
    contract_id: uuid.UUID,
    version_id: uuid.UUID,
    *,
    final_decision: str = "HEDGE",
    changed: bool = True,
) -> None:
    await db.execute(
        text("""
            INSERT INTO pl_judge_shadow
                (id, date, contract_id, algorithm_version_id,
                 base_source, base_decision, base_confidence, regime_source_date,
                 regime, specialist, prob_up, judge_direction, judge_stance,
                 judge_confidence, is_anomaly, evidence, drift_summary,
                 disconfirming_case, key_risk, n_days_window, final_decision,
                 changed, rationale, prompt_version, model_id)
            VALUES (gen_random_uuid(), :d, :c, :a,
                 'regime', 'OPEN', 3.0, :d,
                 'bull', 'bull', 0.6123, 'DOWN', 'CONTRARIAN',
                 4, false, :evidence, 'Rain deficit widening in Ivory Coast.',
                 'A demand shock would invalidate this.', 'Harmattan onset', 3,
                 :final, :changed, 'Macro drift contradicts the technical call.',
                 'judge_prompt_v2', 'o4-mini')
        """),
        {
            "d": _SESSION,
            "c": str(contract_id),
            "a": str(version_id),
            "evidence": '["quote one", "quote two"]',
            "final": final_decision,
            "changed": changed,
        },
    )


async def _rows(db: AsyncSession, version_id: uuid.UUID) -> dict[str, Any]:
    result = await db.execute(
        text(
            "SELECT language, decision, confidence, direction, eco, conclusion, "
            "confidence_rationale, rsi_norm, macd_norm, macroeco_bonus, "
            "macroeco_score, contract_id "
            "FROM pl_indicator_daily WHERE algorithm_version_id = :a"
        ),
        {"a": str(version_id)},
    )
    return {row.language: row for row in result}


async def _run_adapter(db: AsyncSession, version_id: uuid.UUID) -> int:
    from scripts.regime_shadow.indicator_adapter import write_adapter_row

    return await db.run_sync(
        lambda sync_session: write_adapter_row(
            sync_session, session_date=_SESSION, algorithm_version_id=version_id
        )
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_writes_both_languages(db_session: AsyncSession) -> None:
    contract = await _seed_contract(db_session)
    version = await _seed_version(db_session)
    await _seed_regime(db_session, contract, version)
    await _seed_judge(db_session, contract, version)

    written = await _run_adapter(db_session, version)

    assert written == 2
    rows = await _rows(db_session, version)
    assert set(rows) == {"fr", "en"}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_french_row_carries_the_decision_for_the_ytd_walk(
    db_session: AsyncSession,
) -> None:
    """The YTD series pins language='fr' — without this row it scores nothing."""
    contract = await _seed_contract(db_session)
    version = await _seed_version(db_session)
    await _seed_regime(db_session, contract, version)
    await _seed_judge(db_session, contract, version, final_decision="HEDGE")

    await _run_adapter(db_session, version)

    fr = (await _rows(db_session, version))["fr"]
    assert fr.decision == "HEDGE"  # the judge's fused call, not regime's OPEN
    assert fr.confidence == Decimal("4.00")
    assert fr.direction == "DOWN"
    assert str(fr.contract_id) == str(contract)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_english_prose_never_lands_on_the_french_row(
    db_session: AsyncSession,
) -> None:
    """The invariant the whole codebase holds — no cross-language narrative."""
    contract = await _seed_contract(db_session)
    version = await _seed_version(db_session)
    await _seed_regime(db_session, contract, version)
    await _seed_judge(db_session, contract, version)

    await _run_adapter(db_session, version)
    rows = await _rows(db_session, version)

    assert rows["fr"].conclusion is None
    assert rows["fr"].eco is None
    assert rows["fr"].confidence_rationale is None

    assert rows["en"].conclusion is not None
    assert "Macro drift contradicts" in rows["en"].conclusion
    assert "quote one" in rows["en"].conclusion
    assert "regime bull" in rows["en"].conclusion
    assert rows["en"].eco is not None
    assert "Rain deficit" in rows["en"].eco
    assert "Harmattan" in rows["en"].eco
    assert rows["en"].confidence_rationale == "A demand shock would invalidate this."


@pytest.mark.integration
@pytest.mark.asyncio
async def test_uncomputed_columns_stay_null(db_session: AsyncSession) -> None:
    """NULL means 'not computed'. 0.0 is a valid z-score and would corrupt averages."""
    contract = await _seed_contract(db_session)
    version = await _seed_version(db_session)
    await _seed_regime(db_session, contract, version)
    await _seed_judge(db_session, contract, version)

    await _run_adapter(db_session, version)
    fr = (await _rows(db_session, version))["fr"]

    assert fr.rsi_norm is None
    assert fr.macd_norm is None
    assert fr.macroeco_bonus is None
    assert fr.macroeco_score is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_projects_regime_alone_when_judge_is_absent(
    db_session: AsyncSession,
) -> None:
    """--no-judge backfills, or an LLM outage: the technical call still lands."""
    contract = await _seed_contract(db_session)
    version = await _seed_version(db_session)
    await _seed_regime(db_session, contract, version)

    written = await _run_adapter(db_session, version)

    assert written == 2
    rows = await _rows(db_session, version)
    assert rows["fr"].decision == "OPEN"  # regime's own call
    assert rows["fr"].confidence is None
    assert rows["en"].conclusion is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_is_idempotent(db_session: AsyncSession) -> None:
    """A re-run must update in place, never duplicate the (date, algo, lang) key."""
    contract = await _seed_contract(db_session)
    version = await _seed_version(db_session)
    await _seed_regime(db_session, contract, version)
    await _seed_judge(db_session, contract, version, final_decision="OPEN")

    await _run_adapter(db_session, version)
    await _run_adapter(db_session, version)

    rows = await _rows(db_session, version)
    assert len(rows) == 2
    assert rows["fr"].decision == "OPEN"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_missing_regime_row_raises(db_session: AsyncSession) -> None:
    """A silent no-op would surface as an empty dashboard the next morning."""
    from scripts.regime_shadow.indicator_adapter import AdapterSourceMissingError

    await _seed_contract(db_session)
    version = await _seed_version(db_session)

    with pytest.raises(AdapterSourceMissingError):
        await _run_adapter(db_session, version)
