"""Tests for cc-daily-analysis ensemble alignment (Phase 8 refactor).

When an ensemble_v1_softgate_wrapper row exists for (date, contract), the job
must:
  * auto-pin the algorithm_version_id to ensemble's row
  * read ensemble diagnostics and inject them into Call#2 prompt
  * use ensemble's decision_wrapped as final_conclusion (override compute)
  * write the LLM narrative to the ensemble row (not legacy)
  * force LLM decision back to ensemble's if it drifted

NO live LLM calls are made — LLMClient.call is mocked end-to-end.
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.models.pipeline import (
    PlAlgorithmVersion,
    PlContractDataDaily,
    PlDerivedIndicators,
    PlIndicatorDaily,
    PlOrchestratorDecision,
    PlSpecialistPrediction,
)
from app.models.reference import RefCommodity, RefContract, RefExchange
from app.models.signal import PlSignalComponent
from scripts.daily_analysis.db_analysis_engine import DBAnalysisEngine
from scripts.daily_analysis.db_reader import ContextData, DBReader
from scripts.daily_analysis.llm_client import LLMResponse


def _empty_context() -> ContextData:
    """Skip macronews/weather lookups — legacy tables aren't created in the test DB."""
    return ContextData(macronews="", meteotoday="", meteonews="")


# ---------------------------------------------------------------------------
# Fixtures (sync DB — daily_analysis uses sync sessions)
# ---------------------------------------------------------------------------


@pytest.fixture()
def ref_chain(sync_db_session):
    exchange = RefExchange(
        code="IFEU-ens", name="ICE Futures Europe", timezone="Europe/London"
    )
    sync_db_session.add(exchange)
    sync_db_session.flush()

    commodity = RefCommodity(
        code="CC-ens", name="London Cocoa #7", exchange_id=exchange.id
    )
    sync_db_session.add(commodity)
    sync_db_session.flush()

    contract = RefContract(
        commodity_id=commodity.id,
        code="CAK26-ens",
        contract_month="2026-05",
        expiry_date=date(2026, 5, 15),
        is_active=True,
    )
    sync_db_session.add(contract)
    sync_db_session.flush()
    return {"exchange": exchange, "commodity": commodity, "contract": contract}


@pytest.fixture()
def versions(sync_db_session, ref_chain):
    legacy = PlAlgorithmVersion(
        name="legacy",
        version="1.0.1",
        horizon="short_term",
        is_active=True,
        compute_enabled=True,
        description="Legacy",
    )
    ensemble = PlAlgorithmVersion(
        name="ensemble_v1_softgate_wrapper",
        version="1.0.0",
        horizon="short_term",
        is_active=False,
        compute_enabled=True,
        description="Ensemble",
    )
    sync_db_session.add_all([legacy, ensemble])
    sync_db_session.flush()
    return {"legacy": legacy, "ensemble": ensemble}


@pytest.fixture()
def seed_market_data(sync_db_session, ref_chain):
    """Two days of OHLCV + derived indicators so the engine has enough history."""
    contract_id = ref_chain["contract"].id
    today_d = date(2026, 5, 11)
    yest_d = date(2026, 5, 8)
    for d, close in [(yest_d, 3100), (today_d, 3300)]:
        sync_db_session.add(
            PlContractDataDaily(
                date=d,
                contract_id=contract_id,
                close=Decimal(str(close)),
                high=Decimal(str(close + 50)),
                low=Decimal(str(close - 50)),
                volume=4000,
                oi=42000,
                implied_volatility=Decimal("0.55"),
            )
        )
        sync_db_session.add(
            PlDerivedIndicators(
                date=d,
                contract_id=contract_id,
                r1=Decimal("3350"),
                pivot=Decimal("3300"),
                s1=Decimal("3250"),
                ema12=Decimal("3280"),
                ema26=Decimal("3260"),
                macd=Decimal("12.5"),
                macd_signal=Decimal("10.0"),
                rsi_14d=Decimal("58"),
                stochastic_k_14=Decimal("72"),
                stochastic_d_14=Decimal("68"),
                atr=Decimal("110"),
                atr_14d=Decimal("105"),
                bollinger=Decimal("3300"),
                bollinger_upper=Decimal("3420"),
                bollinger_lower=Decimal("3180"),
            )
        )
    sync_db_session.flush()
    return {"today": today_d, "yesterday": yest_d, "contract_id": contract_id}


