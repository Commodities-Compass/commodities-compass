"""CLI entry point for the daily analysis pipeline.

Usage:
    poetry run daily-analysis --dry-run
    poetry run daily-analysis --contract CAK26
    poetry run daily-analysis --session-date 2026-03-20
"""

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

import sentry_sdk
from dotenv import load_dotenv
from sentry_sdk.crons import monitor

from app.core.i18n import LANGUAGE_CLI_CHOICES, expand_languages
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
        "--session-date",
        type=date.fromisoformat,
        default=None,
        help=(
            "Session date to (re)generate, YYYY-MM-DD (= the row date the "
            "analysis updates). Default (cron): the last completed trading "
            "session. Explicit --session-date bypasses the eve-of-trading-day "
            "gate (backfills, manual reruns)."
        ),
    )
    parser.add_argument("--dry-run", action="store_true", help="Log only, no writes")
    parser.add_argument("--force", action="store_true", help="Overwrite existing data")
    parser.add_argument("--verbose", action="store_true", help="Debug logging")

    # LLM overrides
    parser.add_argument("--llm-provider", default="openai")
    parser.add_argument("--llm-model", default=None)

    # Algorithm version pin (P2-daily-analysis-version-flag.md).
    # Default None → resolve to is_active=TRUE (backward compatible).
    # Set to a name (e.g. "legacy") → target that version row even when
    # another version is currently is_active=TRUE. Required for C5 day-1
    # launch to prevent overwriting the ensemble's pl_indicator_daily row.
    parser.add_argument(
        "--algorithm-version",
        default=None,
        help=(
            "Pin to a specific algorithm name (e.g. 'legacy'). "
            "If omitted: resolves to is_active=TRUE (current behavior)."
        ),
    )

    # Content language for the 3 native prose fields (eco / conclusion /
    # confidence_rationale). Default 'fr' (source-of-truth run, owns the
    # numbers). 'en' copies numbers from the fr row and writes only EN prose
    # (D3-EN-rows) — the fr run must have written first.
    parser.add_argument(
        "--language",
        choices=LANGUAGE_CLI_CHOICES,
        default="fr",
        help=(
            "Content language of the prose fields (default: fr). 'both' runs "
            "fr then en in one execution (fr first — en copies the fr row)."
        ),
    )

    return parser.parse_args()


@monitor(monitor_slug="daily-analysis")
def main() -> int:
    args = _parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Phase-B date pair — single source of truth (scripts/db.py). --session-date
    # or --force bypass the eve-of-trading-day gate (backfills, manual reruns).
    from scripts.db import phase_b_should_skip, resolve_phase_b_dates

    if phase_b_should_skip(args.session_date, args.force):
        logger.info("Phase-B gate: tomorrow is not a trading day — skipping cleanly.")
        return 0

    dates = resolve_phase_b_dates(args.session_date)
    target_date, data_date = dates.target_date, dates.data_date

    # Resolve contract: explicit CLI arg or active contract from DB
    contract_code: str = args.contract
    if contract_code is None:
        from scripts.contract_resolver import resolve_active_code
        from scripts.db import get_session

        with get_session() as session:
            contract_code = resolve_active_code(session)
        logger.info("Resolved active contract from DB: %s", contract_code)

    # Pre-flight: the analysis reads the last completed close (= data_date).
    # target_date is the upcoming session and has no data yet.
    from scripts.db import has_contract_data_for_date

    if not has_contract_data_for_date(data_date):
        if args.force:
            logger.warning(
                "No data in pl_contract_data_daily for session %s "
                "— continuing anyway (--force)",
                data_date,
            )
        else:
            logger.warning(
                "No data in pl_contract_data_daily for session %s "
                "— skipping analysis (upstream scraper may not have run). "
                "Use --force to override.",
                data_date,
            )
            return 0

    # 'both' → fr first, then en (en copies the fr row). A failure aborts the
    # remaining languages but leaves any already-committed language intact.
    overall = 0
    for lang in expand_languages(args.language):
        code = _run_db_pipeline(
            target_date=target_date,
            data_date=data_date,
            contract_code=contract_code,
            llm_provider=args.llm_provider,
            llm_model=args.llm_model,
            algorithm_version_name=args.algorithm_version,
            dry_run=args.dry_run,
            language=str(lang),
        )
        if code != 0:
            overall = code
            logger.error(
                "Language '%s' run failed (exit %d) — skipping remaining languages.",
                lang,
                code,
            )
            break
    return overall


def _run_db_pipeline(
    target_date: date,
    data_date: date,
    contract_code: str,
    llm_provider: str,
    llm_model: str | None,
    algorithm_version_name: str | None,
    dry_run: bool,
    language: str = "fr",
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
    logger.info("Session (row date): %s | prepares: %s", data_date, target_date)
    logger.info("Contract: %s", contract_code)
    logger.info("Language: %s", language)
    logger.info("Mode: %s", "DRY RUN" if dry_run else "FULL PIPELINE")
    logger.info("=" * 60)

    try:
        db_url = str(settings.DATABASE_SYNC_URL)
        engine = create_engine(db_url)

        with Session(engine) as session:
            db_engine = DBAnalysisEngine(
                session,
                algorithm_version_name=algorithm_version_name,
                llm_provider=llm_provider,
                llm_model=llm_model,
            )
            result = db_engine.run(
                target_date=target_date,
                data_date=data_date,
                contract_code=contract_code,
                dry_run=dry_run,
                language=language,
            )

        sentry_sdk.set_context(
            "daily_analysis",
            {
                "date": data_date.isoformat(),
                "target_date": target_date.isoformat(),
                "contract": contract_code,
                "language": language,
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
