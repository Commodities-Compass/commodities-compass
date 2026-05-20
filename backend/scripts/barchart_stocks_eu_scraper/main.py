"""Barchart Stocks EU scraper — daily UPDATE on pl_contract_data_daily.

Usage:
    poetry run barchart-stocks-eu-scraper                # live
    poetry run barchart-stocks-eu-scraper --dry-run
    poetry run barchart-stocks-eu-scraper --verbose --force

Cron (prod):
    10 19 * * 1-5    # 19:10 UTC weekdays — 10 min after barchart OHLCV
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
from scripts.barchart_stocks_eu_scraper.db_writer import update_stock_eu

configure_logging()
logger = logging.getLogger(__name__)

bootstrap_scraper("barchart-stocks-eu-scraper", script_file=__file__)


def _parse_args() -> argparse.Namespace:
    parser = build_base_argparser(
        "Barchart cmdty Stock EU scraper (ICE certified stocks)"
    )
    return parser.parse_args()


@monitor(monitor_slug="barchart-stocks-eu-scraper")
def main() -> int:
    args = _parse_args()
    configure_logging(verbose=args.verbose)

    from scripts.db import should_skip_non_trading_day

    if should_skip_non_trading_day(force=args.force):
        return 0

    logger.info("=" * 60)
    logger.info("Barchart Stocks EU Scraper")
    logger.info("Mode: %s", "DRY RUN" if args.dry_run else "LIVE")
    logger.info("=" * 60)

    try:
        from scripts.barchart_stocks_eu_scraper.scraper import scrape_latest

        obs = scrape_latest()
        logger.info(
            "Step 1: Fetched %s = %s bags60kg (history rows: %d)",
            obs.date,
            obs.value_bags60kg,
            len(obs.history),
        )

        if args.dry_run:
            logger.info("Step 2: [DRY RUN] Skipping DB UPDATE")
            for d, v in obs.history[:5]:
                logger.info("  history: %s = %s bags60kg", d, v)
        else:
            from scripts.db import get_session

            with get_session() as session:
                n_updated = update_stock_eu(session, obs.date, obs.value_bags60kg)
                session.commit()
            logger.info("Step 2: Updated %d row in pl_contract_data_daily", n_updated)

        sentry_sdk.set_context(
            "scrape_result",
            {
                "date": obs.date.isoformat(),
                "value_bags60kg": str(obs.value_bags60kg),
                "history_rows": len(obs.history),
                "dry_run": args.dry_run,
            },
        )

        logger.info("=" * 60)
        logger.info("SUCCESS: Barchart Stocks EU scraper completed")
        logger.info("=" * 60)
        return 0

    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        logger.exception("Barchart Stocks EU scraper failed: %s", exc)
        sentry_sdk.capture_exception(exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