def _seed_indicator_daily(
    sync_db_session, *, contract_id, date_, algo_id
) -> PlIndicatorDaily:
    """Pre-create the pl_indicator_daily row that compute-indicators would have written."""
    row = PlIndicatorDaily(
        date=date_,
        contract_id=contract_id,
        algorithm_version_id=algo_id,
        rsi_norm=Decimal("0.42"),
        macd_norm=Decimal("0.18"),
        stoch_k_norm=Decimal("0.35"),
        atr_norm=Decimal("0.12"),
        close_pivot_norm=Decimal("0.08"),
        vol_oi_norm=Decimal("0.05"),
        momentum=Decimal("0.10"),
    )
    sync_db_session.add(row)
    # Mandatory signal_component row so the writer's UPDATE doesn't warn.
    sync_db_session.add(
        PlSignalComponent(
            date=date_,
            contract_id=contract_id,
            algorithm_version_id=algo_id,
            indicator_name="macroeco",
            raw_value=Decimal("0.0"),
            normalized_value=Decimal("0.0"),
            weighted_contribution=Decimal("0.0"),
        )
    )
    sync_db_session.flush()
    return row


def _seed_ensemble_decision(
    sync_db_session,
    *,
    contract_id,
    date_,
    ensemble_id,
    decision_wrapped="OPEN",
    fired_dispersion=True,
    wrapper_active=False,
) -> PlOrchestratorDecision:
    row = PlOrchestratorDecision(
        date=date_,
        contract_id=contract_id,
        algorithm_version_id=ensemble_id,
        soft_gate_decision="OPEN",
        net_score=Decimal("0.78"),
        weights_sum=Decimal("11.5"),
        n_committed_specialists=12,
        decision_wrapped=decision_wrapped,
        wrapper_active=wrapper_active,
        fired_running_acc=True,
        fired_trend=False,
        fired_dispersion=fired_dispersion,
        fired_three_way=False,
        running_acc_5d=Decimal("0.95"),
        winter_vote_signed=3,
        spring_vote_signed=-2,
        macro_direction=1,
        macro_surprise=Decimal("0.12"),
        macro_half_life_days=6,
        anomaly_score_z=Decimal("-0.4"),
        prior_open=Decimal("0.55"),
        prior_hedge=Decimal("0.20"),
        prior_monitor=Decimal("0.25"),
    )
    sync_db_session.add(row)
    sync_db_session.flush()
    return row


def _mock_llm_response(text: str) -> LLMResponse:
    return LLMResponse(
        raw_text=text,
        model="gpt-mock",
        input_tokens=100,
        output_tokens=50,
        latency_ms=10,
    )


def _macro_response(macroeco: float = 0.04) -> LLMResponse:
    payload = {
        "date": "11/05/2026",
        "macroeco_bonus": macroeco,
        "eco": "Conditions stables sur les zones cacaoyères, demande chocolat soutenue.",
    }
    return _mock_llm_response(json.dumps(payload))


def _trading_response(decision: str = "OPEN", confiance: int = 4) -> LLMResponse:
    payload = {
        "decision": decision,
        "confiance": confiance,
        "direction": "HAUSSIERE" if decision == "OPEN" else "NEUTRE",
        # US-1 facts/voice: the LLM now emits only a qualitative headline; the
        # numbers/bullets/à-surveiller are rendered from the DB facts by the engine.
        "headline": f"Lecture Compass alignée sur la position {decision}, conviction forte.",
    }
    return _mock_llm_response(json.dumps(payload))


# ---------------------------------------------------------------------------
# DBReader.read_ensemble_diagnostics — direct unit tests
# ---------------------------------------------------------------------------


class TestEnsembleDiagnosticsRead:
    def test_returns_none_when_no_ensemble_row(self, sync_db_session, ref_chain):
        reader = DBReader(sync_db_session)
        result = reader._read_ensemble_diagnostics(
            target_date=date(2024, 6, 15),
            contract_code=ref_chain["contract"].code,
        )
        assert result is None

    def test_returns_populated_diagnostics_when_row_exists(
        self, sync_db_session, ref_chain, versions, seed_market_data
    ):
        _seed_ensemble_decision(
            sync_db_session,
            contract_id=seed_market_data["contract_id"],
            date_=seed_market_data["today"],
            ensemble_id=versions["ensemble"].id,
        )
        reader = DBReader(sync_db_session)
        diag = reader._read_ensemble_diagnostics(
            target_date=seed_market_data["today"],
            contract_code=ref_chain["contract"].code,
        )
        assert diag is not None
        assert diag.decision_wrapped == "OPEN"
        assert diag.soft_gate_decision == "OPEN"
        assert diag.n_committed_specialists == 12
        assert diag.net_score == pytest.approx(0.78)
        assert diag.winter_vote_signed == 3
        assert diag.spring_vote_signed == -2
        assert diag.fired_dispersion is True
        assert diag.wrapper_active is False
        assert diag.macro_direction == 1


