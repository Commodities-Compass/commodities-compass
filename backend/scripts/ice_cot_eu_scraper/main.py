"""ICE COT EU scraper — daily idempotent ingestion to pl_cot_eu_weekly.

Usage:
    poetry run ice-cot-eu-scraper                # current year, live
    poetry run ice-cot-eu-scraper --dry-run
    poetry run ice-cot-eu-scraper --year 2024    # specific year (manual backfill)
    poetry run ice-cot-eu-scraper --verbose --force

Cron (prod):
    10 22 * * 1-5    # 22:10 UTC weekdays — ICE publishes Friday ~21:30 CET
                     # (≈19:30 UTC) for prior Tuesday's snapshot. Daily run +
                     # idempotent UPSERT on (release_date, contract_market)
                     # catches late publishes without coupling cron to ICE's
                     # exact publication time.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone

import sentry_sdk
from sentry_sdk.crons import monitor

from scripts._shared.cli import build_base_argparser
from scripts._shared.logging import configure_logging
from scripts._shared.sentry import bootstrap_scraper
from scripts.ice_cot_eu_scraper.db_writer import upsert_cot_eu_rows

configure_logging()
logger = logging.getLogger(__name__)

bootstrap_scraper("ice-cot-eu-scraper", script_file=__file__)


def _parse_args() -> argparse.Namespace:
    parser = build_base_argparser(
        "ICE Europe COT scraper (cocoa #7 weekly positioning)"
    )
    parser.add_argument(
        "--year",
        type=int,
        default=None,
        help=(
            "Calendar year to fetch (default: current UTC year). Use this to "
            "rescrape a specific historical year — UPSERT is idempotent."
        ),
    )
    return parser.parse_args()


@monitor(monitor_slug="ice-cot-eu-scraper")
def main() -> int:
    args = _parse_args()
    configure_logging(verbose=args.verbose)

    # Daily cron run: skip weekends + bank holidays unless --force. ICE only
    # publishes a new snapshot on Fridays anyway, but the daily idempotent
    # UPSERT lets us catch a late-publish without coupling cron to ICE's
    # schedule directly.
    from scripts.db import should_skip_non_trading_day

    if should_skip_non_trading_day(force=args.force):
        return 0

    year = args.year if args.year is not None else datetime.now(timezone.utc).year

    logger.info("=" * 60)
    logger.info("ICE COT EU Scraper — year=%d", year)
    logger.info("Mode: %s", "DRY RUN" if args.dry_run else "LIVE")
    logger.info("=" * 60)

    try:
        from scripts.ice_cot_eu_scraper.scraper import scrape_year

        observations = scrape_year(year)
        logger.info("Step 1: Fetched %d ICE COT EU rows", len(observations))

        if args.dry_run:
            logger.info("Step 2: [DRY RUN] Skipping DB write")
            tail = observations[-5:] if len(observations) >= 5 else observations
            for obs in tail:
                logger.info(
                    "  release=%s report=%s OI=%d MM_net=%d PM_net=%d",
                    obs.release_date,
                    obs.report_date,
                    obs.open_interest,
                    obs.m_money_long - obs.m_money_short,
                    obs.prod_merc_long - obs.prod_merc_short,
                )
        else:
            from scripts.db import get_session

            with get_session() as session:
                n_written = upsert_cot_eu_rows(session, observations)
                session.commit()
            logger.info("Step 2: Upserted %d rows into pl_cot_eu_weekly", n_written)

        sentry_sdk.set_context(
            "scrape_result",
            {
                "year": year,
                "n_records": len(observations),
                "dry_run": args.dry_run,
            },
        )

        logger.info("=" * 60)
        logger.info("SUCCESS: ICE COT EU scraper completed")
        logger.info("=" * 60)
        return 0

    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        logger.exception("ICE COT EU scraper failed: %s", exc)
        sentry_sdk.capture_exception(exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
