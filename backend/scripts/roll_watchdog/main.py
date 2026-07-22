"""Watchdog: nudge the operator when it's time to roll the contract.

The front-month is operator-controlled (``ref_contract.active_from``, set by
``roll-contract``). Liquidity (open interest + volume) no longer *decides* the
roll — but it is the signal that a roll is *due*: when the next delivery month
starts leading on BOTH OI and volume for several consecutive sessions while the
calendar still points at the incumbent, the operator should roll.

This job compares, per recent session, the LIQUIDITY front-month (the old
"leads on both OI and volume, else incumbent" rule) against the CALENDAR
front-month (``active_from`` lookup). If they diverge for
``--threshold`` consecutive sessions (most recent first), it fires a Sentry
alert telling the operator exactly which ``roll-contract`` to run. It never
changes any data — it only turns silent divergence into a visible nudge.

Usage:
    poetry run roll-watchdog
    poetry run roll-watchdog --dry-run --threshold 3

Cron (prod):
    45 19 * * 1-5    # 19:45 UTC weekdays, after compute-indicators
"""

from __future__ import annotations

import argparse
import logging
import sys

import sentry_sdk
from sentry_sdk.crons import monitor
from sqlalchemy import text

from scripts._shared.cli import build_base_argparser
from scripts._shared.logging import configure_logging
from scripts._shared.sentry import bootstrap_scraper

configure_logging()
logger = logging.getLogger(__name__)

bootstrap_scraper("roll-watchdog", script_file=__file__)


# Consecutive sessions the liquidity front-month must lead beyond the calendar
# before we nudge the operator. 3 filters one-day OI/volume blips (the class of
# false roll that caused the 2026-07-17 split-brain).
DEFAULT_THRESHOLD = 3

# Liquidity front-month per date (old "leads on both OI AND volume, else
# incumbent by contract_month") joined to the calendar front-month per date.
_QUERY = text(
    """
    WITH per_date AS (
        SELECT date,
               MAX(COALESCE(oi, 0))     AS max_oi,
               MAX(COALESCE(volume, 0)) AS max_vol
        FROM pl_contract_data_daily
        WHERE close IS NOT NULL
        GROUP BY date
    ),
    liq AS (
        SELECT DISTINCT ON (d.date)
               d.date,
               c.code AS liq_code,
               c.active_from AS liq_active_from
        FROM pl_contract_data_daily d
        JOIN ref_contract c ON c.id = d.contract_id
        JOIN per_date pd ON pd.date = d.date
        WHERE d.close IS NOT NULL
        ORDER BY d.date,
            (COALESCE(d.oi, 0) >= pd.max_oi
             AND COALESCE(d.volume, 0) >= pd.max_vol) DESC,
            c.contract_month ASC
    )
    SELECT liq.date,
           liq.liq_code,
           liq.liq_active_from,
           (SELECT c.code FROM ref_contract c
             WHERE c.active_from IS NOT NULL
               AND c.active_from <= liq.date
             ORDER BY c.active_from DESC
             LIMIT 1) AS cal_code
    FROM liq
    ORDER BY liq.date DESC
    LIMIT :lookback
    """
)


def _parse_args() -> argparse.Namespace:
    parser = build_base_argparser(
        "Roll watchdog (nudge when liquidity front-month leads the calendar)",
        include_force=False,
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=DEFAULT_THRESHOLD,
        help=(
            f"Consecutive diverging sessions before alerting "
            f"(default: {DEFAULT_THRESHOLD})."
        ),
    )
    return parser.parse_args()


@monitor(monitor_slug="roll-watchdog")
def main() -> int:
    args = _parse_args()
    configure_logging(verbose=args.verbose)
    threshold = args.threshold

    logger.info("=" * 60)
    logger.info("Roll Watchdog")
    logger.info(
        "Mode: %s (threshold=%d consecutive sessions)",
        "DRY RUN" if args.dry_run else "LIVE",
        threshold,
    )
    logger.info("=" * 60)

    from scripts.db import get_session

    try:
        with get_session() as session:
            rows = session.execute(_QUERY, {"lookback": threshold + 5}).all()

        if not rows:
            logger.info("No market data to evaluate. Exit clean.")
            return 0

        # Count the leading run (most recent first) of liquidity-vs-calendar
        # divergence. A single non-diverging (or missing) session resets it.
        # rows are DESC, so rows[0] is the most recent — the diverging contract.
        consecutive = 0
        for row in rows:
            if row.liq_code and row.cal_code and row.liq_code != row.cal_code:
                consecutive += 1
            else:
                break

        logger.info(
            "Latest session: liquidity=%s calendar=%s — divergence run=%d",
            rows[0].liq_code,
            rows[0].cal_code,
            consecutive,
        )

        if consecutive < threshold:
            logger.info("No roll due (divergence run < %d). Exit clean.", threshold)
            return 0

        diverged_to = rows[0].liq_code
        calendar_code = rows[0].cal_code

        if rows[0].liq_active_from is not None:
            # The diverging liquidity contract is already IN the calendar (a
            # past/current contract, not a future one) → this is a BACKWARD
            # divergence: a post-roll OI blip, or a deliberate early roll where
            # the market briefly lags. Never instruct a backward roll.
            logger.info(
                "Liquidity front-month %s trails the calendar %s for %d sessions "
                "(backward divergence — no roll suggested). Exit clean.",
                diverged_to,
                calendar_code,
                consecutive,
            )
            return 0

        # liq_active_from IS NULL → a genuine FORWARD-roll candidate: the market
        # has moved to a contract the operator has not rolled to yet.
        msg = (
            f"Roll due: {diverged_to} has led OI+volume for {consecutive} "
            f"consecutive sessions while the calendar front-month is "
            f"{calendar_code}. Run: roll-contract {diverged_to}"
        )
        logger.warning(msg)
        sentry_sdk.set_context(
            "roll_due",
            {
                "liquidity_front_month": diverged_to,
                "calendar_front_month": calendar_code,
                "consecutive_sessions": consecutive,
                "threshold": threshold,
            },
        )
        sentry_sdk.capture_message(msg, level="warning")

        # Non-zero so the cron monitor surfaces the nudge even if nobody is
        # watching Sentry directly (same convention as publication-watchdog).
        return 1

    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        logger.exception("Roll watchdog failed: %s", exc)
        sentry_sdk.capture_exception(exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