# ---------------------------------------------------------------------------
# DBAnalysisEngine.run — ensemble alignment
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("seed_market_data")
class TestEngineEnsembleAlignment:
    def test_aligns_on_ensemble_when_row_exists(
        self, sync_db_session, ref_chain, versions, seed_market_data
    ):
        # Seed indicator_daily row + ensemble orchestrator row
        _seed_indicator_daily(
            sync_db_session,
            contract_id=seed_market_data["contract_id"],
            date_=seed_market_data["today"],
            algo_id=versions["ensemble"].id,
        )
        # Also seed legacy row to prove the engine targets ensemble, not legacy
        _seed_indicator_daily(
            sync_db_session,
            contract_id=seed_market_data["contract_id"],
            date_=seed_market_data["today"],
            algo_id=versions["legacy"].id,
        )
        _seed_ensemble_decision(
            sync_db_session,
            contract_id=seed_market_data["contract_id"],
            date_=seed_market_data["today"],
            ensemble_id=versions["ensemble"].id,
            decision_wrapped="OPEN",
        )

        with (
            patch("scripts.daily_analysis.db_analysis_engine.LLMClient") as MockClient,
            patch.object(DBReader, "_read_context", lambda self, d: _empty_context()),
        ):
            mock_instance = MagicMock()
            mock_instance.provider = "openai"
            mock_instance.call.side_effect = [
                _macro_response(0.04),
                _trading_response("OPEN", 4),
            ]
            MockClient.return_value = mock_instance

            engine = DBAnalysisEngine(sync_db_session)
            result = engine.run(
                target_date=seed_market_data["today"],
                contract_code=ref_chain["contract"].code,
                data_date=seed_market_data["today"],
            )

        assert result.ensemble_aligned is True
        assert result.final_conclusion == "OPEN", (
            "final_conclusion must be ensemble.decision_wrapped"
        )
        assert result.trading.decision == "OPEN"
        # The cached version id must now point to ensemble (writer scoped here)
        assert engine._algorithm_version_id_cache == versions["ensemble"].id

        # Call #2 prompt must have used the ensemble builder — verify by
        # checking the second prompt is the redacted "LECTURE COMPASS DU JOUR"
        # variant (not the legacy composite-score prompt).
        second_prompt = mock_instance.call.call_args_list[1].args[0]
        assert "LECTURE COMPASS DU JOUR" in second_prompt
        assert "verdict Compass" in second_prompt
        # The redacted block must carry the VOCABULAIRE INTERDIT block so the
        # LLM knows it must NOT leak any of these tokens into the conclusion.
        assert "VOCABULAIRE STRICTEMENT INTERDIT" in second_prompt
        # The OLD diagnostic lines that previously exposed cluster scores
        # and detector state must no longer appear as positive instructions.
        # (They show up inside the INTERDIT list as forbidden words — that's
        # the only place they should appear now.)
        assert "Cluster Winter (régime bear-dominant)" not in second_prompt
        assert "Cluster Spring (régime bull/transition)" not in second_prompt
        assert "Filet de sécurité (wrapper) actif" not in second_prompt
        assert 'Détecteur "précision récente"' not in second_prompt
        assert "DECISION_WRAPPED" not in second_prompt  # template var resolved

        # The writer UPDATE must have hit the ensemble row, not legacy
        from sqlalchemy import text as sql_text

        ensemble_after = sync_db_session.execute(
            sql_text("""
                SELECT decision, conclusion FROM pl_indicator_daily
                WHERE date = :d AND contract_id = :c AND algorithm_version_id = :v
            """),
            {
                "d": seed_market_data["today"],
                "c": seed_market_data["contract_id"],
                "v": versions["ensemble"].id,
            },
        ).fetchone()
        assert ensemble_after is not None
        assert ensemble_after.decision == "OPEN"
        assert ensemble_after.conclusion is not None
        # US-1 facts/voice: conclusion = LLM headline + deterministically rendered
        # fact-bullets + à-surveiller (numbers come from the DB, not the model).
        assert ensemble_after.conclusion.startswith(
            "> Lecture Compass alignée sur la position OPEN"
        )
        assert "Le CLOSE s'établit à" in ensemble_after.conclusion
        assert "> A SURVEILLER AUJOURD'HUI:" in ensemble_after.conclusion

        legacy_after = sync_db_session.execute(
            sql_text("""
                SELECT decision, conclusion FROM pl_indicator_daily
                WHERE date = :d AND contract_id = :c AND algorithm_version_id = :v
            """),
            {
                "d": seed_market_data["today"],
                "c": seed_market_data["contract_id"],
                "v": versions["legacy"].id,
            },
        ).fetchone()
        # Legacy row must be untouched by this run
        assert legacy_after.decision is None
        assert legacy_after.conclusion is None

    def test_legacy_path_when_no_ensemble_row(
        self, sync_db_session, ref_chain, versions, seed_market_data
    ):
        # Only legacy row (no orchestrator decision)
        _seed_indicator_daily(
            sync_db_session,
            contract_id=seed_market_data["contract_id"],
            date_=seed_market_data["today"],
            algo_id=versions["legacy"].id,
        )

        with (
            patch("scripts.daily_analysis.db_analysis_engine.LLMClient") as MockClient,
            patch.object(DBReader, "_read_context", lambda self, d: _empty_context()),
        ):
            mock_instance = MagicMock()
            mock_instance.provider = "openai"
            mock_instance.call.side_effect = [
                _macro_response(0.0),
                _trading_response("MONITOR", 3),
            ]
            MockClient.return_value = mock_instance

            engine = DBAnalysisEngine(sync_db_session)
            result = engine.run(
                target_date=seed_market_data["today"],
                contract_code=ref_chain["contract"].code,
                data_date=seed_market_data["today"],
            )

        assert result.ensemble_aligned is False
        # final_conclusion comes from compute_decision on the legacy row (whichever
        # threshold the score lands in — just assert it's NOT "OPEN" forced).
        assert result.trading.decision == "MONITOR"

        second_prompt = mock_instance.call.call_args_list[1].args[0]
        # Legacy prompt: no ensemble vocab
        assert "spécialistes" not in second_prompt

    def test_explicit_version_flag_overrides_ensemble(
        self, sync_db_session, ref_chain, versions, seed_market_data
    ):
        # Ensemble row exists, but operator pins to legacy explicitly
        _seed_indicator_daily(
            sync_db_session,
            contract_id=seed_market_data["contract_id"],
            date_=seed_market_data["today"],
            algo_id=versions["legacy"].id,
        )
        _seed_ensemble_decision(
            sync_db_session,
            contract_id=seed_market_data["contract_id"],
            date_=seed_market_data["today"],
            ensemble_id=versions["ensemble"].id,
        )

        with (
            patch("scripts.daily_analysis.db_analysis_engine.LLMClient") as MockClient,
            patch.object(DBReader, "_read_context", lambda self, d: _empty_context()),
        ):
            mock_instance = MagicMock()
            mock_instance.provider = "openai"
            mock_instance.call.side_effect = [
                _macro_response(0.0),
                _trading_response("HEDGE", 3),
            ]
            MockClient.return_value = mock_instance

            engine = DBAnalysisEngine(sync_db_session, algorithm_version_name="legacy")
            result = engine.run(
                target_date=seed_market_data["today"],
                contract_code=ref_chain["contract"].code,
                data_date=seed_market_data["today"],
            )

        assert result.ensemble_aligned is False
        assert engine._algorithm_version_id_cache == versions["legacy"].id

    def test_llm_decision_drift_forced_to_ensemble(
        self, sync_db_session, ref_chain, versions, seed_market_data
    ):
        # Ensemble says OPEN but the LLM (mock) returns HEDGE — engine must override.
        _seed_indicator_daily(
            sync_db_session,
            contract_id=seed_market_data["contract_id"],
            date_=seed_market_data["today"],
            algo_id=versions["ensemble"].id,
        )
        _seed_ensemble_decision(
            sync_db_session,
            contract_id=seed_market_data["contract_id"],
            date_=seed_market_data["today"],
            ensemble_id=versions["ensemble"].id,
            decision_wrapped="OPEN",
        )

        with (
            patch("scripts.daily_analysis.db_analysis_engine.LLMClient") as MockClient,
            patch.object(DBReader, "_read_context", lambda self, d: _empty_context()),
        ):
            mock_instance = MagicMock()
            mock_instance.provider = "openai"
            mock_instance.call.side_effect = [
                _macro_response(0.04),
                _trading_response("HEDGE", 5),  # LLM drifts
            ]
            MockClient.return_value = mock_instance

            engine = DBAnalysisEngine(sync_db_session)
            result = engine.run(
                target_date=seed_market_data["today"],
                contract_code=ref_chain["contract"].code,
                data_date=seed_market_data["today"],
            )

        # Engine forces back to ensemble.decision_wrapped
        assert result.trading.decision == "OPEN"


