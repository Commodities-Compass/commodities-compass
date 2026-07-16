"""US-3b-ii: language threading + translated-row materialisation (D3-EN-rows).

The default-language (fr) run owns the numbers; an en run copies every number
from the fr row and overrides only the 3 prose fields (eco / conclusion /
confidence_rationale) with native English. Figures are therefore byte-identical
across languages by construction — proven here end-to-end (LLM mocked).
"""

from __future__ import annotations

import json
import sys
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text

from app.models.pipeline import (
    PlAlgorithmVersion,
    PlContractDataDaily,
    PlDerivedIndicators,
    PlIndicatorDaily,
)
from app.models.reference import RefCommodity, RefContract, RefExchange
from app.models.signal import PlSignalComponent
from scripts.daily_analysis.db_analysis_engine import (
    AnalysisWriteError,
    DBAnalysisEngine,
)
from scripts.daily_analysis.db_reader import ContextData, DBReader
from scripts.daily_analysis.llm_client import LLMResponse
from scripts.daily_analysis.main import _parse_args


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _empty_context() -> ContextData:
    return ContextData(macronews="", meteotoday="", meteonews="")


@pytest.fixture()
def ref_chain(sync_db_session):
    exchange = RefExchange(
        code="IFEU-lang", name="ICE Futures Europe", timezone="Europe/London"
    )
    sync_db_session.add(exchange)
    sync_db_session.flush()
    commodity = RefCommodity(
        code="CC-lang", name="London Cocoa #7", exchange_id=exchange.id
    )
    sync_db_session.add(commodity)
    sync_db_session.flush()
    contract = RefContract(
        commodity_id=commodity.id,
        code="CAK26-lang",
        contract_month="2026-05",
        expiry_date=date(2026, 5, 15),
        is_active=True,
    )
    sync_db_session.add(contract)
    sync_db_session.flush()
    return {"contract": contract}


@pytest.fixture()
def legacy_version(sync_db_session, ref_chain):
    version = PlAlgorithmVersion(
        name="legacy",
        version="1.0.1",
        horizon="short_term",
        is_active=True,
        compute_enabled=True,
        description="Legacy",
    )
    sync_db_session.add(version)
    sync_db_session.flush()
    return version


@pytest.fixture()
def seed_market_data(sync_db_session, ref_chain):
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
                r2=Decimal("3400"),
                pivot=Decimal("3300"),
                s1=Decimal("3250"),
                s2=Decimal("3200"),
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


def _seed_fr_zscore_row(sync_db_session, *, contract_id, date_, algo_id) -> None:
    """The fr row compute-indicators would have written (z-scores, language=fr)."""
    sync_db_session.add(
        PlIndicatorDaily(
            date=date_,
            contract_id=contract_id,
            algorithm_version_id=algo_id,
            language="fr",
            rsi_norm=Decimal("0.42"),
            macd_norm=Decimal("0.18"),
            stoch_k_norm=Decimal("0.35"),
            atr_norm=Decimal("0.12"),
            close_pivot_norm=Decimal("0.08"),
            vol_oi_norm=Decimal("0.05"),
            momentum=Decimal("0.10"),
        )
    )
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


def _resp(text_: str) -> LLMResponse:
    return LLMResponse(
        raw_text=text_,
        model="gpt-mock",
        input_tokens=100,
        output_tokens=50,
        latency_ms=10,
    )


def _macro(eco: str, macroeco: float = 0.04) -> LLMResponse:
    return _resp(
        json.dumps({"date": "11/05/2026", "macroeco_bonus": macroeco, "eco": eco})
    )


def _trading(decision: str, headline: str) -> LLMResponse:
    return _resp(
        json.dumps(
            {
                "decision": decision,
                "confiance": 4,
                "direction": "NEUTRE" if decision == "MONITOR" else "HAUSSIERE",
                "headline": headline,
            }
        )
    )


def _run(sync_db_session, contract_code, day, *, language, macro_resp, trading_resp):
    with (
        patch("scripts.daily_analysis.db_analysis_engine.LLMClient") as MockClient,
        patch.object(DBReader, "_read_context", lambda self, d: _empty_context()),
    ):
        inst = MagicMock()
        inst.provider = "openai"
        inst.call.side_effect = [macro_resp, trading_resp]
        MockClient.return_value = inst
        engine = DBAnalysisEngine(sync_db_session)
        return engine.run(
            target_date=day,
            contract_code=contract_code,
            data_date=day,
            language=language,
        )


def _fetch_row(sync_db_session, *, contract_id, day, algo_id, language):
    return sync_db_session.execute(
        text("""
            SELECT decision, confidence, direction, final_indicator, macroeco_bonus,
                   rsi_norm, eco, conclusion, confidence_rationale, language
            FROM pl_indicator_daily
            WHERE date = :d AND contract_id = :c
              AND algorithm_version_id = :v AND language = :lang
        """),
        {"d": day, "c": contract_id, "v": algo_id, "lang": language},
    ).fetchone()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("seed_market_data")
