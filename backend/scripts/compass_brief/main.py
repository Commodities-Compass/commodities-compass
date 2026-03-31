"""CLI entry point for the Compass Brief generator.

Usage:
    # DB mode (new — no Sheets dependency)
    poetry run compass-brief --db --dry-run
    poetry run compass-brief --db

    # Legacy Sheets mode
    poetry run compass-brief --dry-run
    poetry run compass-brief

    # Save locally
    poetry run compass-brief --db --output /tmp/brief.txt
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
        "--db",
        action="store_true",
        help="Read from pl_* tables instead of Google Sheets",
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
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run even on non-trading days (for backfills/debugging)",
    )
    return parser.parse_args()


def _read_from_db():
    """Read brief data from database."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.core.config import settings
    from scripts.compass_brief.db_reader import DBBriefReader

    db_url = str(settings.DATABASE_SYNC_URL)
    engine = create_engine(db_url)

    with Session(engine) as session:
        reader = DBBriefReader(session)
        return reader.read_all()


def _read_from_sheets():
    """Read brief data from Google Sheets (legacy)."""
    from scripts.compass_brief.sheets_reader import SheetsReader

    creds = get_credentials_json()
    reader = SheetsReader(creds)
    return reader.read_all()


@monitor(monitor_slug="compass-brief")
def main() -> int:
    args = _parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Skip on non-trading days unless --force
    from scripts.db import should_skip_non_trading_day

    if should_skip_non_trading_day(force=args.force):
        return 0

    mode = "DB" if args.db else "SHEETS"
    logger.info("=" * 60)
    logger.info("Compass Brief Generator (%s)", mode)
    logger.info("Mode: %s", "DRY RUN" if args.dry_run else "UPLOAD")
    logger.info("=" * 60)

    try:
        # 1. Read data
        if args.db:
            data = _read_from_db()
        else:
            data = _read_from_sheets()

        # 2. Generate brief text
        brief = generate_brief(data)

        # 3. Derive filename from today's date
        dt = datetime.strptime(data.today.date, "%m/%d/%Y")
        filename = f"{dt.strftime('%Y%m%d')}-CompassBrief.txt"

        logger.info("Generated brief: %s (%d chars)", filename, len(brief))
        logger.info("Today: %s | Yesterday: %s", data.today.date, data.yesterday.date)

        # 4. Save locally if requested
        if args.output:
            Path(args.output).write_text(brief, encoding="utf-8")
            logger.info("Saved to %s", args.output)

        # 5. Print to stdout in dry-run mode
        if args.dry_run:
            print("\n" + brief)
            return 0

        # 6. Upload to Drive
        creds = get_credentials_json()
        uploader = DriveUploader(creds)
        folder_id = get_drive_briefs_folder_id()
        file_id = uploader.upload(brief, filename, folder_id)

        sentry_sdk.set_context(
            "compass_brief",
            {
                "source": mode,
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
