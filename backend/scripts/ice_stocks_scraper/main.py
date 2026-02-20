"""CLI entry point for ICE Certified Cocoa Stocks scraper.

Downloads public XLS from ice.com, parses certified stock data,
writes to Google Sheets column H (STOCK US).

No browser, no reCAPTCHA, no cookies. Just httpx.
"""

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import sentry_sdk
from dotenv import load_dotenv
from sentry_sdk.crons import monitor

from app.core.sentry import init_sentry
from scripts.ice_stocks_scraper.config import LOG_FORMAT
from scripts.ice_stocks_scraper.scraper import ICEScraperError, scrape
from scripts.ice_stocks_scraper.sheets_manager import SheetsManager, SheetsManagerError

logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# Load env + init Sentry BEFORE @monitor-decorated function
load_dotenv(Path(__file__).parent.parent.parent / ".env")
init_sentry("ice-stocks-scraper")


@monitor(monitor_slug="ice-stocks-scraper")
def main() -> int:
    parser = argparse.ArgumentParser(
        description="ICE Certified Cocoa Stocks scraper (Report 41)"
    )
    parser.add_argument("--sheet", choices=["staging", "production"], default="staging")
    parser.add_argument(
        "--dry-run", action="store_true", help="Parse + validate, no Sheets write"
    )
    parser.add_argument(
        "--date", type=str, default=None, help="Target date YYYY-MM-DD (default: today)"
    )
    parser.add_argument("--verbose", action="store_true")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    target_date = None
    if args.date:
        target_date = datetime.strptime(args.date, "%Y-%m-%d").date()

    logger.info("=" * 60)
    logger.info("ICE Certified Cocoa Stocks (Report 41)")
    logger.info(
        f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'} | Sheet: {args.sheet.upper()}"
    )
    logger.info(f"Date: {target_date or 'today'}")
    logger.info("=" * 60)

    try:
        # Step 1: Download + parse XLS
        logger.info("Step 1: Downloading ICE XLS...")
        data = scrape(target_date)

        grand_total_bags = data.get("grand_total_bags")
        certified_bags = data["certified_total_bags"]
        report_date = data.get("actual_date", "?")

        if grand_total_bags is None:
            raise ICEScraperError("Could not extract grand total from XLS")

        stock_us_tonnes = int(grand_total_bags * 70 / 1000)

        logger.info(f"Step 2: Report {report_date}")
        logger.info(
            f"  Grand total:     {grand_total_bags:,} bags = {stock_us_tonnes:,} tonnes"
        )
        logger.info(f"  Certified stock: {certified_bags:,} bags")
        logger.info(
            f"  DR port:         {data.get('port_dr_bags', '?'):,} bags"
            if data.get("port_dr_bags")
            else ""
        )
        logger.info(
            f"  NY port:         {data.get('port_ny_bags', '?'):,} bags"
            if data.get("port_ny_bags")
            else ""
        )

        # Step 3: Write to Sheets (grand total converted to tonnes)
        logger.info(f"Step 3: Writing to Google Sheets ({args.sheet})...")
        creds = os.getenv("GOOGLE_SHEETS_SCRAPER_CREDENTIALS_JSON")
        if not creds:
            raise RuntimeError("GOOGLE_SHEETS_SCRAPER_CREDENTIALS_JSON not set")

        sheets_mgr = SheetsManager(creds, sheet_name=args.sheet)
        cell_range = sheets_mgr.update_latest_row(stock_us_tonnes, dry_run=args.dry_run)

        sentry_sdk.set_context(
            "scrape_result",
            {
                "report_date": str(report_date),
                "stock_us_tonnes": stock_us_tonnes,
                "grand_total_bags": grand_total_bags,
                "certified_bags": certified_bags,
                "sheet": args.sheet,
                "dry_run": args.dry_run,
            },
        )

        logger.info("=" * 60)
        logger.info(
            f"SUCCESS: STOCK US = {stock_us_tonnes:,} t ({grand_total_bags:,} bags) -> {cell_range}"
        )
        logger.info("=" * 60)
        return 0

    except ICEScraperError as e:
        logger.error(f"Scraper error: {e}")
        sentry_sdk.capture_exception(e)
        return 1

    except SheetsManagerError as e:
        logger.error(f"Sheets error: {e}")
        sentry_sdk.capture_exception(e)
        return 1

    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        sentry_sdk.capture_exception(e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
