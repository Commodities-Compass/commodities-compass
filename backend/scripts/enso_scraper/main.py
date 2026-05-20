"""ENSO scraper — monthly NOAA PSL ingestion to pl_external_indicator.

Usage:
    poetry run enso-scraper
    poetry run enso-scraper --dry-run
    poetry run enso-scraper --verbose

Cron (prod):
    0 22 20 * *      # 20 du mois 22:00 UTC, NOAA publishes ~mid-month
"""

from __future__ import annotations

import argparse
import logging
import sys

import sentry_sdk
from sentry_sdk.crons import monitor

from scripts._shared.cli import build_base_argparser
from scripts._shared.logging import configure_logging
from scripts._shared.sentry import bootstrap_scraper

configure_logging()
logger = logging.getLogger(__name__)

# ENSO is monthly (cron `0 22 20 * *`); no --force / non-trading-day skip.
bootstrap_scraper("enso-scraper", script_file=__file__)


def _parse_args() -> argparse.Namespace:
    parser = build_base_argparser(
        "NOAA PSL ENSO scraper (ONI + Niño 3.4)", include_force=False
    )
    return parser.parse_args()


@monitor(monitor_slug="enso-scraper")
def main() -> int:
    args = _parse_args()
    configure_logging(verbose=args.verbose)

    logger.info("=" * 60)
    logger.info("ENSO Scraper - NOAA PSL ONI + Niño 3.4")
    logger.info("Mode: %s", "DRY RUN" if args.dry_run else "LIVE")
    logger.info("=" * 60)

    try:
        # Step 1: Fetch both indices.
        from scripts.enso_scraper.scraper import scrape_all

        records = scrape_all()
        logger.info("Step 1: Fetched %d ENSO records", len(records))

        # Step 2: Write to DB (or skip on dry-run).
        if args.dry_run:
            logger.info("Step 2: [DRY RUN] Skipping DB write")
            tail = records[-5:] if len(records) >= 5 else records
            for rec in tail:
                logger.info("  %s %s=%.4f", rec.date, rec.value_name, rec.value)
        else:
            from scripts.enso_scraper.db_writer import upsert_enso_rows
            from scripts.db import get_session

            with get_session() as session:
                n_written = upsert_enso_rows(session, records)
                session.commit()
            logger.info(
                "Step 2: Upserted %d rows into pl_external_indicator", n_written
            )

        sentry_sdk.set_context(
            "scrape_result",
            {
                "n_records": len(records),
                "dry_run": args.dry_run,
            },
        )

        logger.info("=" * 60)
        logger.info("SUCCESS: ENSO scraper completed")
        logger.info("=" * 60)
        return 0

    except (KeyboardInterrupt, SystemExit):
        # Let OS signals + explicit exits propagate; don't classify them as
        # pipeline errors.
        raise
    except Exception as exc:
        # Fail-loud: log + Sentry + non-zero exit. NO retry, NO fallback.
        logger.exception("ENSO scraper failed: %s", exc)
        sentry_sdk.capture_exception(exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
