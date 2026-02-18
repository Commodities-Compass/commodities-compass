"""CLI entry point for Barchart scraper."""

import argparse
import logging
import os
import sys
from pathlib import Path

import sentry_sdk
from dotenv import load_dotenv
from sentry_sdk.crons import monitor

from app.core.sentry import init_sentry
from scripts.barchart_scraper.config import (
    LOG_FORMAT,
    SHEET_NAME_PRODUCTION,
    SHEET_NAME_STAGING,
)
from scripts.barchart_scraper.scraper import BarchartScraper, BarchartScraperError
from scripts.barchart_scraper.sheets_writer import SheetsWriter, SheetsWriterError
from scripts.barchart_scraper.validator import DataValidator

logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def load_credentials() -> str:
    """
    Load Google Sheets credentials from environment.
    Uses GOOGLE_SHEETS_SCRAPER_CREDENTIALS_JSON (scraper-specific read-write SA).

    Returns:
        Credentials JSON string

    Raises:
        RuntimeError: If credentials not found
    """
    creds = os.getenv("GOOGLE_SHEETS_SCRAPER_CREDENTIALS_JSON")
    if not creds:
        raise RuntimeError(
            "GOOGLE_SHEETS_SCRAPER_CREDENTIALS_JSON environment variable not set. "
            "See .env.example for setup instructions."
        )
    return creds


# Load env + init Sentry BEFORE @monitor-decorated function
load_dotenv(Path(__file__).parent.parent.parent / ".env")
init_sentry("barchart-scraper")


@monitor(monitor_slug="barchart-scraper")
def main() -> int:
    """
    Main entry point.

    Returns:
        Exit code (0 = success, 1 = failure)
    """
    parser = argparse.ArgumentParser(
        description="Barchart scraper for London cocoa futures"
    )
    parser.add_argument(
        "--sheet",
        choices=["staging", "production"],
        default="staging",
        help="Target sheet: 'staging' (TECHNICALS_STAGING) or 'production' (TECHNICALS)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run scraper and validation, but don't write to Sheets (for testing)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--headful",
        action="store_true",
        help="Run browser in non-headless mode (visible, for debugging)",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    logger.info("=" * 60)
    logger.info("Barchart Scraper - London Cocoa #7 (CA*0)")
    logger.info(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    logger.info(f"Target: {args.sheet.upper()}")
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

        # Step 3: Write to Sheets
        sheet_name = (
            SHEET_NAME_STAGING if args.sheet == "staging" else SHEET_NAME_PRODUCTION
        )
        logger.info(f"Step 3: Writing to Google Sheets ({sheet_name})...")

        creds = load_credentials()
        writer = SheetsWriter(creds)
        writer.append_row(data, sheet_name=sheet_name, dry_run=args.dry_run)

        sentry_sdk.set_context(
            "scrape_result",
            {
                "date": str(data.get("date")),
                "contract": str(data.get("contract_code")),
                "close": str(data.get("close")),
                "volume": str(data.get("volume")),
                "oi": str(data.get("open_interest")),
                "iv": str(data.get("iv")),
                "sheet": sheet_name,
                "dry_run": args.dry_run,
            },
        )
        sentry_sdk.capture_message("Barchart scraper OK", level="info")

        logger.info("=" * 60)
        logger.info("SUCCESS: Scraper completed successfully")
        logger.info("=" * 60)
        return 0

    except BarchartScraperError as e:
        logger.error(f"Scraper error: {e}")
        sentry_sdk.capture_exception(e)
        return 1
    except SheetsWriterError as e:
        logger.error(f"Sheets writer error: {e}")
        sentry_sdk.capture_exception(e)
        return 1
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        sentry_sdk.capture_exception(e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