# ---------------------------------------------------------------------------
# Specialist predictions seeding (used by readers in some test variants)
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("seed_market_data")
class TestEnsembleAlignmentWithVotes:
    def test_diagnostics_block_renders_redacted_signal_view(
        self, sync_db_session, ref_chain, versions, seed_market_data
    ):
        """Replaces the previous winter/spring/dispersion check. After the
        engine-redaction patch, the Call#2 prompt no longer exposes cluster
        scores, soft-gate/wrapper state, or detector fires — those are
        explicit leaks. The prompt instead carries a small set of safe
        diagnostics (decision, conviction, convergence count, macro direction)
        plus a strict VOCABULAIRE INTERDIT block."""
        _seed_indicator_daily(
            sync_db_session,
            contract_id=seed_market_data["contract_id"],
            date_=seed_market_data["today"],
            algo_id=versions["ensemble"].id,
        )
        _seed_ensemble_decision(
            sync_db_session,
            contract_id=seed_market_data["contract_id"],
            date_=seed_market_data["today"],
            ensemble_id=versions["ensemble"].id,
            decision_wrapped="OPEN",
            fired_dispersion=True,
            wrapper_active=False,
        )
        # 14 specialist rows (not directly read by daily-analysis but proves
        # the ensemble row joins on contract correctly)
        for i in range(4):
            sync_db_session.add(
                PlSpecialistPrediction(
                    id=uuid.uuid4(),
                    date=seed_market_data["today"],
                    contract_id=seed_market_data["contract_id"],
                    algorithm_version_id=versions["ensemble"].id,
                    specialist_name=f"specialist_{i}",
                    window_months=12,
                    pred="OPEN",
                )
            )
        sync_db_session.flush()

        with (
            patch("scripts.daily_analysis.db_analysis_engine.LLMClient") as MockClient,
            patch.object(DBReader, "_read_context", lambda self, d: _empty_context()),
        ):
            mock_instance = MagicMock()
            mock_instance.provider = "openai"
            mock_instance.call.side_effect = [
                _macro_response(0.04),
                _trading_response("OPEN", 4),
            ]
            MockClient.return_value = mock_instance

            engine = DBAnalysisEngine(sync_db_session)
            engine.run(
                target_date=seed_market_data["today"],
                contract_code=ref_chain["contract"].code,
                data_date=seed_market_data["today"],
            )

        second_prompt = mock_instance.call.call_args_list[1].args[0]
        # Redacted diagnostics carry the qualitative conviction label only
        # (no raw net_score, no committed count) — the LLM gets enough to
        # judge but cannot quote engine internals back.
        assert "Conviction Compass intrinsèque" in second_prompt
        # 12 committed + net_score=1.0 → adhesion=0.926 → "forte"
        assert "forte" in second_prompt
        # The new confidence rubric is in the prompt
        assert "ÉVALUATION DE LA CONFIANCE" in second_prompt
        # The VOCABULAIRE STRICTEMENT INTERDIT block must reach the LLM
        # (otherwise the LLM has no instruction to stop leaking).
        assert "VOCABULAIRE STRICTEMENT INTERDIT" in second_prompt
        # The OLD positive instructions exposing cluster scores and detectors
        # are gone.
        assert "Cluster Winter (régime bear-dominant)" not in second_prompt
        assert "Cluster Spring (régime bull/transition)" not in second_prompt
        assert 'Détecteur "divergence régimes"' not in second_prompt
