"""CLI entry point for Barchart scraper."""

import logging
import sys

import sentry_sdk
from sentry_sdk.crons import monitor

from scripts._shared.cli import build_base_argparser
from scripts._shared.sentry import bootstrap_scraper
from scripts.barchart_scraper.config import LOG_FORMAT
from scripts.barchart_scraper.scraper import BarchartScraper, BarchartScraperError
from scripts.barchart_scraper.validator import DataValidator

logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# Load env + init Sentry BEFORE @monitor-decorated function
bootstrap_scraper("barchart-scraper", script_file=__file__)


@monitor(monitor_slug="barchart-scraper")
def main() -> int:
    parser = build_base_argparser("Barchart scraper for London cocoa futures")
    parser.add_argument(
        "--headful",
        action="store_true",
        help="Run browser in non-headless mode (visible, for debugging)",
    )

    args = parser.parse_args()

    # Skip on non-trading days unless --force
    from scripts.db import should_skip_non_trading_day

    if should_skip_non_trading_day(force=args.force):
        return 0

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    logger.info("=" * 60)
    logger.info("Barchart Scraper - London Cocoa #7 (CA*0)")
    logger.info(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    logger.info(f"Browser: {'HEADFUL (visible)' if args.headful else 'HEADLESS'}")
    logger.info("=" * 60)

    try:
        # Step 1: Scrape data
        logger.info("Step 1: Scraping Barchart.com...")
        with BarchartScraper(headless=not args.headful) as scraper:
            data = scraper.scrape_all()

        # Step 2: Validate data
        logger.info("Step 2: Validating data...")
        errors = DataValidator.validate_all(data)
        if errors:
            logger.error("Validation failed:")
            for error in errors:
                logger.error(f"  - {error}")
            sentry_sdk.capture_message(
                f"Barchart validation failed: {errors}", level="error"
            )
            return 1

        # Step 3: Write to GCP PostgreSQL
        logger.info("Step 3: Writing to GCP PostgreSQL...")
        from scripts.barchart_scraper.config import get_current_contract_code
        from scripts.barchart_scraper.db_writer import write_ohlcv
        from scripts.db import get_display_date, get_session

        display_date = get_display_date()
        logger.info("Display date (next trading day): %s", display_date)

        with get_session() as session:
            write_ohlcv(
                session,
                data,
                get_current_contract_code(),
                dry_run=args.dry_run,
                display_date=display_date,
            )

        sentry_sdk.set_context(
            "scrape_result",
            {
                "date": str(data.get("date")),
                "contract": str(data.get("contract_code")),
                "close": str(data.get("close")),
                "volume": str(data.get("volume")),
                "oi": str(data.get("open_interest")),
                "iv": str(data.get("iv")),
                "dry_run": args.dry_run,
            },
        )

        logger.info("=" * 60)
        logger.info("SUCCESS: Scraper completed successfully")
        logger.info("=" * 60)
        return 0

    except BarchartScraperError as e:
        logger.error(f"Scraper error: {e}")
        sentry_sdk.capture_exception(e)
        return 1
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        sentry_sdk.capture_exception(e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
