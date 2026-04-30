"""CLI entry point for press review agent."""

import argparse
import asyncio
import logging
import sys
import uuid
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
    fetch_google_news_headlines,
    format_sources_for_prompt,
)
from scripts.press_review_agent.validator import validate_output

logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


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
        "--provider",
        choices=["claude", "openai", "gemini", "all"],
        default="openai",
        help="LLM provider to run (default: openai/o4-mini for production)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run even on non-trading days (for backfills/debugging)",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Skip on non-trading days unless --force
    from scripts.db import should_skip_non_trading_day

    if should_skip_non_trading_day(force=args.force):
        return 0

    providers = parse_providers(args.provider)

    logger.info("=" * 60)
    logger.info("Press Review Agent - Cocoa Market Analysis")
    logger.info(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    logger.info(f"Providers: {', '.join(p.value for p in providers)}")
    logger.info("=" * 60)

    try:
        # Step 1: Read CLOSE from DB
        logger.info("Step 1: Reading CLOSE from pl_contract_data_daily...")
        from scripts.db import get_session
        from scripts.press_review_agent.db_reader import read_latest_close

        with get_session() as session:
            close_price, date_str, contract_code, contract_month = read_latest_close(
                session
            )
        logger.info(
            f"CLOSE={close_price}, DATE={date_str}, CONTRACT={contract_code} ({contract_month})"
        )

        # Step 2: Fetch news sources + Google News headlines
        logger.info("Step 2: Fetching news sources...")
        news_results = fetch_all_sources()
        headlines = fetch_google_news_headlines()
        sources_text = format_sources_for_prompt(news_results, headlines)
        successful_sources = sum(1 for r in news_results if r.success)
        logger.info(f"Google News: {len(headlines)} headlines fetched")

        # Step 3: Build prompts (identical for all providers)
        user_prompt = USER_PROMPT_TEMPLATE.format(
            date=date_str,
            close=close_price,
            contract_code=contract_code,
            contract_month=contract_month,
            source_count=successful_sources,
            sources_text=sources_text,
        )
        logger.info(
            f"Prompt built: {len(user_prompt)} chars, {successful_sources} sources"
        )

        # Step 4: Call LLM providers in parallel
        logger.info(f"Step 3: Calling {len(providers)} LLM provider(s)...")
        llm_results: list[LLMResult] = asyncio.run(
            call_providers(providers, SYSTEM_PROMPT, user_prompt)
        )

        # Step 5: Validate + write for each successful provider
        logger.info("Step 4: Validating and writing results...")
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

            # DB write
            from scripts.press_review_agent.db_writer import (
                write_article,
                write_llm_call,
                write_theme_sentiments,
            )

            with get_session() as session:
                article_id = write_article(
                    session,
                    result.provider,
                    result.parsed,
                    dry_run=args.dry_run,
                    source_count=successful_sources,
                    total_sources=len(news_results),
                )
                write_llm_call(
                    session,
                    result.provider,
                    result.usage,
                    result.latency_ms,
                    dry_run=args.dry_run,
                )

                # Theme sentiments — additive, non-blocking
                if result.parsed and "theme_sentiments" in result.parsed:
                    try:
                        from datetime import date as date_type

                        write_theme_sentiments(
                            session,
                            article_id or uuid.uuid4(),
                            date_type.today(),
                            result.parsed["theme_sentiments"],
                            result.provider,
                            dry_run=args.dry_run,
                        )
                    except Exception as e:
                        logger.error(
                            "[%s] Theme sentiment write FAILED: %s",
                            result.provider.value,
                            e,
                        )
                        raise

            any_success = True

        # Sentry context
        sentry_sdk.set_context(
            "press_review",
            {
                "date": date_str,
                "close": close_price,
                "sources_fetched": successful_sources,
                "sources_total": len(news_results),
                "google_news_headlines": len(headlines),
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

    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        sentry_sdk.capture_exception(e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
