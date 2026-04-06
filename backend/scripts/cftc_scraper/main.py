"""CFTC scraper - Simple daily runner for COM NET US data."""

import argparse
import logging
import sys
from pathlib import Path

import sentry_sdk
from dotenv import load_dotenv
from sentry_sdk.crons import monitor

from app.core.sentry import init_sentry
from scripts.cftc_scraper.scraper import CFTCScraper, CFTCScraperError

LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# Load env + init Sentry BEFORE @monitor-decorated function
load_dotenv(Path(__file__).parent.parent.parent / ".env")
init_sentry("cftc-scraper")


@monitor(monitor_slug="cftc-scraper")
def main() -> int:
    parser = argparse.ArgumentParser(description="CFTC scraper for COM NET US data")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scrape and validate, but don't write to DB",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run even on non-trading days (for backfills/debugging)",
    )

    args = parser.parse_args()

    # Skip on non-trading days unless --force
    from scripts.db import should_skip_non_trading_day

    if should_skip_non_trading_day(force=args.force):
        return 0

    logger.info("=" * 60)
    logger.info("CFTC Scraper - COM NET US")
    logger.info(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    logger.info("=" * 60)

    try:
        # Step 1: Scrape CFTC report
        logger.info("Step 1: Scraping CFTC report...")
        scraper = CFTCScraper()
        commercial_net = scraper.scrape()

        logger.info(f"COM NET US: {commercial_net:,.0f}")

        # Step 2: Write to GCP PostgreSQL
        logger.info("Step 2: Writing to GCP PostgreSQL...")
        from scripts.cftc_scraper.db_writer import write_com_net_us
        from scripts.db import get_session

        from datetime import date

        with get_session() as session:
            write_com_net_us(
                session, commercial_net, target_date=date.today(), dry_run=args.dry_run
            )

        sentry_sdk.set_context(
            "scrape_result",
            {
                "commercial_net": commercial_net,
                "dry_run": args.dry_run,
            },
        )

        logger.info("=" * 60)
        logger.info("SUCCESS: CFTC scraper completed")
        logger.info("=" * 60)
        return 0

    except CFTCScraperError as e:
        logger.error(f"CFTC scraper error: {e}")
        sentry_sdk.capture_exception(e)
        return 1
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        sentry_sdk.capture_exception(e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
