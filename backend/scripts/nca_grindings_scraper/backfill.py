"""One-shot backfill of NCA grindings into pl_supply_demand_observation.

Walks the chocolatecouncil.org listing page (~5-6 years of quarterly PDFs
hosted on candyusa.com), fetches and parses every PDF, UPSERTs the records,
and populates ``actual_publication_date`` on every matching calendar row.
"""

from __future__ import annotations

import argparse
import logging
import sys

import sentry_sdk

from scripts._shared.cli import build_base_argparser
from scripts._shared.logging import configure_logging
from scripts._shared.sentry import bootstrap_scraper
from scripts.nca_grindings_scraper.db_writer import upsert_nca_records
from scripts.nca_grindings_scraper.parser import NcaParseError
from scripts.nca_grindings_scraper.scraper import (
    NcaScraperError,
    discover_pdf_urls,
    fetch_and_parse,
)

configure_logging()
logger = logging.getLogger(__name__)

bootstrap_scraper("nca-grindings-scraper-backfill", script_file=__file__)


def _parse_args() -> argparse.Namespace:
    parser = build_base_argparser(
        "NCA grindings one-shot backfill (full listing)", include_force=False
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Re-parse every PDF and compare to DB rows (parser-drift detection).",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    configure_logging(verbose=args.verbose)

    logger.info("=" * 60)
    logger.info("NCA Grindings Backfill")
    logger.info("Mode: %s", "DRY RUN" if args.dry_run else "LIVE")
    if args.verify:
        logger.info("Mode: VERIFY (re-parse + compare)")
    logger.info("=" * 60)

    from scripts.db import get_session

    try:
        pdf_urls = discover_pdf_urls()
        n_processed = 0
        n_records = 0

        with get_session() as session:
            for period_label, pdf_url in sorted(pdf_urls.items()):
                try:
                    records = fetch_and_parse(period_label, pdf_url)
                except (NcaScraperError, NcaParseError) as exc:
                    logger.error(
                        "NCA backfill: failed %s (%s) — skipping",
                        period_label,
                        exc,
                    )
                    sentry_sdk.capture_exception(exc)
                    continue

                n_processed += 1
                n_records += len(records)

                if args.dry_run:
                    for rec in records:
                        logger.info(
                            "[DRY RUN] %s %s=%.2f (pub %s)",
                            rec.period_label,
                            rec.metric_name,
                            rec.value,
                            rec.publication_date,
                        )
                else:
                    upsert_nca_records(session, records, pdf_url=pdf_url)

            if not args.dry_run:
                session.commit()

        logger.info("=" * 60)
        logger.info(
            "SUCCESS: backfilled %d publications, %d records",
            n_processed,
            n_records,
        )
        logger.info("=" * 60)
        return 0

    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        logger.exception("NCA backfill failed: %s", exc)
        sentry_sdk.capture_exception(exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
