"""CLI entry point for pattern extraction from press review articles."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from scripts.pattern_extractor.config import (
    EXTRACTION_VERSION,
    LOG_FORMAT,
    SYSTEM_PROMPT,
    USER_PROMPT_TEMPLATE,
)
from scripts.pattern_extractor.llm_client import call_openai
from scripts.pattern_extractor.output_parser import parse_extraction

logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


load_dotenv(Path(__file__).parent.parent.parent / ".env")


def process_article(article, *, dry_run: bool, extraction_version: str) -> bool:
    """Extract segments from a single article. Returns True on success."""
    from scripts.db import get_session
    from scripts.pattern_extractor.db_writer import write_llm_call, write_segments

    user_prompt = USER_PROMPT_TEMPLATE.format(
        date=article.date.strftime("%Y-%m-%d"),
        summary=article.summary or "",
        keywords=article.keywords or "N/A",
        impact_synthesis=article.impact_synthesis or "N/A",
    )

    result = asyncio.run(call_openai(SYSTEM_PROMPT, user_prompt))

    if not result.success:
        logger.error(
            "LLM call failed for article %s (%s): %s",
            article.id,
            article.date,
            result.error,
        )
        return False

    try:
        extraction = parse_extraction(result.parsed)
    except ValueError as e:
        logger.error(
            "Validation failed for article %s (%s): %s",
            article.id,
            article.date,
            e,
        )
        return False

    with get_session() as session:
        write_segments(
            session,
            article.id,
            article.date,
            extraction,
            extraction_version=extraction_version,
            dry_run=dry_run,
        )
        write_llm_call(
            session,
            result.usage,
            result.latency_ms,
            dry_run=dry_run,
        )

    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract structured patterns from press review articles"
    )
    parser.add_argument(
        "--mode",
        choices=["batch", "single"],
        default="batch",
        help="batch = all unprocessed articles, single = latest article only",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run extraction but don't write to DB",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N articles (batch mode)",
    )
    parser.add_argument(
        "--rate-limit",
        type=float,
        default=1.0,
        help="Seconds between API calls (default: 1.0)",
    )
    parser.add_argument(
        "--extraction-version",
        default=EXTRACTION_VERSION,
        help=f"Version tag for extraction results (default: {EXTRACTION_VERSION})",
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
    logger.info("Pattern Extractor - Cocoa Market Articles")
    logger.info(
        "Mode: %s | %s | version=%s",
        args.mode,
        "DRY RUN" if args.dry_run else "LIVE",
        args.extraction_version,
    )
    logger.info("=" * 60)

    try:
        from scripts.db import get_session
        from scripts.pattern_extractor.db_reader import (
            read_latest_article,
            read_unprocessed_articles,
        )

        # Load articles
        with get_session() as session:
            if args.mode == "single":
                article = read_latest_article(session)
                articles = [article] if article else []
            else:
                articles = read_unprocessed_articles(
                    session,
                    args.extraction_version,
                    limit=args.limit,
                )

        if not articles:
            logger.info("No articles to process.")
            return 0

        logger.info("Found %d article(s) to process", len(articles))

        # Process each article
        success_count = 0
        fail_count = 0

        for i, article in enumerate(articles, 1):
            logger.info(
                "[%d/%d] Processing article %s (date=%s, %d chars)",
                i,
                len(articles),
                article.id,
                article.date,
                len(article.summary or ""),
            )

            ok = process_article(
                article,
                dry_run=args.dry_run,
                extraction_version=args.extraction_version,
            )

            if ok:
                success_count += 1
            else:
                fail_count += 1

            # Rate limiting between calls
            if i < len(articles) and args.rate_limit > 0:
                time.sleep(args.rate_limit)

        logger.info("=" * 60)
        logger.info(
            "DONE: %d success, %d failed out of %d",
            success_count,
            fail_count,
            len(articles),
        )
        logger.info("=" * 60)

        return 1 if fail_count > 0 and success_count == 0 else 0

    except Exception as e:
        logger.exception("Unexpected error: %s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
