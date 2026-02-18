"""CFTC scraper - Simple daily runner for COM NET US data."""

import argparse
import logging
import os
import sys
from pathlib import Path

import sentry_sdk
from dotenv import load_dotenv
from sentry_sdk.crons import monitor

from app.core.sentry import init_sentry
from scripts.cftc_scraper.config import LOG_FORMAT
from scripts.cftc_scraper.scraper import CFTCScraper, CFTCScraperError
from scripts.cftc_scraper.sheets_manager import SheetsManager, SheetsManagerError

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
    """
    Main entry point for CFTC scraper.

    Simple logic:
    1. Scrape CFTC report -> get COM NET US value
    2. Update last row in Google Sheets column I

    Returns:
        Exit code (0 = success, 1 = failure)
    """
    parser = argparse.ArgumentParser(description="CFTC scraper for COM NET US data")
    parser.add_argument(
        "--sheet",
        choices=["staging", "production"],
        default="staging",
        help="Target sheet: 'staging' or 'production'",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scrape and validate, but don't write to Sheets",
    )

    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("CFTC Scraper - COM NET US")
    logger.info(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    logger.info(f"Target: {args.sheet.upper()}")
    logger.info("=" * 60)

    try:
        # Step 1: Scrape CFTC report
        logger.info("Step 1: Scraping CFTC report...")
        scraper = CFTCScraper()
        commercial_net = scraper.scrape()

        logger.info(f"COM NET US: {commercial_net:,.0f}")

        # Step 2: Update Google Sheets
        logger.info("Step 2: Updating Google Sheets...")

        creds = os.getenv("GOOGLE_SHEETS_SCRAPER_CREDENTIALS_JSON")
        if not creds:
            raise RuntimeError("GOOGLE_SHEETS_SCRAPER_CREDENTIALS_JSON not set")

        if args.dry_run:
            logger.info(
                f"[DRY RUN] Would update last row column I with: {commercial_net:,.0f}"
            )
        else:
            sheets_mgr = SheetsManager(creds, sheet_name=args.sheet)
            cell_range = sheets_mgr.update_latest_row(commercial_net)
            logger.info(f"Updated {cell_range}")

        sentry_sdk.set_context(
            "scrape_result",
            {
                "commercial_net": commercial_net,
                "sheet": args.sheet,
                "dry_run": args.dry_run,
            },
        )
        sentry_sdk.capture_message(
            f"CFTC scraper OK — COM NET US: {commercial_net:,.0f}", level="info"
        )

        logger.info("=" * 60)
        logger.info("SUCCESS: CFTC scraper completed")
        logger.info("=" * 60)
        return 0

    except CFTCScraperError as e:
        logger.error(f"CFTC scraper error: {e}")
        sentry_sdk.capture_exception(e)
        return 1

    except SheetsManagerError as e:
        logger.error(f"Sheets manager error: {e}")
        sentry_sdk.capture_exception(e)
        return 1

    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        sentry_sdk.capture_exception(e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
