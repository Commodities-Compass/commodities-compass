"""DB-first analysis engine — replaces Sheets-dependent analysis_engine.py.

Flow:
  1. Read technicals + context from DB (pl_* tables)
  2. Compute FINAL_INDICATOR using app.engine.composite (no Sheets recalc)
  3. LLM Call #1 → MACROECO BONUS + ECO
  4. LLM Call #2 → DECISION / CONFIANCE / DIRECTION / CONCLUSION
  5. Write results to pl_indicator_daily + aud_llm_call

The 528-line IndicatorWriter (HISTORIQUE row-shift) is eliminated entirely.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.engine.composite import compute_decision, compute_momentum, compute_score
from app.engine.types import AlgorithmConfig, LEGACY_V1
from scripts.daily_analysis.db_reader import DBReader, PipelineInputs
from scripts.daily_analysis.llm_client import LLMClient, LLMResponse
from scripts.daily_analysis.output_parser import (
    MacroAnalysisOutput,
    TradingDecisionOutput,
    parse_macro_output,
    parse_trading_output,
)
from scripts.daily_analysis.prompts import build_call1_prompt, build_call2_prompt

logger = logging.getLogger(__name__)


@dataclass
class AnalysisResult:
    """Full output of the DB-first daily analysis pipeline."""

    macro: MacroAnalysisOutput
    final_indicator: float
    final_conclusion: str
    trading: TradingDecisionOutput
    call1_response: LLMResponse
    call2_response: LLMResponse
    target_date: date


class DBAnalysisEngine:
    """Orchestrates the daily analysis pipeline using DB + engine."""

    def __init__(
        self,
        session: Session,
        *,
        algorithm_config: AlgorithmConfig = LEGACY_V1,
        llm_provider: str = "openai",
        llm_model: str | None = None,
        call1_temperature: float = 1.0,
        call2_temperature: float = 0.7,
    ) -> None:
        self._session = session
        self._reader = DBReader(session)
        self._llm = LLMClient(provider=llm_provider, model=llm_model)
        self._config = algorithm_config

        self._call1_temperature = call1_temperature
        self._call2_temperature = call2_temperature

    def run(
        self,
        target_date: date,
        contract_code: str = "CAK26",
        *,
        dry_run: bool = False,
    ) -> AnalysisResult:
        """Execute the full pipeline for a given date."""

        # --- Step 1: Read inputs from DB ---
        logger.info("Step 1: Reading data from database...")
        inputs = self._reader.read_all(target_date, contract_code=contract_code)
        self._log_inputs(inputs)

        # --- Step 2: LLM Call #1 — Macro/Weather analysis ---
        logger.info("Step 2: LLM Call #1 — Macro/Weather analysis...")
        call1_prompt = build_call1_prompt(
            macronews=inputs.context.macronews,
            meteotoday=inputs.context.meteotoday,
            meteonews=inputs.context.meteonews,
        )
        call1_response = self._llm.call(
            call1_prompt,
            temperature=self._call1_temperature,
            max_tokens=2048,
        )
        macro = parse_macro_output(call1_response.raw_text)
        logger.info(
            "Call #1 result: MACROECO_BONUS=%.2f ECO=%s",
            macro.macroeco_bonus,
            macro.eco[:80],
        )

        # --- Step 3: Compute FINAL_INDICATOR from DB (no Sheets!) ---
        logger.info("Step 3: Computing FINAL_INDICATOR from engine...")
        final_indicator, final_conclusion = self._compute_final_indicator(
            target_date,
            contract_code,
            macro.macroeco_bonus,
        )
        logger.info(
            "Engine result: FINAL_INDICATOR=%.4f CONCLUSION=%s",
            final_indicator,
            final_conclusion,
        )

        # --- Step 4: LLM Call #2 — Trading decision ---
        logger.info("Step 4: LLM Call #2 — Trading decision...")
        call2_prompt = build_call2_prompt(
            technicals_today=inputs.technicals.today,
            technicals_yesterday=inputs.technicals.yesterday,
            final_indicator=final_indicator,
            final_conclusion=final_conclusion,
        )
        call2_response = self._llm.call(
            call2_prompt,
            temperature=self._call2_temperature,
            max_tokens=2048,
        )
        trading = parse_trading_output(call2_response.raw_text)
        logger.info(
            "Call #2 result: DECISION=%s CONFIANCE=%d DIRECTION=%s",
            trading.decision,
            trading.confiance,
            trading.direction,
        )

        # --- Step 5: Write results to DB ---
        if not dry_run:
            logger.info("Step 5: Writing results to database...")
            self._write_results(
                target_date=target_date,
                contract_code=contract_code,
                macro=macro,
                final_indicator=final_indicator,
                final_conclusion=final_conclusion,
                trading=trading,
                call1_response=call1_response,
                call2_response=call2_response,
            )
        else:
            logger.info("Step 5: [DRY RUN] Skipping DB write")

        return AnalysisResult(
            macro=macro,
            final_indicator=final_indicator,
            final_conclusion=final_conclusion,
            trading=trading,
            call1_response=call1_response,
            call2_response=call2_response,
            target_date=target_date,
        )

    def _compute_final_indicator(
        self,
        target_date: date,
        contract_code: str,
        macroeco_bonus: float,
    ) -> tuple[float, str]:
        """Compute composite score from normalized indicators in DB.

        Reads the latest pl_indicator_daily row for z-scores,
        computes momentum from the previous day's linear indicator,
        then applies the NEW CHAMPION power formula.
        """
        # Get last 2 days of normalized scores
        result = self._session.execute(
            text("""
                SELECT
                    i.date,
                    i.rsi_norm, i.macd_norm, i.stoch_k_norm,
                    i.atr_norm, i.close_pivot_norm, i.vol_oi_norm,
                    i.indicator_value, i.momentum
                FROM pl_indicator_daily i
                JOIN ref_contract c ON i.contract_id = c.id
                WHERE i.date <= :target_date
                ORDER BY i.date DESC
                LIMIT 2
            """),
            {"target_date": target_date},
        )
        rows = result.fetchall()

        if not rows:
            logger.warning("No indicator data found — returning default MONITOR")
            return 0.0, "MONITOR"

        today = dict(zip(result.keys(), rows[0]))

        # Get momentum: compare today's linear indicator vs yesterday's
        momentum = 0.0
        if len(rows) >= 2:
            yesterday = dict(zip(result.keys(), rows[1]))
            today_linear = today.get("indicator_value")
            yesterday_linear = yesterday.get("indicator_value")
            if today_linear is not None and yesterday_linear is not None:
                momentum = compute_momentum(
                    float(today_linear), float(yesterday_linear)
                )

        # Apply power formula
        score = compute_score(
            rsi_norm=_to_float(today.get("rsi_norm")),
            macd_norm=_to_float(today.get("macd_norm")),
            stoch_norm=_to_float(today.get("stoch_k_norm")),
            atr_norm=_to_float(today.get("atr_norm")),
            cp_norm=_to_float(today.get("close_pivot_norm")),
            voi_norm=_to_float(today.get("vol_oi_norm")),
            momentum=momentum,
            macroeco=macroeco_bonus,
            config=self._config,
        )
        decision = compute_decision(score, self._config)
        return score, decision

    def _write_results(
        self,
        *,
        target_date: date,
        contract_code: str,
        macro: MacroAnalysisOutput,
        final_indicator: float,
        final_conclusion: str,
        trading: TradingDecisionOutput,
        call1_response: LLMResponse,
        call2_response: LLMResponse,
    ) -> None:
        """Write analysis results to pl_indicator_daily + aud_llm_call."""
        # Get contract_id and algorithm_version_id
        contract_row = self._session.execute(
            text("SELECT id FROM ref_contract WHERE code = :code"),
            {"code": contract_code},
        ).fetchone()
        if not contract_row:
            logger.error("Contract %s not found", contract_code)
            return
        contract_id = contract_row[0]

        algo_row = self._session.execute(
            text("SELECT id FROM pl_algorithm_version WHERE is_active = true LIMIT 1"),
        ).fetchone()
        algo_version_id = algo_row[0] if algo_row else None

        # Update pl_indicator_daily with LLM outputs
        result = self._session.execute(
            text("""
                UPDATE pl_indicator_daily
                SET macroeco_bonus = :macroeco_bonus,
                    macroeco_score = :macroeco_score,
                    eco = :eco,
                    final_indicator = :final_indicator,
                    decision = :decision,
                    confidence = :confidence,
                    direction = :direction,
                    conclusion = :conclusion,
                    momentum = :momentum
                WHERE date = :target_date
                  AND contract_id = :contract_id
                  AND algorithm_version_id = :algo_version_id
            """),
            {
                "macroeco_bonus": macro.macroeco_bonus,
                "macroeco_score": 1.0 + macro.macroeco_bonus,
                "eco": macro.eco,
                "final_indicator": final_indicator,
                "decision": trading.decision,
                "confidence": trading.confiance,
                "direction": trading.direction,
                "conclusion": trading.conclusion,
                "momentum": 0.0,  # will be computed properly once we have prior row
                "target_date": target_date,
                "contract_id": contract_id,
                "algo_version_id": algo_version_id,
            },
        )
        if result.rowcount == 0:
            logger.warning(
                "pl_indicator_daily UPDATE matched 0 rows for date=%s contract=%s — "
                "row may not exist yet (compute-indicators not run?)",
                target_date,
                contract_code,
            )

        # Update macroeco signal component with LLM-provided values
        from app.engine.composite import _power_term

        macroeco_contribution = _power_term(
            self._config.p, self._config.q, macro.macroeco_bonus
        )
        sc_result = self._session.execute(
            text("""
                UPDATE pl_signal_component
                SET raw_value = :raw_value,
                    normalized_value = :normalized_value,
                    weighted_contribution = :weighted_contribution
                WHERE date = :target_date
                  AND contract_id = :contract_id
                  AND indicator_name = 'macroeco'
                  AND algorithm_version_id = :algo_version_id
            """),
            {
                "raw_value": macro.macroeco_bonus,
                "normalized_value": macro.macroeco_bonus,
                "weighted_contribution": round(macroeco_contribution, 6),
                "target_date": target_date,
                "contract_id": contract_id,
                "algo_version_id": algo_version_id,
            },
        )
        if sc_result.rowcount == 0:
            logger.warning(
                "pl_signal_component macroeco UPDATE matched 0 rows for date=%s",
                target_date,
            )

        # Write LLM audit trail — create parent pipeline run first
        pipeline_run_id = uuid.uuid4()
        self._session.execute(
            text("""
                INSERT INTO aud_pipeline_run
                    (id, pipeline_name, started_at, status, created_at)
                VALUES
                    (:id, :name, NOW(), :status, NOW())
            """),
            {
                "id": pipeline_run_id,
                "name": "daily-analysis-db",
                "status": "success",
            },
        )
        for call_num, response in [(1, call1_response), (2, call2_response)]:
            self._session.execute(
                text("""
                    INSERT INTO aud_llm_call
                        (id, pipeline_run_id, provider, model,
                         prompt, response, input_tokens, output_tokens,
                         latency_ms)
                    VALUES
                        (:id, :pipeline_run_id, :provider, :model,
                         :prompt, :response, :input_tokens, :output_tokens,
                         :latency_ms)
                """),
                {
                    "id": uuid.uuid4(),
                    "pipeline_run_id": pipeline_run_id,
                    "provider": "openai",
                    "model": response.model,
                    "prompt": f"[daily_analysis_call_{call_num}]",
                    "response": response.raw_text,
                    "input_tokens": response.input_tokens,
                    "output_tokens": response.output_tokens,
                    "latency_ms": response.latency_ms,
                },
            )

        self._session.commit()
        logger.info("Results written to pl_indicator_daily + 2 aud_llm_call rows")

    def _log_inputs(self, inputs: PipelineInputs) -> None:
        t = inputs.technicals
        c = inputs.context
        logger.info("--- Pipeline inputs ---")
        logger.info("  Date: %s", t.today_date)
        logger.info("  TOD variables: %d", len(t.today))
        logger.info("  YES variables: %d", len(t.yesterday))
        logger.info("  MACRONEWS: %d chars", len(c.macronews))
        logger.info("  METEONEWS: %d chars", len(c.meteonews))
        logger.info("  METEOTODAY: %d chars", len(c.meteotoday))


def _to_float(value: object) -> float:
    """Convert DB value to float, defaulting to 0.0 for None/NaN."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0
