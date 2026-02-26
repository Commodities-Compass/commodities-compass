"""CLI entry point for press review agent."""

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
from scripts.press_review_agent.config import (
    LOG_FORMAT,
    SYSTEM_PROMPT,
    USER_PROMPT_TEMPLATE,
    Provider,
)
from scripts.press_review_agent.llm_client import LLMResult, call_providers
from scripts.press_review_agent.news_fetcher import (
    fetch_all_sources,
    format_sources_for_prompt,
)
from scripts.press_review_agent.sheets_reader import SheetsReader, SheetsReaderError
from scripts.press_review_agent.sheets_writer import SheetsWriter, SheetsWriterError
from scripts.press_review_agent.validator import validate_output

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


def parse_providers(provider_arg: str) -> list[Provider]:
    if provider_arg == "all":
        return [Provider.CLAUDE, Provider.OPENAI, Provider.GEMINI]
    return [Provider(provider_arg)]


load_dotenv(Path(__file__).parent.parent.parent / ".env")
init_sentry("press-review-agent")


@monitor(monitor_slug="press-review-agent")
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Press review agent for daily cocoa market analysis"
    )
    parser.add_argument(
        "--sheet",
        choices=["staging", "production"],
        default="staging",
        help="Target sheet mode",
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
    parser.add_argument(
        "--provider",
        choices=["claude", "openai", "gemini", "all"],
        default="all",
        help="LLM provider(s) to run (default: all for A/B test)",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    providers = parse_providers(args.provider)

    logger.info("=" * 60)
    logger.info("Press Review Agent - Cocoa Market Analysis")
    logger.info(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    logger.info(f"Target: {args.sheet.upper()}")
    logger.info(f"Providers: {', '.join(p.value for p in providers)}")
    logger.info("=" * 60)

    try:
        # Step 1: Read CLOSE from TECHNICALS
        logger.info("Step 1: Reading CLOSE from TECHNICALS...")
        creds = load_credentials()
        reader = SheetsReader(creds)
        close_price, date_str = reader.read_latest_close(sheet_mode=args.sheet)
        logger.info(f"CLOSE={close_price}, DATE={date_str}")

        # Step 2: Fetch news sources
        logger.info("Step 2: Fetching news sources...")
        news_results = fetch_all_sources()
        sources_text = format_sources_for_prompt(news_results)
        successful_sources = sum(1 for r in news_results if r.success)

        # Step 3: Build prompts (identical for all providers)
        user_prompt = USER_PROMPT_TEMPLATE.format(
            date=date_str,
            close=close_price,
            source_count=successful_sources,
            sources_text=sources_text,
        )
        logger.info(
            f"Prompt built: {len(user_prompt)} chars, " f"{successful_sources} sources"
        )

        # Step 4: Call LLM providers in parallel
        logger.info(f"Step 3: Calling {len(providers)} LLM provider(s)...")
        llm_results: list[LLMResult] = asyncio.run(
            call_providers(providers, SYSTEM_PROMPT, user_prompt)
        )

        # Step 5: Validate + write for each successful provider
        logger.info("Step 4: Validating and writing results...")
        writer = SheetsWriter(creds)
        any_success = False

        for result in llm_results:
            if not result.success:
                logger.error(
                    f"[{result.provider.value}] LLM call failed: {result.error}"
                )
                sentry_sdk.capture_message(
                    f"Press review LLM failed: {result.provider.value} "
                    f"- {result.error}",
                    level="error",
                )
                continue

            errors = validate_output(result.parsed, result.provider)
            if errors:
                logger.error(f"[{result.provider.value}] Validation failed: {errors}")
                sentry_sdk.capture_message(
                    f"Press review validation failed: {result.provider.value} "
                    f"- {errors}",
                    level="error",
                )
                continue

            try:
                writer.append_row(
                    provider=result.provider,
                    parsed=result.parsed,
                    sheet_mode=args.sheet,
                    dry_run=args.dry_run,
                )
                any_success = True
            except SheetsWriterError as e:
                logger.error(f"[{result.provider.value}] Write failed: {e}")
                sentry_sdk.capture_exception(e)

        # Step 6: Sentry context
        sentry_sdk.set_context(
            "press_review",
            {
                "date": date_str,
                "close": close_price,
                "sources_fetched": successful_sources,
                "sources_total": len(news_results),
                "providers_attempted": [p.value for p in providers],
                "providers_succeeded": [
                    r.provider.value for r in llm_results if r.success and r.parsed
                ],
                "usage": {r.provider.value: r.usage for r in llm_results if r.usage},
                "latencies": {r.provider.value: r.latency_ms for r in llm_results},
                "dry_run": args.dry_run,
            },
        )

        if not any_success:
            logger.error("All providers failed -- no data written")
            sentry_sdk.capture_message(
                "Press review: ALL providers failed", level="error"
            )
            return 1

        logger.info("=" * 60)
        logger.info("SUCCESS: Press review agent completed")
        logger.info("=" * 60)
        return 0

    except SheetsReaderError as e:
        logger.error(f"Sheets reader error: {e}")
        sentry_sdk.capture_exception(e)
        return 1
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        sentry_sdk.capture_exception(e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
