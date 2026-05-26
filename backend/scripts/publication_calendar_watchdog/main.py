"""Watchdog: alert on overdue fundamentals publications.

Daily cron job that queries ``ref_publication_calendar`` for rows where::

    actual_publication_date IS NULL
    AND expected_publication_date < today - GRACE_DAYS

i.e. publications that were expected ≥ GRACE_DAYS ago but never made it into
``pl_supply_demand_observation``. Likely causes:
  * Publisher (ECA / NCA) skipped or delayed the release.
  * Their PDF URL pattern drifted and our discovery regex no longer matches.
  * Our parser broke on a layout change.

The job logs each overdue row at ERROR and captures a Sentry alert. It does
NOT try to re-fetch — that is the daily scraper's job. The watchdog only
makes silence VISIBLE.

Usage:
    poetry run publication-calendar-watchdog
    poetry run publication-calendar-watchdog --dry-run

Cron (prod):
    0 16 * * 1-5    # 16:00 UTC weekdays
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta

import sentry_sdk
from sentry_sdk.crons import monitor
from sqlalchemy import text

from scripts._shared.cli import build_base_argparser
from scripts._shared.logging import configure_logging
from scripts._shared.sentry import bootstrap_scraper

configure_logging()
logger = logging.getLogger(__name__)

bootstrap_scraper("publication-calendar-watchdog", script_file=__file__)


# Days past expected_publication_date before we flag a row as missing.
# Larger than the daily-scraper tolerance window (14 days) so a normal
# publication delay doesn't trigger immediately.
DEFAULT_GRACE_DAYS = 21


def _parse_args() -> argparse.Namespace:
    parser = build_base_argparser(
        "Publication calendar watchdog (alert on overdue fundamentals)",
        include_force=False,
    )
    parser.add_argument(
        "--grace-days",
        type=int,
        default=DEFAULT_GRACE_DAYS,
        help=(
            f"Alert when expected_publication_date < today - this many days "
            f"(default: {DEFAULT_GRACE_DAYS})."
        ),
    )
    return parser.parse_args()


@monitor(monitor_slug="publication-calendar-watchdog")
def main() -> int:
    args = _parse_args()
    configure_logging(verbose=args.verbose)
    grace_days = args.grace_days

    cutoff = date.today() - timedelta(days=grace_days)
    logger.info("=" * 60)
    logger.info("Publication Calendar Watchdog")
    logger.info(
        "Mode: %s (grace=%dd, cutoff=%s)",
        "DRY RUN" if args.dry_run else "LIVE",
        grace_days,
        cutoff,
    )
    logger.info("=" * 60)

    from scripts.db import get_session

    try:
        with get_session() as session:
            rows = session.execute(
                text(
                    """
                    SELECT source, category, region, period_label,
                           expected_publication_date,
                           CURRENT_DATE - expected_publication_date AS days_late
                    FROM ref_publication_calendar
                    WHERE actual_publication_date IS NULL
                      AND expected_publication_date <= :cutoff
                    ORDER BY expected_publication_date ASC
                    """
                ),
                {"cutoff": cutoff},
            ).all()

        if not rows:
            logger.info("All fundamental publications on track. Exit clean.")
            return 0

        logger.error(
            "Found %d overdue publication(s) (≥ %d days late):", len(rows), grace_days
        )
        for row in rows:
            source, category, region, period_label, expected, days_late = row
            logger.error(
                "  %s/%s/%s %s — expected %s, %d days late",
                source,
                category,
                region or "—",
                period_label,
                expected,
                days_late,
            )

        # Fail-loud: send a Sentry event so the on-call sees it
        # (cron monitor reports SUCCESS for return 0; we use a capture instead).
        sentry_sdk.set_context(
            "overdue_publications",
            {
                "count": len(rows),
                "grace_days": grace_days,
                "items": [
                    f"{r[0]}/{r[3]} (expected {r[4]}, {r[5]}d late)" for r in rows
                ],
            },
        )
        sentry_sdk.capture_message(
            f"{len(rows)} overdue fundamental publication(s) (≥ {grace_days} days)",
            level="error",
        )

        # Return non-zero so the cron monitor flags an issue even if no human
        # is watching Sentry directly.
        return 1

    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        logger.exception("Watchdog failed: %s", exc)
        sentry_sdk.capture_exception(exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
