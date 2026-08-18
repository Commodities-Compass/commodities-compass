"""cc-compute-gauges — feed pl_dashboard_gauge, the algorithm-free gauge source.

The five technical gauges the dashboard renders (RSI / MACD / %K / ATR / VOL-OI)
used to be read off ``pl_indicator_daily.*_norm``, i.e. off whichever ALGORITHM
wrote that row. They therefore died with the algorithm — unacceptable for a
bascule, and conceptually wrong: a gauge describes the market, not a decision.

This job recomputes them from ``pl_derived_indicators`` over the canonical
front-month chain and stores all three stages (raw → 5d SMA → 252d z-score).
It touches no algorithm table and reads no algorithm config.

Runs after cc-compute-indicators (which fills pl_derived_indicators) and before
the decision jobs, though nothing depends on that ordering beyond freshness.

Usage:
    poetry run compute-gauges                    # cron: whole chain, upsert
    poetry run compute-gauges --dry-run --verbose
    poetry run compute-gauges --backfill-days 250   # limit to the last N sessions
"""

from __future__ import annotations

import logging
import sys

import sentry_sdk
from sentry_sdk.crons import monitor

from scripts._shared.cli import build_base_argparser
from scripts._shared.logging import configure_logging
from scripts._shared.sentry import bootstrap_scraper
from scripts.compute_gauges.computer import (
    GAUGE_SPECS,
    compute_gauge_frame,
    load_derived_chain,
    to_gauge_rows,
)
from scripts.compute_gauges.db_writer import upsert_gauges

configure_logging()
logger = logging.getLogger(__name__)

bootstrap_scraper("compute-gauges", script_file=__file__)


def _parse_args():
    parser = build_base_argparser(
        "Compute the dashboard technical gauges (algorithm-independent)",
        include_force=False,
    )
    parser.add_argument(
        "--backfill-days",
        type=int,
        default=None,
        help=(
            "Only write the last N sessions. The z-score still needs the full "
            "history to be computed, so this limits the WRITE, never the read."
        ),
    )
    return parser.parse_args()


@monitor(monitor_slug="compute-gauges")
def main() -> int:
    args = _parse_args()
    configure_logging(verbose=args.verbose)

    from scripts.db import get_session

    with get_session() as session:
        chain = load_derived_chain(session)
        logger.info(
            "derived chain: %d sessions [%s..%s]",
            len(chain),
            chain["date"].min().date(),
            chain["date"].max().date(),
        )

        # The rolling windows need the WHOLE history to be correct; only the
        # write window is narrowed. Trimming the input instead would silently
        # produce wrong z-scores for the first ~252 rows of the slice.
        frame = compute_gauge_frame(chain)
        if args.backfill_days:
            frame = frame.tail(args.backfill_days)
            logger.info("limiting write window to the last %d sessions", len(frame))

        rows = to_gauge_rows(frame)
        logger.info(
            "%d gauge rows over %d sessions × %d indicators",
            len(rows),
            len(frame),
            len(GAUGE_SPECS),
        )

        if args.dry_run:
            for row in rows[-len(GAUGE_SPECS) :]:
                logger.info(
                    "  [DRY RUN] %s %-6s raw=%s score=%s norm=%s",
                    row["date"],
                    row["indicator_name"],
                    row["raw_value"],
                    row["score_value"],
                    row["norm_value"],
                )
            logger.info("[DRY RUN] %d rows computed, nothing written", len(rows))
            written = 0
        else:
            written = upsert_gauges(session, rows)
            session.commit()
            logger.info("wrote %d gauge rows", written)

    sentry_sdk.set_context(
        "compute_gauges",
        {
            "sessions": len(frame),
            "rows": len(rows),
            "written": written,
            "dry_run": args.dry_run,
        },
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
