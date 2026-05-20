"""FX scraper — daily ECB SDMX ingestion to pl_external_indicator.

Usage:
    poetry run fx-scraper
    poetry run fx-scraper --dry-run
    poetry run fx-scraper --force --verbose

Cron (prod):
    30 18 * * 1-5    # 18:30 UTC business days, before cc-ensemble-compute (19:18)
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

bootstrap_scraper("fx-scraper", script_file=__file__)


def _parse_args() -> argparse.Namespace:
    parser = build_base_argparser("ECB SDMX FX scraper (USD/EUR + GBP/EUR)")
    return parser.parse_args()


@monitor(monitor_slug="fx-scraper")
def main() -> int:
    args = _parse_args()
    configure_logging(verbose=args.verbose)

    # Skip on non-trading days unless --force (ECB doesn't publish on weekends
    # and some EU bank holidays; skipping aligns with the rest of the pipeline).
    from scripts.db import should_skip_non_trading_day

    if should_skip_non_trading_day(force=args.force):
        return 0

    logger.info("=" * 60)
    logger.info("FX Scraper - ECB SDMX (USD/EUR + GBP/EUR)")
    logger.info("Mode: %s", "DRY RUN" if args.dry_run else "LIVE")
    logger.info("=" * 60)

    try:
        from scripts.fx_scraper.scraper import scrape_all

        records = scrape_all()
        logger.info("Step 1: Computed %d FX records", len(records))

        if args.dry_run:
            logger.info("Step 2: [DRY RUN] Skipping DB write")
            tail = records[-5:] if len(records) >= 5 else records
            for rec in tail:
                logger.info(
                    "  %s  dxy=%s  gbpusd=%s",
                    rec.date,
                    f"{rec.fx_dxy_proxy:.6f}"
                    if rec.fx_dxy_proxy is not None
                    else "N/A",
                    f"{rec.fx_gbpusd:.6f}" if rec.fx_gbpusd is not None else "N/A",
                )
        else:
            from scripts.db import get_session
            from scripts.fx_scraper.db_writer import upsert_fx_rows

            with get_session() as session:
                n_written = upsert_fx_rows(session, records)
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
        logger.info("SUCCESS: FX scraper completed")
        logger.info("=" * 60)
        return 0

    except (KeyboardInterrupt, SystemExit):
        # Let OS signals + explicit exits propagate; don't classify them as
        # pipeline errors.
        raise
    except Exception as exc:
        # Fail-loud: log + Sentry + non-zero exit. NO retry, NO fallback.
        logger.exception("FX scraper failed: %s", exc)
        sentry_sdk.capture_exception(exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
