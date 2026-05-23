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

from app.engine.composite import compute_decision, compute_score
from app.utils.converters import to_float
from app.engine.types import AlgorithmConfig, LEGACY_V1
from scripts.daily_analysis.db_reader import (
    DBReader,
    PipelineInputs,
)
from scripts.daily_analysis.llm_client import LLMClient, LLMResponse
from scripts.daily_analysis.output_parser import (
    MacroAnalysisOutput,
    TradingDecisionOutput,
    parse_macro_output,
    parse_trading_output,
)
from scripts.daily_analysis.prompts import (
    build_call1_prompt,
    build_call2_prompt,
    build_call2_prompt_ensemble,
)

logger = logging.getLogger(__name__)


class AlgorithmVersionNotFoundError(RuntimeError):
    """Raised when --algorithm-version targets a name with no matching row.

    Fail-loud per `.claude/rules/pipeline-error-handling.md`. The job exits
    non-zero so the operator notices and fixes the deploy.yml flag rather
    than silently falling back to is_active=TRUE (which would defeat the
    purpose of pinning).
    """


class AnalysisWriteError(RuntimeError):
    """Raised when the LLM analysis run writes nothing to pl_indicator_daily.

    Fail-loud per `.claude/rules/pipeline-error-handling.md`. A run that
    succeeds at LLM calls but cannot persist results (because the target
    row doesn't exist — typically compute-indicators hasn't run yet) must
    NOT exit 0. Otherwise the cron green-checkmark masks a silent failure.
    """


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
    # True when this run aligned itself on the ensemble row for the date
    # (diagnostics injected into Call#2, narrative + decision written to the
    # ensemble row). False = legacy path (historical date or no ensemble row).
    ensemble_aligned: bool = False


