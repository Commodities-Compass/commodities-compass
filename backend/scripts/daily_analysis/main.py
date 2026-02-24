"""CLI entry point for the daily analysis pipeline.

Usage:
    # Full pipeline (dry run)
    python -m scripts.daily_analysis.main --sheet staging --dry-run

    # Full pipeline (live against staging)
    python -m scripts.daily_analysis.main --sheet staging

    # Backfill a past date
    python -m scripts.daily_analysis.main --sheet staging --date 2026-02-12 --force

    # Inspect INDICATOR sheet state only (no writes, no LLM calls)
    python -m scripts.daily_analysis.main --sheet staging --inspect

    # Indicator-only mode (test formula management without LLM)
    python -m scripts.daily_analysis.main --sheet staging --indicator-only --macroeco-bonus 0.04 --eco "Test"
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

import sentry_sdk
from dotenv import load_dotenv
from sentry_sdk.crons import monitor

from app.core.sentry import init_sentry
from scripts.daily_analysis.config import (
    INDICATOR_SHEETS,
    get_credentials_json,
    validate_env,
)
from scripts.daily_analysis.indicator_writer import (
    IndicatorWriter,
    IndicatorWriterError,
)

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"

logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

load_dotenv(Path(__file__).parent.parent.parent / ".env")
init_sentry("daily-analysis")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Commodities Compass — Daily Analysis")
    parser.add_argument(
        "--sheet",
        choices=["staging", "production"],
        default="staging",
        help="Target sheet mode for WRITES (reads always from production)",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Target date YYYY-MM-DD (default: today). Enables backfill.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Log only, no writes")
    parser.add_argument("--force", action="store_true", help="Overwrite existing data")
    parser.add_argument("--verbose", action="store_true", help="Debug logging")
    parser.add_argument(
        "--inspect", action="store_true", help="Inspect INDICATOR state and exit"
    )

    # Indicator-only mode (test formula management without LLM)
    parser.add_argument(
        "--indicator-only",
        action="store_true",
        help="Run only the INDICATOR formula shift (no LLM calls)",
    )
    parser.add_argument("--macroeco-bonus", type=float, default=0.02)
    parser.add_argument("--eco", type=str, default="Test run — no LLM output yet")

    # LLM overrides
    parser.add_argument("--llm-provider", default="openai")
    parser.add_argument("--llm-model", default=None)

    return parser.parse_args()


def _resolve_date(date_str: str | None) -> datetime:
    if date_str:
        return datetime.strptime(date_str, "%Y-%m-%d")
    return datetime.now()


@monitor(monitor_slug="daily-analysis")
def main() -> int:
    args = _parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # --- Env validation (fail fast before any API call) ---
    require_llm = not args.inspect and not args.indicator_only
    missing = validate_env(require_llm=require_llm)
    if missing:
        logger.error("Missing required environment variables: %s", ", ".join(missing))
        return 1

    target_date = _resolve_date(args.date)
    sheet_name = INDICATOR_SHEETS[args.sheet]

    logger.info("=" * 60)
    logger.info("Daily Analysis Pipeline")
    logger.info("Date: %s", target_date.strftime("%Y-%m-%d"))
    logger.info("Sheet: %s (%s)", args.sheet.upper(), sheet_name)
    logger.info(
        "Mode: %s",
        "DRY RUN"
        if args.dry_run
        else "INSPECT"
        if args.inspect
        else "INDICATOR ONLY"
        if args.indicator_only
        else "FULL PIPELINE",
    )
    logger.info("=" * 60)

    try:
        # --- Inspect mode ---
        if args.inspect:
            return _run_inspect(sheet_name)

        # --- Indicator-only mode ---
        if args.indicator_only:
            return _run_indicator_only(
                sheet_name=sheet_name,
                macroeco_bonus=args.macroeco_bonus,
                eco=args.eco,
                dry_run=args.dry_run,
                force=args.force,
                target_date=target_date,
            )

        # --- Full pipeline ---
        return _run_full_pipeline(
            sheet_mode=args.sheet,
            target_date=target_date,
            llm_provider=args.llm_provider,
            llm_model=args.llm_model,
            dry_run=args.dry_run,
            force=args.force,
        )

    except IndicatorWriterError as exc:
        logger.error("Indicator writer error: %s", exc)
        sentry_sdk.capture_exception(exc)
        return 1
    except Exception as exc:
        logger.exception("Unexpected error: %s", exc)
        sentry_sdk.capture_exception(exc)
        return 1


def _run_inspect(sheet_name: str) -> int:
    creds = get_credentials_json()
    writer = IndicatorWriter(creds)
    state = writer.get_state(sheet_name)
    logger.info(
        "State: last_row=%d | older_row=%d (R%d) | newer_row=%d (R%d)",
        state.last_data_row,
        state.older_row,
        state.lower_ref,
        state.newer_row,
        state.higher_ref,
    )
    return 0


def _run_indicator_only(
    sheet_name: str,
    macroeco_bonus: float,
    eco: str,
    dry_run: bool,
    force: bool,
    target_date: datetime,
) -> int:
    creds = get_credentials_json()
    writer = IndicatorWriter(creds)
    date_str = target_date.strftime("%m/%d/%Y")
    result = writer.execute(
        sheet_name=sheet_name,
        macroeco_bonus=macroeco_bonus,
        eco=eco,
        dry_run=dry_run,
        force=force,
        target_date_str=date_str,
    )
    logger.info(
        "Row %d → FINAL_INDICATOR=%.4f  CONCLUSION=%s",
        result.row_number,
        result.final_indicator,
        result.conclusion,
    )
    return 0


def _run_full_pipeline(
    sheet_mode: str,
    target_date: datetime,
    llm_provider: str,
    llm_model: str | None,
    dry_run: bool,
    force: bool,
) -> int:
    from scripts.daily_analysis.analysis_engine import AnalysisEngine

    engine = AnalysisEngine(
        sheet_mode=sheet_mode,
        llm_provider=llm_provider,
        llm_model=llm_model,
    )
    result = engine.run(target_date, dry_run=dry_run, force=force)

    sentry_sdk.set_context(
        "daily_analysis",
        {
            "date": target_date.strftime("%Y-%m-%d"),
            "macroeco_bonus": result.macro.macroeco_bonus,
            "final_indicator": result.indicator_readback.final_indicator,
            "conclusion": result.indicator_readback.conclusion,
            "decision": result.trading.decision,
            "confiance": result.trading.confiance,
            "direction": result.trading.direction,
            "call1_tokens": result.call1_response.input_tokens
            + result.call1_response.output_tokens,
            "call2_tokens": result.call2_response.input_tokens
            + result.call2_response.output_tokens,
            "dry_run": dry_run,
        },
    )

    logger.info("=" * 60)
    logger.info("SUCCESS — Daily Analysis Complete")
    logger.info("  MACROECO BONUS: %.2f", result.macro.macroeco_bonus)
    logger.info("  ECO: %s", result.macro.eco[:80])
    logger.info(
        "  FINAL INDICATOR: %.4f → %s",
        result.indicator_readback.final_indicator,
        result.indicator_readback.conclusion,
    )
    logger.info(
        "  DECISION: %s (CONFIANCE=%d, DIRECTION=%s)",
        result.trading.decision,
        result.trading.confiance,
        result.trading.direction,
    )
    logger.info(
        "  LLM tokens: Call#1=%d Call#2=%d",
        result.call1_response.input_tokens + result.call1_response.output_tokens,
        result.call2_response.input_tokens + result.call2_response.output_tokens,
    )
    logger.info("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
