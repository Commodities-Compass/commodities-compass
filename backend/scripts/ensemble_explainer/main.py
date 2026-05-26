"""CLI entry point for the ensemble explainer.

Runs at 19:25 UTC daily (P2b calendar-aware gate), AFTER:
  - cc-ensemble-compute (19:18) has written the ensemble decision + diagnostics
  - cc-press-review-agent (19:05) and cc-meteo-agent (19:00) wrote their rows
  - cc-daily-analysis (19:20) wrote the legacy row (which the legacy brief uses)

Sequence:
  1. Resolve active contract + ensemble algorithm_version_id
  2. Read inputs: pl_orchestrator_decision + 14 specialist_prediction + press + meteo + technicals
  3. Build the LLM prompt (FR éditorial, decision-pinned)
  4. Call OpenAI gpt-4o-mini (1 call, ~$0.001, ~3s)
  5. Validate output JSON: schema + consistency vs decision (fail-loud)
  6. UPDATE pl_indicator_daily ensemble row with eco/confidence/direction/conclusion

Fail-loud per .claude/rules/pipeline-error-handling.md — no auto-retry, no
fallback. On any error the job exits non-zero and Sentry captures it.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import date as date_type
from pathlib import Path

import sentry_sdk
from dotenv import load_dotenv
from sentry_sdk.crons import monitor

from app.core.sentry import init_sentry
from scripts.ensemble_explainer.config import LOG_FORMAT
from scripts.ensemble_explainer.db_reader import (
    ExplainerDataMissingError,
    read_explainer_inputs,
)
from scripts.ensemble_explainer.db_writer import (
    ExplainerWriteError,
    update_ensemble_narrative,
)
from scripts.ensemble_explainer.llm_client import call_openai
from scripts.ensemble_explainer.output_parser import (
    ExplainerOutputError,
    parse_explainer_output,
)
from scripts.ensemble_explainer.prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE

logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

load_dotenv(Path(__file__).parent.parent.parent / ".env")
init_sentry("ensemble-explainer")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ensemble Explainer — LLM commentary for the ensemble decision"
    )
    parser.add_argument("--dry-run", action="store_true", help="Log only, no DB write")
    parser.add_argument("--verbose", action="store_true", help="Debug logging")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass eve-of-trading-day gate (backfill/debugging)",
    )
    parser.add_argument(
        "--target-date",
        type=date_type.fromisoformat,
        default=None,
        help=(
            "Trading session date the commentary should target (YYYY-MM-DD). "
            "Defaults to get_next_session_date(today()) per P2b."
        ),
    )
    return parser.parse_args()


def _build_specialists_table(specialists) -> str:
    """Format the 14-specialist votes as a readable text block for the prompt."""
    if not specialists:
        return "(aucun vote spécialiste disponible)"
    lines = [
        f"  {s.name:<32s} {s.pred:<8s} (window={s.window_months}m)" for s in specialists
    ]
    return "\n".join(lines)


def _format_decimal(value, precision: int = 3) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.{precision}f}"
    except (TypeError, ValueError):
        return str(value)


def _build_user_prompt(inputs) -> str:
    return USER_PROMPT_TEMPLATE.format(
        target_date=inputs.target_date.isoformat(),
        decision=inputs.decision,
        soft_gate_decision=inputs.soft_gate_decision,
        wrapper_active=inputs.wrapper_active,
        net_score=_format_decimal(inputs.net_score, 4),
        n_committed_specialists=inputs.n_committed_specialists
        if inputs.n_committed_specialists is not None
        else "n/a",
        running_acc_5d=_format_decimal(inputs.running_acc_5d, 4),
        realized_return_5d=_format_decimal(inputs.realized_return_5d, 4),
        anomaly_score_z=_format_decimal(inputs.anomaly_score_z, 3),
        macro_direction=inputs.macro_direction
        if inputs.macro_direction is not None
        else "n/a",
        macro_surprise=_format_decimal(inputs.macro_surprise, 3),
        macro_half_life_days=inputs.macro_half_life_days
        if inputs.macro_half_life_days is not None
        else "n/a",
        prior_open=_format_decimal(inputs.prior_open, 3),
        prior_hedge=_format_decimal(inputs.prior_hedge, 3),
        prior_monitor=_format_decimal(inputs.prior_monitor, 3),
        winter_vote_signed=inputs.winter_vote_signed
        if inputs.winter_vote_signed is not None
        else "n/a",
        spring_vote_signed=inputs.spring_vote_signed
        if inputs.spring_vote_signed is not None
        else "n/a",
        fired_running_acc=inputs.fired_running_acc,
        fired_trend=inputs.fired_trend,
        fired_dispersion=inputs.fired_dispersion,
        fired_three_way=inputs.fired_three_way,
        specialist_votes_table=_build_specialists_table(inputs.specialists),
        press_summary=(inputs.press_summary or "(aucune revue de presse disponible)")[
            :1200
        ],
        press_impact=(inputs.press_impact or "(aucune synthèse impact)")[:600],
        press_sentiment=inputs.press_sentiment or "n/a",
        meteo_summary=(inputs.meteo_summary or "(aucune météo disponible)")[:600],
        meteo_impact=(inputs.meteo_impact or "(aucune évaluation impact)")[:400],
        technicals_snapshot=inputs.technicals_snapshot,
    )


@monitor(monitor_slug="ensemble-explainer")
def main() -> int:
    args = _parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # P2b gate
    from scripts.db import (
        get_next_session_date,
        get_previous_session_date,
        is_eve_of_trading_day,
    )

    target_date: date_type = args.target_date or get_next_session_date()
    if not args.force and args.target_date is None:
        if not is_eve_of_trading_day():
            logger.info(
                "Phase-B gate: tomorrow is not a trading day — skipping cleanly."
            )
            return 0

    # ``data_date`` = last completed session = where ensemble-compute (19:18
    # weekday) wrote pl_orchestrator_decision + the ensemble row of
    # pl_indicator_daily. The explainer reads/UPDATEs against this date,
    # while ``target_date`` remains the upcoming session the narrative is
    # written for (used for press/meteo lookups + Sentry context).
    data_date: date_type = get_previous_session_date(target_date)

    logger.info("=" * 60)
    logger.info("Ensemble Explainer")
    logger.info("Mode: %s", "DRY RUN" if args.dry_run else "LIVE")
    logger.info("Target session: %s | Data session: %s", target_date, data_date)
    logger.info("=" * 60)

    try:
        from scripts.contract_resolver import resolve_active
        from scripts.db import get_session

        with get_session() as session:
            contract_id = resolve_active(session)
            logger.info("Active contract id: %s", contract_id)

            inputs = read_explainer_inputs(
                session, target_date, contract_id, data_date=data_date
            )

            user_prompt = _build_user_prompt(inputs)
            logger.info("Prompt built: %d chars", len(user_prompt))

            result = asyncio.run(call_openai(SYSTEM_PROMPT, user_prompt))
            if not result.success:
                logger.error("LLM call failed: %s", result.error)
                sentry_sdk.capture_message(
                    f"Ensemble explainer LLM failed: {result.error}", level="error"
                )
                return 1

            output = parse_explainer_output(result.parsed or {}, inputs.decision)
            logger.info(
                "Validated output: confidence=%d direction=%s conclusion_len=%d eco_len=%d",
                output.confidence,
                output.direction,
                len(output.conclusion),
                len(output.eco),
            )

            if args.dry_run:
                logger.info("[DRY RUN] Skipping UPDATE.")
                logger.info("=== eco ===\n%s", output.eco)
                logger.info("=== conclusion ===\n%s", output.conclusion)
                return 0

            update_ensemble_narrative(
                session,
                data_date,
                contract_id,
                inputs.algorithm_version_id,
                output,
            )
            session.commit()

        sentry_sdk.set_context(
            "ensemble_explainer",
            {
                "target_date": target_date.isoformat(),
                "decision": inputs.decision,
                "confidence": output.confidence,
                "direction": output.direction,
                "llm_input_tokens": result.usage.get("input_tokens", 0),
                "llm_output_tokens": result.usage.get("output_tokens", 0),
                "llm_latency_ms": result.latency_ms,
            },
        )

        logger.info("=" * 60)
        logger.info(
            "SUCCESS: ensemble narrative written for %s (decision=%s confidence=%d)",
            target_date,
            inputs.decision,
            output.confidence,
        )
        logger.info("=" * 60)
        return 0

    except (KeyboardInterrupt, SystemExit):
        raise
    except (
        ExplainerDataMissingError,
        ExplainerOutputError,
        ExplainerWriteError,
    ) as exc:
        logger.exception("Ensemble explainer failed: %s", exc)
        sentry_sdk.capture_exception(exc)
        return 1
    except Exception as exc:
        logger.exception("Ensemble explainer failed (unexpected): %s", exc)
        sentry_sdk.capture_exception(exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
