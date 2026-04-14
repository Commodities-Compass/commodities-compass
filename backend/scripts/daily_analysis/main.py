"""CLI entry point for the daily analysis pipeline.

Usage:
    poetry run daily-analysis --dry-run
    poetry run daily-analysis --contract CAK26
    poetry run daily-analysis --date 2026-03-20
"""

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import sentry_sdk
from dotenv import load_dotenv
from sentry_sdk.crons import monitor

from app.core.sentry import init_sentry

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
        "--contract",
        default=None,
        help="Contract code (default: active contract from DB)",
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

    # LLM overrides
    parser.add_argument("--llm-provider", default="openai")
    parser.add_argument("--llm-model", default=None)

    return parser.parse_args()


def _resolve_date(date_str: str | None) -> datetime:
    if date_str:
        return datetime.strptime(date_str, "%Y-%m-%d")
    return datetime.now(timezone.utc)


@monitor(monitor_slug="daily-analysis")
def main() -> int:
    args = _parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Skip on non-trading days unless --force
    from scripts.db import should_skip_non_trading_day

    if should_skip_non_trading_day(force=args.force):
        return 0

    target_date = _resolve_date(args.date)

    # Resolve contract: explicit CLI arg or active contract from DB
    contract_code: str = args.contract
    if contract_code is None:
        from scripts.contract_resolver import resolve_active_code
        from scripts.db import get_session

        with get_session() as session:
            contract_code = resolve_active_code(session)
        logger.info("Resolved active contract from DB: %s", contract_code)

    # Pre-flight: verify upstream data exists before making LLM calls
    from scripts.db import has_contract_data_for_date

    check_date = (
        target_date.date() if isinstance(target_date, datetime) else target_date
    )
    if not has_contract_data_for_date(check_date):
        if args.force:
            logger.warning(
                "No data in pl_contract_data_daily for %s — continuing anyway (--force)",
                check_date,
            )
        else:
            logger.warning(
                "No data in pl_contract_data_daily for %s — skipping analysis "
                "(upstream scraper may not have run). Use --force to override.",
                check_date,
            )
            return 0

    return _run_db_pipeline(
        target_date=target_date,
        contract_code=contract_code,
        llm_provider=args.llm_provider,
        llm_model=args.llm_model,
        dry_run=args.dry_run,
    )


def _run_db_pipeline(
    target_date: datetime,
    contract_code: str,
    llm_provider: str,
    llm_model: str | None,
    dry_run: bool,
) -> int:
    """Run the DB-first pipeline (no Sheets dependency)."""
    import os

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.core.config import settings
    from scripts.daily_analysis.db_analysis_engine import DBAnalysisEngine

    if not os.environ.get("OPENAI_API_KEY"):
        logger.error("Missing OPENAI_API_KEY environment variable")
        return 1

    logger.info("=" * 60)
    logger.info("Daily Analysis Pipeline")
    logger.info("Date: %s", target_date.strftime("%Y-%m-%d"))
    logger.info("Contract: %s", contract_code)
    logger.info("Mode: %s", "DRY RUN" if dry_run else "FULL PIPELINE")
    logger.info("=" * 60)

    try:
        db_url = str(settings.DATABASE_SYNC_URL)
        engine = create_engine(db_url)

        with Session(engine) as session:
            db_engine = DBAnalysisEngine(
                session,
                llm_provider=llm_provider,
                llm_model=llm_model,
            )
            result = db_engine.run(
                target_date=target_date.date()
                if isinstance(target_date, datetime)
                else target_date,
                contract_code=contract_code,
                dry_run=dry_run,
            )

        sentry_sdk.set_context(
            "daily_analysis",
            {
                "date": target_date.strftime("%Y-%m-%d"),
                "contract": contract_code,
                "macroeco_bonus": result.macro.macroeco_bonus,
                "final_indicator": result.final_indicator,
                "conclusion": result.final_conclusion,
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
            result.final_indicator,
            result.final_conclusion,
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

    except Exception as exc:
        logger.exception("Pipeline error: %s", exc)
        sentry_sdk.capture_exception(exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