class TestTranslatedRowMaterialisation:
    def test_en_run_copies_fr_numbers_and_writes_en_prose(
        self, sync_db_session, ref_chain, legacy_version, seed_market_data
    ):
        contract_id = seed_market_data["contract_id"]
        code = ref_chain["contract"].code
        day = seed_market_data["today"]
        _seed_fr_zscore_row(
            sync_db_session,
            contract_id=contract_id,
            date_=day,
            algo_id=legacy_version.id,
        )

        # 1) FR run owns the numbers.
        _run(
            sync_db_session,
            code,
            day,
            language="fr",
            macro_resp=_macro("Conditions stables sur les zones cacaoyères."),
            trading_resp=_trading(
                "MONITOR", "Lecture prudente, la fenêtre reste à surveiller."
            ),
        )
        fr = _fetch_row(
            sync_db_session,
            contract_id=contract_id,
            day=day,
            algo_id=legacy_version.id,
            language="fr",
        )
        assert fr is not None
        assert fr.decision == "MONITOR"

        # 2) EN run — its own LLM says OPEN, but the row must copy fr's MONITOR.
        _run(
            sync_db_session,
            code,
            day,
            language="en",
            macro_resp=_macro("Steady conditions across the cocoa belt."),
            trading_resp=_trading(
                "OPEN", "Cautious read, the window ahead stays worth watching."
            ),
        )
        en = _fetch_row(
            sync_db_session,
            contract_id=contract_id,
            day=day,
            algo_id=legacy_version.id,
            language="en",
        )
        assert en is not None, "EN run must have materialised its own row"

        # --- Number parity: every figure copied from the fr row ---
        assert en.decision == fr.decision == "MONITOR"
        assert en.confidence == fr.confidence
        assert en.direction == fr.direction
        assert en.final_indicator == fr.final_indicator
        assert en.macroeco_bonus == fr.macroeco_bonus
        assert en.rsi_norm == fr.rsi_norm

        # --- Prose: native English, distinct from FR ---
        assert en.eco == "Steady conditions across the cocoa belt."
        assert en.eco != fr.eco
        assert en.conclusion.startswith(
            "> Cautious read, the window ahead stays worth watching."
        )
        assert "> TO WATCH TODAY:" in en.conclusion
        assert en.conclusion != fr.conclusion
        assert "A SURVEILLER" not in en.conclusion

        # --- FR row untouched by the EN run ---
        assert fr.eco == "Conditions stables sur les zones cacaoyères."
        assert "> A SURVEILLER AUJOURD'HUI:" in fr.conclusion

    def test_en_run_fails_loud_when_fr_row_absent(
        self, sync_db_session, ref_chain, legacy_version, seed_market_data
    ):
        # An `en` z-score row exists (so step-3 compute succeeds) but NO `fr`
        # row does — the copy has nothing to source. The translated UPSERT must
        # fail loud rather than silently write an EN row with no numbers.
        contract_id = seed_market_data["contract_id"]
        code = ref_chain["contract"].code
        day = seed_market_data["today"]
        sync_db_session.add(
            PlIndicatorDaily(
                date=day,
                contract_id=contract_id,
                algorithm_version_id=legacy_version.id,
                language="en",
                rsi_norm=Decimal("0.42"),
                macd_norm=Decimal("0.18"),
                stoch_k_norm=Decimal("0.35"),
                atr_norm=Decimal("0.12"),
                close_pivot_norm=Decimal("0.08"),
                vol_oi_norm=Decimal("0.05"),
                momentum=Decimal("0.10"),
            )
        )
        sync_db_session.flush()

        with pytest.raises(AnalysisWriteError, match="source 'fr' row must exist"):
            _run(
                sync_db_session,
                code,
                day,
                language="en",
                macro_resp=_macro("Steady conditions."),
                trading_resp=_trading("MONITOR", "Cautious read into the window."),
            )

    def test_fr_rerun_does_not_clobber_en_row(
        self, sync_db_session, ref_chain, legacy_version, seed_market_data
    ):
        contract_id = seed_market_data["contract_id"]
        code = ref_chain["contract"].code
        day = seed_market_data["today"]
        _seed_fr_zscore_row(
            sync_db_session,
            contract_id=contract_id,
            date_=day,
            algo_id=legacy_version.id,
        )
        _run(
            sync_db_session,
            code,
            day,
            language="fr",
            macro_resp=_macro("Contexte FR initial."),
            trading_resp=_trading("MONITOR", "Lecture FR initiale."),
        )
        _run(
            sync_db_session,
            code,
            day,
            language="en",
            macro_resp=_macro("English context."),
            trading_resp=_trading("MONITOR", "English read."),
        )
        # FR re-run with new prose — the language filter must isolate it.
        _run(
            sync_db_session,
            code,
            day,
            language="fr",
            macro_resp=_macro("Contexte FR mis a jour."),
            trading_resp=_trading("MONITOR", "Lecture FR mise a jour."),
        )
        en = _fetch_row(
            sync_db_session,
            contract_id=contract_id,
            day=day,
            algo_id=legacy_version.id,
            language="en",
        )
        assert en.eco == "English context.", "EN prose must survive an FR re-run"
        assert en.conclusion.startswith("> English read.")


# ---------------------------------------------------------------------------
# CLI flag
# ---------------------------------------------------------------------------


class TestLanguageFlag:
    def test_default_is_fr(self):
        with patch.object(sys, "argv", ["daily-analysis"]):
            args = _parse_args()
        assert args.language == "fr"

    def test_accepts_en(self):
        with patch.object(sys, "argv", ["daily-analysis", "--language", "en"]):
            args = _parse_args()
        assert args.language == "en"

    def test_rejects_unknown_language(self):
        with patch.object(sys, "argv", ["daily-analysis", "--language", "de"]):
            with pytest.raises(SystemExit):
                _parse_args()
