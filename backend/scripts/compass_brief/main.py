"""CLI entry point for the Compass Brief generator.

Usage:
    # Dry run — generate brief, print to stdout, no upload
    poetry run compass-brief --dry-run

    # Generate and upload to Drive
    poetry run compass-brief

    # Generate, save locally, and upload
    poetry run compass-brief --output /tmp/brief.txt

    # Verbose logging
    poetry run compass-brief --dry-run --verbose
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

import sentry_sdk
from dotenv import load_dotenv
from sentry_sdk.crons import monitor

from app.core.sentry import init_sentry
from scripts.compass_brief.brief_generator import generate_brief
from scripts.compass_brief.config import (
    get_credentials_json,
    get_drive_briefs_folder_id,
)
from scripts.compass_brief.drive_uploader import DriveUploader
from scripts.compass_brief.sheets_reader import SheetsReader

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"

logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

load_dotenv(Path(__file__).parent.parent.parent / ".env")
init_sentry("compass-brief")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Commodities Compass — Daily Brief Generator"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate brief and print to stdout, no upload",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Save brief to a local file path",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging",
    )
    return parser.parse_args()


@monitor(monitor_slug="compass-brief")
def main() -> int:
    args = _parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    logger.info("=" * 60)
    logger.info("Compass Brief Generator")
    logger.info("Mode: %s", "DRY RUN" if args.dry_run else "UPLOAD")
    logger.info("=" * 60)

    try:
        # 1. Read data from Sheets
        creds = get_credentials_json()
        reader = SheetsReader(creds)
        data = reader.read_all()

        # 2. Generate brief text
        brief = generate_brief(data)

        # 3. Derive filename from today's date in TECHNICALS
        dt = datetime.strptime(data.today.date, "%m/%d/%Y")
        filename = f"{dt.strftime('%Y%m%d')}-CompassBrief.txt"

        logger.info("Generated brief: %s (%d chars)", filename, len(brief))

        # 4. Save locally if requested
        if args.output:
            Path(args.output).write_text(brief, encoding="utf-8")
            logger.info("Saved to %s", args.output)

        # 5. Print to stdout in dry-run mode
        if args.dry_run:
            print("\n" + brief)
            return 0

        # 6. Upload to Drive
        uploader = DriveUploader(creds)
        folder_id = get_drive_briefs_folder_id()
        file_id = uploader.upload(brief, filename, folder_id)

        sentry_sdk.set_context(
            "compass_brief",
            {
                "today": data.today.date,
                "yesterday": data.yesterday.date,
                "filename": filename,
                "brief_chars": len(brief),
                "file_id": file_id,
            },
        )

        logger.info("=" * 60)
        logger.info("SUCCESS — %s uploaded (id=%s)", filename, file_id)
        logger.info("=" * 60)
        return 0

    except Exception as exc:
        logger.exception("Failed: %s", exc)
        sentry_sdk.capture_exception(exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