class DBAnalysisEngine:
    """Orchestrates the daily analysis pipeline using DB + engine."""

    def __init__(
        self,
        session: Session,
        *,
        algorithm_config: AlgorithmConfig = LEGACY_V1,
        algorithm_version_name: str | None = None,
        llm_provider: str = "openai",
        llm_model: str | None = None,
        call1_temperature: float = 1.0,
        call2_temperature: float = 0.7,
    ) -> None:
        self._session = session
        self._reader = DBReader(session)
        self._llm = LLMClient(provider=llm_provider, model=llm_model)
        self._config = algorithm_config
        # When set, _resolve_algorithm_version_id() targets the named version
        # instead of resolving via is_active=TRUE. Prevents LLM overwrites of
        # other versions' rows (e.g., C5 ensemble) when this version is the
        # active one. See P2-daily-analysis-version-flag.md.
        self._algorithm_version_name = algorithm_version_name

        # Cached `algorithm_version_id` — resolved once per engine instance to
        # avoid (1) a second DB roundtrip on every run() and (2) a race where
        # `is_active` rotates between the read in _compute_final_indicator and
        # the write in _write_results.
        self._algorithm_version_id_cache: uuid.UUID | None = None
        self._algorithm_version_id_resolved: bool = False

        self._call1_temperature = call1_temperature
        self._call2_temperature = call2_temperature

    def _resolve_algorithm_version_id(self) -> uuid.UUID | None:
        """Return the algorithm_version_id this job is allowed to UPDATE.

        Cached after first call to ensure read+write target the same row even
        if `is_active` is rotated mid-run.

        Behavior:
          * If `algorithm_version_name` was provided at init time, look up the
            row by name and return its id even when `is_active=FALSE`. Raise
            `AlgorithmVersionNotFoundError` if no row exists (fail-loud).
          * Otherwise (backward compat), return the row where `is_active=TRUE`
            or None if no active version exists.
        """
        if self._algorithm_version_id_resolved:
            return self._algorithm_version_id_cache

        if self._algorithm_version_name is not None:
            row = self._session.execute(
                text(
                    "SELECT id FROM pl_algorithm_version WHERE name = :name "
                    "ORDER BY is_active DESC, created_at DESC LIMIT 1"
                ),
                {"name": self._algorithm_version_name},
            ).fetchone()
            if row is None:
                raise AlgorithmVersionNotFoundError(
                    f"No row in pl_algorithm_version with name='{self._algorithm_version_name}'. "
                    "Check the --algorithm-version flag in deploy.yml or DB state."
                )
            self._algorithm_version_id_cache = row[0]
        else:
            row = self._session.execute(
                text(
                    "SELECT id FROM pl_algorithm_version WHERE is_active = true LIMIT 1"
                ),
            ).fetchone()
            self._algorithm_version_id_cache = row[0] if row else None

        self._algorithm_version_id_resolved = True
        return self._algorithm_version_id_cache

    def run(
        self,
        target_date: date,
        contract_code: str,
        *,
        dry_run: bool = False,
    ) -> AnalysisResult:
        """Execute the full pipeline for a given date.

        Behavior depends on whether the ensemble produced a decision for the
        (date, contract):
          * Ensemble row present (default for 2025-12-15 onward): the run
            "aligns" itself on ensemble — Call#2 receives the ensemble
            diagnostics block, the decision is pinned to ``decision_wrapped``,
            and the narrative is written to the ensemble row. This is what
            keeps the dashboard, brief and podcast coherent with ensemble.
          * No ensemble row: legacy path unchanged — composite final_indicator
            drives the decision, narrative is written to the legacy row.

        ``--algorithm-version`` CLI flag still works as an explicit override:
        when set, the run targets that named version regardless of ensemble
        presence (used for historical backfills or operator interventions).
        """

        # --- Step 1: Read inputs from DB ---
        logger.info("Step 1: Reading data from database...")
        inputs = self._reader.read_all(target_date, contract_code=contract_code)
        self._log_inputs(inputs)

        # Auto-align on ensemble when present AND no explicit override was set.
        ensemble = inputs.ensemble
        align_on_ensemble = (
            ensemble is not None and self._algorithm_version_name is None
        )
        if align_on_ensemble:
            # Pin the cached algorithm_version_id to ensemble's row so reads
            # and writes target it (instead of the legacy is_active=TRUE row).
            self._algorithm_version_id_cache = uuid.UUID(ensemble.algorithm_version_id)
            self._algorithm_version_id_resolved = True
            logger.info(
                "Ensemble row detected for %s — aligning narrative on ensemble decision %s",
                target_date,
                ensemble.decision_wrapped,
            )

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
        # Always compute it — even on ensemble dates — because it keeps
        # populating ``final_indicator`` + ``macroeco_score`` columns and
        # the macroeco signal component. The ``final_conclusion`` is only
        # used to drive Call#2 when no ensemble decision is available.
        logger.info("Step 3: Computing FINAL_INDICATOR from engine...")
        final_indicator, computed_conclusion = self._compute_final_indicator(
            target_date,
            contract_code,
            macro.macroeco_bonus,
        )
        if align_on_ensemble and ensemble is not None:
            final_conclusion = ensemble.decision_wrapped
            logger.info(
                "Engine result: FINAL_INDICATOR=%.4f COMPUTED=%s (overridden by ensemble → %s)",
                final_indicator,
                computed_conclusion,
                final_conclusion,
            )
        else:
            final_conclusion = computed_conclusion
            logger.info(
                "Engine result: FINAL_INDICATOR=%.4f CONCLUSION=%s",
                final_indicator,
                final_conclusion,
            )

        # --- Step 4: LLM Call #2 — Trading decision ---
        logger.info("Step 4: LLM Call #2 — Trading decision...")
        if align_on_ensemble and ensemble is not None:
            call2_prompt = build_call2_prompt_ensemble(
                technicals_today=inputs.technicals.today,
                technicals_yesterday=inputs.technicals.yesterday,
                ensemble=ensemble,
            )
        else:
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

        # Sanity-check: when aligning on ensemble, the LLM MUST echo the
        # ensemble decision. If it drifts (rare with the new prompt), log a
        # warning and force the decision back to the ensemble value so the
        # dashboard and the audit trail stay coherent.
        if align_on_ensemble and ensemble is not None:
            if trading.decision != ensemble.decision_wrapped:
                logger.warning(
                    "LLM returned decision=%s but ensemble said %s — forcing alignment",
                    trading.decision,
                    ensemble.decision_wrapped,
                )
                trading = TradingDecisionOutput(
                    decision=ensemble.decision_wrapped,
                    confiance=trading.confiance,
                    direction=trading.direction,
                    conclusion=trading.conclusion,
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
            ensemble_aligned=align_on_ensemble,
        )

    def _compute_final_indicator(
        self,
        target_date: date,
        contract_code: str,
        macroeco_bonus: float,
    ) -> tuple[float, str]:
        """Recompute composite score with fresh macroeco from LLM.

        Reads z-scores and momentum from pl_indicator_daily (written by
        compute-indicators). Only recomputes final_indicator and decision
        — does NOT recompute or overwrite technical indicators.

        Scoped to ``algorithm_version_id`` (same resolution rule as the
        UPDATE in ``_write_results``). When multiple versions coexist for
        the same date (e.g. C5 ensemble + legacy), the legacy run must
        read the legacy z-scores, not an arbitrary version's. Without this
        filter ``LIMIT 1`` is non-deterministic.
        """
        algo_version_id = self._resolve_algorithm_version_id()
        if algo_version_id is None:
            # No active version at all → can't read z-scores deterministically.
            # Fail-loud per .claude/rules/pipeline-error-handling.md.
            raise RuntimeError(
                "No active algorithm_version_id resolved — cannot read "
                "z-scores deterministically. Check pl_algorithm_version "
                "for is_active=true rows, or pass --algorithm-version."
            )

        result = self._session.execute(
            text("""
                SELECT
                    i.rsi_norm, i.macd_norm, i.stoch_k_norm,
                    i.atr_norm, i.close_pivot_norm, i.vol_oi_norm,
                    i.momentum
                FROM pl_indicator_daily i
                JOIN ref_contract c ON i.contract_id = c.id
                WHERE i.date = :target_date
                  AND c.code = :contract_code
                  AND i.algorithm_version_id = :algo_version_id
                LIMIT 1
            """),
            {
                "target_date": target_date,
                "contract_code": contract_code,
                "algo_version_id": algo_version_id,
            },
        )
        row = result.fetchone()

        if not row:
            raise RuntimeError(
                f"No indicator data found for {target_date} / {contract_code} "
                f"/ algo_version={algo_version_id} — compute-indicators may "
                f"not have run for this version. Cannot produce trading signal."
            )

        today = dict(zip(result.keys(), row))

        score = compute_score(
            rsi_norm=to_float(today.get("rsi_norm")),
            macd_norm=to_float(today.get("macd_norm")),
            stoch_norm=to_float(today.get("stoch_k_norm")),
            atr_norm=to_float(today.get("atr_norm")),
            cp_norm=to_float(today.get("close_pivot_norm")),
            voi_norm=to_float(today.get("vol_oi_norm")),
            momentum=to_float(today.get("momentum")),
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

        algo_version_id = self._resolve_algorithm_version_id()

        # Update pl_indicator_daily with LLM outputs only.
        # Technical indicators (momentum, z-scores) are owned by compute-indicators
        # and must not be overwritten here.
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
                    conclusion = :conclusion
                WHERE date = :target_date
                  AND contract_id = :contract_id
                  AND algorithm_version_id = :algo_version_id
            """),
            {
                "macroeco_bonus": macro.macroeco_bonus,
                "macroeco_score": 1.0 + macro.macroeco_bonus
                if macro.macroeco_bonus is not None
                else None,
                "eco": macro.eco,
                "final_indicator": final_indicator,
                "decision": trading.decision,
                "confidence": trading.confiance,
                "direction": trading.direction,
                "conclusion": trading.conclusion,
                "target_date": target_date,
                "contract_id": contract_id,
                "algo_version_id": algo_version_id,
            },
        )
        if result.rowcount == 0:
            raise AnalysisWriteError(
                f"pl_indicator_daily UPDATE matched 0 rows for date={target_date} "
                f"contract={contract_code} algorithm_version_id={algo_version_id} "
                "— compute-indicators must run first to create the row. "
                "Re-run cc-compute-indicators, then re-run cc-daily-analysis."
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
                    "provider": self._llm.provider,
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
