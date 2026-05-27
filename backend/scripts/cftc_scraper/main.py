"""CFTC scraper — daily runner for CFTC US Disaggregated COT (cocoa).

Refactored 2026-05-27: writes one UPSERT row per real CFTC release into
``pl_cot_us_weekly``, mirroring ``cc-ice-cot-eu-scraper``. The previous
behavior (overwrite ``pl_contract_data_daily.com_net_us`` every weekday
with the same Friday-released value) is gone.
"""

from __future__ import annotations

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


# CFTC publishes Friday for Tuesday snapshot. Allow up to 14 days latency
# before flagging the publisher as stale — covers federal holidays that
# shift Friday's release to Monday.
STALE_OBSERVATION_DAYS = 14


@monitor(monitor_slug="cftc-scraper")
def main() -> int:
    parser = argparse.ArgumentParser(
        description="CFTC Disaggregated COT scraper (cocoa)"
    )
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
    logger.info("CFTC Scraper — Disaggregated COT (cocoa)")
    logger.info("Mode: %s", "DRY RUN" if args.dry_run else "LIVE")
    logger.info("=" * 60)

    try:
        logger.info("Step 1: Scraping CFTC report...")
        scraper = CFTCScraper()
        obs = scraper.scrape(max_stale_days=STALE_OBSERVATION_DAYS)

        logger.info(
            "Parsed: report_date=%s release_date=%s prod_merc_net=%d "
            "m_money_net=%d open_interest=%d",
            obs.report_date,
            obs.release_date,
            obs.prod_merc_net,
            obs.m_money_net,
            obs.open_interest,
        )

        logger.info("Step 2: Writing to GCP PostgreSQL...")
        from scripts.cftc_scraper.db_writer import upsert_cot_us_weekly
        from scripts.db import get_session

        with get_session() as session:
            upsert_cot_us_weekly(session, obs, dry_run=args.dry_run)
            session.commit()

        sentry_sdk.set_context(
            "scrape_result",
            {
                "release_date": obs.release_date.isoformat(),
                "report_date": obs.report_date.isoformat(),
                "prod_merc_net": obs.prod_merc_net,
                "m_money_net": obs.m_money_net,
                "open_interest": obs.open_interest,
                "dry_run": args.dry_run,
            },
        )

        logger.info("=" * 60)
        logger.info("SUCCESS: CFTC scraper completed")
        logger.info("=" * 60)
        return 0

    except CFTCScraperError as exc:
        logger.error("CFTC scraper error: %s", exc)
        sentry_sdk.capture_exception(exc)
        return 1
    except Exception as exc:
        logger.exception("Unexpected error: %s", exc)
        sentry_sdk.capture_exception(exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
