"""CLI entry point for press review agent."""

import argparse
import asyncio
import logging
import sys
import uuid
from datetime import date as date_type
from pathlib import Path

import sentry_sdk
from dotenv import load_dotenv
from sentry_sdk.crons import monitor

from app.core.i18n import LANGUAGE_CLI_CHOICES, expand_languages
from app.core.sentry import init_sentry
from scripts.press_review_agent.config import (
    LOG_FORMAT,
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_EN,
    USER_PROMPT_TEMPLATE,
    USER_PROMPT_TEMPLATE_EN,
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
    parser.add_argument(
        "--session-date",
        type=date_type.fromisoformat,
        default=None,
        help=(
            "Session date to (re)generate, YYYY-MM-DD (= the row date the "
            "review lands on). Default (cron): the last completed trading "
            "session. Explicit --session-date bypasses the eve-of-trading-day "
            "gate (backfills, manual reruns)."
        ),
    )
    parser.add_argument(
        "--language",
        choices=LANGUAGE_CLI_CHOICES,
        default="fr",
        help=(
            "Review language (default: fr). 'en' writes a native English "
            "(Ghana) article row alongside the fr row; 'both' runs fr then en "
            "in one execution. The ensemble-facing article segments are always "
            "written by the fr run only."
        ),
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Phase-B date pair — single source of truth (scripts/db.py). The prompt
    # addresses target_date (the upcoming session the review informs), but the
    # ROW is dated at data_date (= last completed session) so dashboard queries
    # align with the pl_* rows compute-indicators wrote for the same session.
    from scripts.db import phase_b_should_skip, resolve_phase_b_dates

    if phase_b_should_skip(args.session_date, args.force):
        logger.info("Phase-B gate: tomorrow is not a trading day — skipping cleanly.")
        return 0

    dates = resolve_phase_b_dates(args.session_date)
    target_date: date_type = dates.target_date
    data_date: date_type = dates.data_date

    providers = parse_providers(args.provider)

    logger.info("=" * 60)
    logger.info("Press Review Agent - Cocoa Market Analysis")
    logger.info(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    logger.info(f"Language: {args.language}")
    logger.info(f"Target session: {target_date} | Data session (row date): {data_date}")
    logger.info(f"Providers: {', '.join(p.value for p in providers)}")
    logger.info("=" * 60)

    try:
        # Step 1: Read CLOSE from DB
        logger.info("Step 1: Reading CLOSE from pl_contract_data_daily...")
        from scripts.db import get_session
        from scripts.press_review_agent.db_reader import read_latest_close

        with get_session() as session:
            close_price, close_date_str, contract_code, contract_month = (
                read_latest_close(session)
            )
        logger.info(
            f"CLOSE={close_price}, CLOSE_DATE={close_date_str}, "
            f"CONTRACT={contract_code} ({contract_month}), TARGET_DATE={target_date}"
        )

        # Step 2: Fetch news sources + Google News headlines
        logger.info("Step 2: Fetching news sources...")
        news_results = fetch_all_sources()
        headlines = fetch_google_news_headlines()
        sources_text = format_sources_for_prompt(news_results, headlines)
        successful_sources = sum(1 for r in news_results if r.success)
        logger.info(f"Google News: {len(headlines)} headlines fetched")

        from scripts.press_review_agent.db_writer import (
            write_article,
            write_llm_call,
            write_theme_sentiments,
        )

        # Step 3-5: per-language build → call providers → validate → write.
        # Sources are fetched once above. 'both' runs fr then en (fr first): the
        # fr run writes the ensemble-facing article segments; the en run writes
        # only its native-English prose article row. A language with no
        # successful provider aborts the remaining languages (fr-first).
        # P2b: prompt frames the review as "for trading session {target_date}",
        # distinct from the prior close date used to anchor the technical context.
        overall_ok = True
        any_success = False
        llm_results: list[LLMResult] = []
        for lang in expand_languages(args.language):
            system_prompt = SYSTEM_PROMPT_EN if lang == "en" else SYSTEM_PROMPT
            user_prompt_template = (
                USER_PROMPT_TEMPLATE_EN if lang == "en" else USER_PROMPT_TEMPLATE
            )
            user_prompt = user_prompt_template.format(
                target_date=target_date.isoformat(),
                close_date=close_date_str,
                close=close_price,
                contract_code=contract_code,
                contract_month=contract_month,
                source_count=successful_sources,
                sources_text=sources_text,
            )
            logger.info(
                "[%s] Prompt built: %d chars — calling %d provider(s)...",
                lang,
                len(user_prompt),
                len(providers),
            )
            llm_results = asyncio.run(
                call_providers(providers, system_prompt, user_prompt)
            )

            lang_success = False
            for result in llm_results:
                if not result.success:
                    logger.error(
                        "[%s/%s] LLM call failed: %s",
                        result.provider.value,
                        lang,
                        result.error,
                    )
                    sentry_sdk.capture_message(
                        f"Press review LLM failed: {result.provider.value}/{lang} "
                        f"- {result.error}",
                        level="error",
                    )
                    continue

                errors = validate_output(result.parsed, result.provider)
                if errors:
                    logger.error(
                        "[%s/%s] Validation failed: %s",
                        result.provider.value,
                        lang,
                        errors,
                    )
                    sentry_sdk.capture_message(
                        f"Press review validation failed: "
                        f"{result.provider.value}/{lang} - {errors}",
                        level="error",
                    )
                    continue

                with get_session() as session:
                    # P2b: article_date = data_date (= last completed session).
                    # The dashboard queries pl_fundamental_article.date by
                    # session_date (= previous_trading_day(display_date)). If we
                    # store the press at target_date (upcoming session) the
                    # dashboard fetches 0 rows on the morning after.
                    article_id = write_article(
                        session,
                        result.provider,
                        result.parsed,
                        article_date=data_date,
                        language=str(lang),
                        dry_run=args.dry_run,
                        source_count=successful_sources,
                        total_sources=len(news_results),
                        force=args.force,
                    )
                    write_llm_call(
                        session,
                        result.provider,
                        result.usage,
                        result.latency_ms,
                        dry_run=args.dry_run,
                    )

                    # Theme sentiments — additive, non-blocking. FR RUN ONLY.
                    # pl_article_segment has NO language dimension and feeds the
                    # (language-agnostic) ensemble macro signal. An EN set would
                    # be a second summary of the SAME news → the ensemble would
                    # double-count it. So the segments stay owned by the fr run;
                    # the EN run still emits theme_sentiments (kept in the prompt
                    # so the shared validator passes) but discards them here.
                    if result.parsed is not None and lang == "fr":
                        try:
                            # P2b: theme sentiments share the same date as the
                            # article row → data_date (= last completed session),
                            # not target_date. Keeps pl_article_segment in sync
                            # with pl_fundamental_article so the sentiment
                            # batch-read in dashboard_service.get_theme_sentiments
                            # finds rows for session_date.
                            write_theme_sentiments(
                                session,
                                article_id or uuid.uuid4(),
                                data_date,
                                result.parsed.get("theme_sentiments") or {},
                                result.provider,
                                dry_run=args.dry_run,
                                force=args.force,
                            )
                        except Exception as e:
                            logger.error(
                                "[%s] Theme sentiment write FAILED: %s",
                                result.provider.value,
                                e,
                            )
                            raise

                lang_success = True
                any_success = True

            if not lang_success:
                overall_ok = False
                logger.error("[%s] No provider succeeded for this language.", lang)
                break  # fr-first: don't attempt en if fr fully failed

        # Sentry context (from the last language's provider results)
        sentry_sdk.set_context(
            "press_review",
            {
                "target_date": target_date.isoformat(),
                "data_date": data_date.isoformat(),
                "language": args.language,
                "close_date": close_date_str,
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
        if not overall_ok:
            logger.error("At least one language run failed -- see logs above")
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
