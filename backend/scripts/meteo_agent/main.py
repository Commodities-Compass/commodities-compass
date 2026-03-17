"""CLI entry point for meteo agent."""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

import sentry_sdk
from dotenv import load_dotenv
from sentry_sdk.crons import monitor

from app.core.sentry import init_sentry
from scripts.meteo_agent.config import LOG_FORMAT, SYSTEM_PROMPT, USER_PROMPT_TEMPLATE
from scripts.meteo_agent.llm_client import call_openai
from scripts.meteo_agent.sheets_writer import SheetsWriter, SheetsWriterError
from scripts.meteo_agent.validator import validate_output
from scripts.meteo_agent.weather_fetcher import WeatherFetcherError, fetch_weather

logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def load_credentials() -> str:
    creds = os.getenv("GOOGLE_SHEETS_SCRAPER_CREDENTIALS_JSON")
    if not creds:
        raise RuntimeError("GOOGLE_SHEETS_SCRAPER_CREDENTIALS_JSON not set")
    return creds


load_dotenv(Path(__file__).parent.parent.parent / ".env")
init_sentry("meteo-agent")


@monitor(monitor_slug="meteo-agent")
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Meteo agent for daily cocoa weather analysis"
    )
    parser.add_argument(
        "--sheet",
        choices=["staging", "production"],
        default="staging",
        help="Target sheet mode (currently writes to METEO_ALL in both modes)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run pipeline but don't write to Sheets",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    logger.info("=" * 60)
    logger.info("Meteo Agent - Cocoa Weather Analysis")
    logger.info("Mode: %s", "DRY RUN" if args.dry_run else "LIVE")
    logger.info("Target: %s", args.sheet.upper())
    logger.info("=" * 60)

    try:
        # Step 1: Fetch weather data from Open-Meteo API
        logger.info("Step 1: Fetching weather data from Open-Meteo...")
        weather_data = fetch_weather()
        logger.info("Weather data: %d chars", len(weather_data))

        # Step 2: Build prompt and call LLM
        logger.info("Step 2: Calling OpenAI for analysis...")
        user_prompt = USER_PROMPT_TEMPLATE.format(weather_data=weather_data)
        result = asyncio.run(call_openai(SYSTEM_PROMPT, user_prompt))

        if not result.success:
            logger.error("LLM call failed: %s", result.error)
            sentry_sdk.capture_message(
                f"Meteo agent LLM failed: {result.error}", level="error"
            )
            return 1

        # Step 3: Validate output
        logger.info("Step 3: Validating output...")
        errors = validate_output(result.parsed)
        if errors:
            logger.error("Validation failed: %s", errors)
            sentry_sdk.capture_message(
                f"Meteo agent validation failed: {errors}", level="error"
            )
            return 1

        # Step 4: Write to GCP PostgreSQL (non-blocking)
        logger.info("Step 4: Writing to GCP PostgreSQL...")
        try:
            from scripts.db import get_session
            from scripts.meteo_agent.db_writer import write_llm_call, write_observation

            with get_session() as session:
                write_observation(session, result.parsed, dry_run=args.dry_run)
                write_llm_call(
                    session, result.usage, result.latency_ms, dry_run=args.dry_run
                )
        except Exception as db_err:
            logger.error("DB write failed (continuing to Sheets): %s", db_err)
            sentry_sdk.capture_exception(db_err)

        # Step 5: Write to METEO_ALL
        logger.info("Step 5: Writing to METEO_ALL...")
        if args.dry_run:
            logger.info("[DRY RUN] Output preview:")
            for field in ("texte", "resume", "mots_cle", "impact_synthetiques"):
                val = result.parsed.get(field, "")
                logger.info("  %s: %d chars — %s...", field, len(val), val[:120])

        creds = load_credentials()
        writer = SheetsWriter(creds)
        writer.write_row(parsed=result.parsed, dry_run=args.dry_run)

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
    except SheetsWriterError as e:
        logger.error("Sheets writer error: %s", e)
        sentry_sdk.capture_exception(e)
        return 1
    except Exception as e:
        logger.exception("Unexpected error: %s", e)
        sentry_sdk.capture_exception(e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
