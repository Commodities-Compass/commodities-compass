"""CLI entry point for meteo agent."""

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
from scripts.meteo_agent.config import (
    LOG_FORMAT,
    SYSTEM_PROMPT_TEMPLATE,
    USER_PROMPT_TEMPLATE,
    build_seasonal_context,
)
from scripts.meteo_agent.llm_client import call_openai
from scripts.meteo_agent.validator import validate_output
from scripts.meteo_agent.weather_fetcher import WeatherFetcherError, fetch_weather

logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

load_dotenv(Path(__file__).parent.parent.parent / ".env")
init_sentry("meteo-agent")


@monitor(monitor_slug="meteo-agent")
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Meteo agent for daily cocoa weather analysis"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run pipeline but don't write to DB",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run even on non-trading days (for backfills/debugging)",
    )
    parser.add_argument(
        "--bootstrap-memory",
        action="store_true",
        help="Backfill seasonal scores for current campaign from Open-Meteo history, then exit",
    )
    parser.add_argument(
        "--target-date",
        type=date_type.fromisoformat,
        default=None,
        help=(
            "Trading session date the observation should be tagged to "
            "(YYYY-MM-DD). Defaults to get_next_session_date(today()) — the "
            "upcoming trading session per P2b calendar-aware timing."
        ),
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # P2b: target_date = upcoming trading session. --force or explicit
    # --target-date bypass the gate (backfills, manual reruns).
    from scripts.db import get_next_session_date, is_eve_of_trading_day

    target_date: date_type = args.target_date or get_next_session_date()

    if not args.force and args.target_date is None:
        if not is_eve_of_trading_day():
            logger.info(
                "Phase-B gate: tomorrow is not a trading day — skipping cleanly."
            )
            return 0

    # Bootstrap mode — compute and store seasonal scores, then exit
    if args.bootstrap_memory:
        return _run_bootstrap()

    logger.info("=" * 60)
    logger.info("Meteo Agent - Cocoa Weather Analysis")
    logger.info("Mode: %s", "DRY RUN" if args.dry_run else "LIVE")
    logger.info("Target session: %s", target_date)
    logger.info("=" * 60)

    try:
        # Step 1: Fetch weather data from Open-Meteo API
        logger.info("Step 1: Fetching weather data from Open-Meteo...")
        weather_data = fetch_weather()
        logger.info("Weather data: %d chars", len(weather_data))

        # Step 2: Build campaign memory + Harmattan context from DB
        logger.info("Step 2: Loading campaign memory...")

        from scripts.meteo_agent.seasonal_memory import (
            build_campaign_memory,
            build_harmattan_context,
            get_campaign,
            get_campaign_harmattan_days,
        )

        campaign_memory = ""
        harmattan_context = ""
        # P2b: campaign membership keyed on target_date (upcoming session)
        # rather than today; matters on month-boundary eve-of-Nov-1 cases.
        campaign = get_campaign(target_date)
        try:
            from scripts.db import get_session

            with get_session() as session:
                campaign_memory = build_campaign_memory(session)
                harmattan_days = get_campaign_harmattan_days(session, campaign)
                # P2b: harmattan/seasonal context aligned with target_date.month.
                harmattan_context = build_harmattan_context(
                    harmattan_days, target_date.month
                )
            if campaign_memory:
                logger.info("Campaign memory: %d chars", len(campaign_memory))
            else:
                logger.info("No campaign memory available (first run?)")
            if harmattan_context:
                logger.info("Harmattan context: %s", harmattan_context.strip())
        except (OSError, ConnectionError) as mem_err:
            logger.warning(
                "Campaign memory unavailable (transient): %s (continuing)", mem_err
            )
        except Exception as mem_err:
            # Import DB libraries to check for transient DB errors
            try:
                from sqlalchemy.exc import OperationalError, InterfaceError

                if isinstance(mem_err, (OperationalError, InterfaceError)):
                    logger.warning(
                        "Campaign memory unavailable (DB): %s (continuing)", mem_err
                    )
                else:
                    raise
            except ImportError:
                raise mem_err from None

        # Step 3: Build prompt and call LLM
        logger.info("Step 3: Calling OpenAI for analysis...")
        # P2b: seasonal context tied to target_date.month so eve-of-November-1
        # runs see November thresholds, not the previous month's.
        current_month = target_date.month
        seasonal_context = build_seasonal_context(current_month)
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(seasonal_context=seasonal_context)
        memory_block = f"\n\n{campaign_memory}" if campaign_memory else ""
        harmattan_block = harmattan_context
        user_prompt = (
            USER_PROMPT_TEMPLATE.format(weather_data=weather_data)
            + memory_block
            + harmattan_block
        )
        logger.info(
            "Season: %s (month %d)", seasonal_context.split("\n")[0], current_month
        )
        result = asyncio.run(call_openai(system_prompt, user_prompt))

        if not result.success:
            logger.error("LLM call failed: %s", result.error)
            sentry_sdk.capture_message(
                f"Meteo agent LLM failed: {result.error}", level="error"
            )
            return 1

        # Step 4: Validate output
        logger.info("Step 4: Validating output...")
        errors = validate_output(result.parsed)
        if errors:
            logger.error("Validation failed: %s", errors)
            sentry_sdk.capture_message(
                f"Meteo agent validation failed: {errors}", level="error"
            )
            return 1

        # Step 5: Write to GCP PostgreSQL
        logger.info("Step 5: Writing to GCP PostgreSQL...")
        from scripts.db import get_session
        from scripts.meteo_agent.db_writer import write_llm_call, write_observation

        with get_session() as session:
            # P2b: explicit observation_date = target_date (upcoming session)
            # — was previously implicit date.today() inside write_observation.
            write_observation(
                session,
                result.parsed,
                observation_date=target_date,
                dry_run=args.dry_run,
            )
            write_llm_call(
                session, result.usage, result.latency_ms, dry_run=args.dry_run
            )

        # Step 6: Daily Harmattan check (increment per-location counter)
        logger.info("Step 6: Checking Harmattan conditions...")
        from scripts.meteo_agent.seasonal_memory import check_daily_harmattan

        with get_session() as session:
            harmattan_results = check_daily_harmattan(
                weather_data,
                session,
                campaign,
                dry_run=args.dry_run,
            )
            if any(harmattan_results.values()):
                detected = [n for n, h in harmattan_results.items() if h]
                logger.info("Harmattan detected at: %s", ", ".join(detected))

        if args.dry_run:
            logger.info("[DRY RUN] Output preview:")
            for field in ("texte", "resume", "mots_cle", "impact_synthetiques"):
                val = result.parsed.get(field, "")
                logger.info("  %s: %d chars — %s...", field, len(val), val[:120])

        # Sentry context
        sentry_sdk.set_context(
            "meteo_agent",
            {
                "weather_data_chars": len(weather_data),
                "usage": result.usage,
                "latency_ms": result.latency_ms,
                "texte_chars": len(result.parsed.get("texte", "")),
                "resume_chars": len(result.parsed.get("resume", "")),
                "dry_run": args.dry_run,
            },
        )

        logger.info("=" * 60)
        logger.info("SUCCESS: Meteo agent completed")
        logger.info("=" * 60)
        return 0

    except WeatherFetcherError as e:
        logger.error("Weather fetch error: %s", e)
        sentry_sdk.capture_exception(e)
        return 1
    except Exception as e:
        logger.exception("Unexpected error: %s", e)
        sentry_sdk.capture_exception(e)
        return 1


def _run_bootstrap() -> int:
    """Backfill seasonal scores for the current campaign."""
    from scripts.db import get_session
    from scripts.meteo_agent.seasonal_memory import bootstrap_campaign

    logger.info("=" * 60)
    logger.info("Meteo Agent — Bootstrap Seasonal Memory")
    logger.info("=" * 60)

    try:
        with get_session() as session:
            bootstrap_campaign(session)
        logger.info("Bootstrap complete")
        return 0
    except Exception as e:
        logger.exception("Bootstrap failed: %s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
