"""NCA grindings scraper — daily entry point (calendar-gated).

Usage:
    poetry run nca-grindings-scraper
    poetry run nca-grindings-scraper --dry-run
    poetry run nca-grindings-scraper --verbose

Cron (prod):
    0 14 * * 1-5    # 14:00 UTC weekdays (NCA publishes ~mid-day ET)

Mirrors the ECA scraper: gate against ref_publication_calendar, discover
PDFs via chocolatecouncil.org listing, fetch + parse + UPSERT, and mark the
calendar row as ingested. Fail-loud, no auto-retry.
"""

from __future__ import annotations

import argparse
import logging
import sys

import sentry_sdk
from sentry_sdk.crons import monitor

from scripts._shared.cli import build_base_argparser
from scripts._shared.logging import configure_logging
from scripts._shared.publication_calendar import (
    PendingPublication,
    find_pending_publications,
)
from scripts._shared.sentry import bootstrap_scraper
from scripts.nca_grindings_scraper.config import SOURCE
from scripts.nca_grindings_scraper.db_writer import upsert_nca_records
from scripts.nca_grindings_scraper.scraper import (
    NcaScraperError,
    discover_pdf_urls,
    fetch_and_parse,
)

configure_logging()
logger = logging.getLogger(__name__)

bootstrap_scraper("nca-grindings-scraper", script_file=__file__)


def _parse_args() -> argparse.Namespace:
    parser = build_base_argparser(
        "NCA North-American Cocoa Grindings scraper", include_force=False
    )
    return parser.parse_args()


def _process_pending(
    session,
    pending: list[PendingPublication],
    pdf_urls: dict[str, str],
    *,
    dry_run: bool,
) -> tuple[int, int]:
    n_processed = 0
    n_records = 0
    for pub in pending:
        pdf_url = pdf_urls.get(pub.period_label)
        if not pdf_url:
            logger.info(
                "NCA %s: no PDF on listing yet (expected %s ± %dd)",
                pub.period_label,
                pub.expected_publication_date,
                pub.tolerance_days,
            )
            continue

        records = fetch_and_parse(pub.period_label, pdf_url)
        n_records += len(records)
        n_processed += 1

        if dry_run:
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

    return n_processed, n_records


@monitor(monitor_slug="nca-grindings-scraper")
def main() -> int:
    args = _parse_args()
    configure_logging(verbose=args.verbose)

    logger.info("=" * 60)
    logger.info("NCA Grindings Scraper")
    logger.info("Mode: %s", "DRY RUN" if args.dry_run else "LIVE")
    logger.info("=" * 60)

    from scripts.db import get_session

    try:
        with get_session() as session:
            pending = find_pending_publications(session, source=SOURCE)
            if not pending:
                logger.info("No pending NCA publications today — exiting clean.")
                return 0

            pdf_urls = discover_pdf_urls()
            n_processed, n_records = _process_pending(
                session, pending, pdf_urls, dry_run=args.dry_run
            )

            if not args.dry_run:
                session.commit()

        sentry_sdk.set_context(
            "scrape_result",
            {
                "n_pending": len(pending),
                "n_processed": n_processed,
                "n_records": n_records,
                "dry_run": args.dry_run,
            },
        )

        logger.info("=" * 60)
        logger.info(
            "SUCCESS: %d/%d publications, %d records",
            n_processed,
            len(pending),
            n_records,
        )
        logger.info("=" * 60)
        return 0

    except (KeyboardInterrupt, SystemExit):
        raise
    except NcaScraperError as exc:
        logger.exception("NCA scraper failed: %s", exc)
        sentry_sdk.capture_exception(exc)
        return 1
    except Exception as exc:
        logger.exception("NCA scraper failed (unexpected): %s", exc)
        sentry_sdk.capture_exception(exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
