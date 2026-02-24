"""Pipeline orchestrator for the daily analysis.

Sequence:
  1. Read data from Google Sheets (TECHNICALS, BIBLIO_ALL, METEO_ALL)
  2. LLM Call #1 → MACROECO BONUS + ECO
  3. Write to INDICATOR sheet (values + formulas + row-shift)
  4. Read back FINAL INDICATOR + CONCLUSION
  5. LLM Call #2 → DECISION / CONFIANCE / DIRECTION / CONCLUSION
  6. Write to TECHNICALS sheet
"""

import logging
from dataclasses import dataclass
from datetime import datetime

from scripts.daily_analysis.config import (
    INDICATOR_SHEETS,
    TECHNICALS_SHEETS,
    get_credentials_json,
)
from scripts.daily_analysis.indicator_writer import IndicatorWriter, ReadBackResult
from scripts.daily_analysis.llm_client import LLMClient, LLMResponse
from scripts.daily_analysis.output_parser import (
    MacroAnalysisOutput,
    TradingDecisionOutput,
    parse_macro_output,
    parse_trading_output,
)
from scripts.daily_analysis.prompts import build_call1_prompt, build_call2_prompt
from scripts.daily_analysis.sheets_reader import PipelineInputs, SheetsReader

logger = logging.getLogger(__name__)


@dataclass
class AnalysisResult:
    """Full output of the daily analysis pipeline."""

    macro: MacroAnalysisOutput
    indicator_readback: ReadBackResult
    trading: TradingDecisionOutput
    call1_response: LLMResponse
    call2_response: LLMResponse
    target_date: datetime
    technicals_row: int


class AnalysisEngine:
    """Orchestrates the full daily analysis pipeline."""

    def __init__(
        self,
        *,
        sheet_mode: str = "staging",
        llm_provider: str = "openai",
        llm_model: str | None = None,
        call1_temperature: float = 1.0,
        call2_temperature: float = 0.7,
    ) -> None:
        creds = get_credentials_json()
        self.reader = SheetsReader(creds)
        self.indicator_writer = IndicatorWriter(creds)
        self.llm = LLMClient(provider=llm_provider, model=llm_model)

        self.sheet_mode = sheet_mode
        self.indicator_sheet = INDICATOR_SHEETS[sheet_mode]
        self.technicals_sheet = TECHNICALS_SHEETS[sheet_mode]
        self.call1_temperature = call1_temperature
        self.call2_temperature = call2_temperature

    def run(
        self,
        target_date: datetime,
        *,
        dry_run: bool = False,
        force: bool = False,
    ) -> AnalysisResult:
        """Execute the full pipeline for a given date."""
        date_str = target_date.strftime("%m/%d/%Y")

        # --- Step 1: Read all inputs from production sheets ---
        logger.info("Step 1: Reading data from Google Sheets...")
        inputs = self.reader.read_all(target_date)
        self._log_inputs(inputs)

        # --- Step 2: LLM Call #1 — Macro/Weather analysis ---
        logger.info("Step 2: LLM Call #1 — Macro/Weather analysis...")
        call1_prompt = build_call1_prompt(
            macronews=inputs.context.macronews,
            meteotoday=inputs.context.meteotoday,
            meteonews=inputs.context.meteonews,
        )
        call1_response = self.llm.call(
            call1_prompt,
            temperature=self.call1_temperature,
            max_tokens=2048,
        )
        macro = parse_macro_output(call1_response.raw_text)
        logger.info(
            "Call #1 result: MACROECO_BONUS=%.2f ECO=%s",
            macro.macroeco_bonus,
            macro.eco[:80],
        )

        # --- Step 3: Write to INDICATOR + row-shift + read back ---
        logger.info("Step 3: Writing to INDICATOR sheet + row-shift...")
        readback = self.indicator_writer.execute(
            sheet_name=self.indicator_sheet,
            macroeco_bonus=macro.macroeco_bonus,
            eco=macro.eco,
            dry_run=dry_run,
            force=force,
            target_date_str=date_str,
        )
        logger.info(
            "INDICATOR read-back: FINAL_INDICATOR=%.4f CONCLUSION=%s (row %d)",
            readback.final_indicator,
            readback.conclusion,
            readback.row_number,
        )

        # --- Step 4: LLM Call #2 — Trading decision ---
        logger.info("Step 4: LLM Call #2 — Trading decision...")
        call2_prompt = build_call2_prompt(
            technicals_today=inputs.technicals.today,
            technicals_yesterday=inputs.technicals.yesterday,
            final_indicator=readback.final_indicator,
            final_conclusion=readback.conclusion,
        )
        call2_response = self.llm.call(
            call2_prompt,
            temperature=self.call2_temperature,
            max_tokens=2048,
        )
        trading = parse_trading_output(call2_response.raw_text)
        logger.info(
            "Call #2 result: DECISION=%s CONFIANCE=%d DIRECTION=%s",
            trading.decision,
            trading.confiance,
            trading.direction,
        )

        # --- Step 5: Write to TECHNICALS sheet ---
        logger.info("Step 5: Writing to TECHNICALS sheet...")
        self._write_technicals(
            row=inputs.technicals.today_row_number,
            trading=trading,
            dry_run=dry_run,
            force=force,
        )

        return AnalysisResult(
            macro=macro,
            indicator_readback=readback,
            trading=trading,
            call1_response=call1_response,
            call2_response=call2_response,
            target_date=target_date,
            technicals_row=inputs.technicals.today_row_number,
        )

    def _write_technicals(
        self,
        row: int,
        trading: TradingDecisionOutput,
        *,
        dry_run: bool = False,
        force: bool = False,
    ) -> None:
        """Write DECISION/CONFIANCE/DIRECTION/SCORE to TECHNICALS columns AO-AR."""
        logger.info(
            "TECHNICALS row %d: AO=%s AP=%d AQ=%s AR=%s",
            row,
            trading.decision,
            trading.confiance,
            trading.direction,
            trading.conclusion[:60],
        )

        # Idempotency: check if AO (DECISION) is already filled
        if not force and not dry_run:
            existing = self.indicator_writer._get_values(
                f"{self.technicals_sheet}!AO{row}"
            )
            vals = existing.get("values", [])
            if vals and vals[0] and str(vals[0][0]).strip():
                raise RuntimeError(
                    f"TECHNICALS row {row} already has DECISION={vals[0][0]}. "
                    f"Use --force to overwrite."
                )

        if dry_run:
            logger.info("[DRY RUN] Skipping TECHNICALS write")
            return

        # AO=DECISION, AP=CONFIANCE, AQ=DIRECTION, AR=SCORE(conclusion)
        values = [
            [
                trading.decision,
                trading.confiance,
                trading.direction,
                trading.conclusion,
            ]
        ]
        self.indicator_writer._update_values(
            f"{self.technicals_sheet}!AO{row}:AR{row}",
            values,
        )
        logger.info("TECHNICALS row %d written", row)

    def _log_inputs(self, inputs: PipelineInputs) -> None:
        """Log a summary of all pipeline inputs."""
        t = inputs.technicals
        c = inputs.context
        logger.info("--- Pipeline inputs ---")
        logger.info("  TECHNICALS date: %s (row %d)", t.today_date, t.today_row_number)
        logger.info("  TOD variables: %d", len(t.today))
        logger.info("  YES variables: %d", len(t.yesterday))
        logger.info("  MACRONEWS: %d chars", len(c.macronews))
        logger.info("  METEONEWS: %d chars", len(c.meteonews))
        logger.info("  METEOTODAY: %d chars", len(c.meteotoday))
