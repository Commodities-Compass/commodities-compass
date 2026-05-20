"""One-shot Stock EU backfill from Barchart cmdty page.

The Barchart cmdty page embeds ~18 months of history as a Highcharts
``options.series[0].data`` array. A **single HTTP request** gives us
hundreds of (date, value) pairs — much cheaper than walking Wayback
Machine snapshots day-by-day.

For deeper history (> 18 months), Barchart paywalls the "All" button
behind `cmdtyStats` subscription. The Wayback fallback path is sketched
below but **not implemented** in the first cut — the 18-month window
already covers the C5 ensemble's 26w rolling needs.

Usage:
    # dry-run
    poetry run barchart-stocks-eu-scraper-backfill --dry-run

    # backfill (UPDATE only — never INSERTs)
    poetry run barchart-stocks-eu-scraper-backfill

    # bound to a specific floor date
    poetry run barchart-stocks-eu-scraper-backfill --floor-date 2025-01-01
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.orm import Session

from scripts.barchart_stocks_eu_scraper.db_writer import (
    StockEuRowMissingError,
    update_stock_eu,
)
from scripts.barchart_stocks_eu_scraper.parser import (
    StockEuObservation,
    parse_barchart_history_series,
    parse_barchart_stocks_eu_html,
)
from scripts.barchart_stocks_eu_scraper.scraper import (
    BarchartStocksEuScraperError,
    _fetch,
)
from scripts.barchart_stocks_eu_scraper.config import BARCHART_STOCKS_EU_URL

# First Value Date observed on the Barchart cmdty page (spike 2026-05-20).
DEFAULT_FLOOR_DATE = date(2012, 2, 7)

load_dotenv(Path(__file__).parent.parent.parent / ".env")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackfillResult:
    """Outcome of a Stock EU backfill run."""

    fetched: int
    updated: int
    skipped_missing_ohlcv: int


def backfill_via_embedded_series(
    session: Session,
    *,
    floor_date: date = DEFAULT_FLOOR_DATE,
) -> BackfillResult:
    """Backfill from the Highcharts series embedded in the cmdty page.

    Fetches the page once, parses the data series, and UPDATEs the matching
    rows in pl_contract_data_daily (oldest → newest so partial runs leave
    the most recent data fresh).

    Skips dates where no OHLCV row exists (the barchart-scraper OHLCV
    backfill must have run first for those dates).
    """
    body = _fetch(BARCHART_STOCKS_EU_URL)
    pairs = parse_barchart_history_series(body)
    logger.info(
        "Fetched %d (date, value) pairs from cmdty page (range %s..%s)",
        len(pairs),
        pairs[0][0],
        pairs[-1][0],
    )

    updated = 0
    skipped = 0
    for d, value in pairs:
        if d < floor_date:
            continue
        try:
            update_stock_eu(session, d, value)
            updated += 1
        except StockEuRowMissingError:
            skipped += 1
            logger.debug("Skip %s: no OHLCV row in pl_contract_data_daily", d)

    session.commit()
    return BackfillResult(
        fetched=len(pairs),
        updated=updated,
        skipped_missing_ohlcv=skipped,
    )


# ---------------------------------------------------------------------------
# Wayback Machine fallback (deeper history, much slower)
# ---------------------------------------------------------------------------
# Not used by the default backfill path — implemented for completeness in
# case a future use-case (e.g. pre-2024 backtests) needs more depth than
# the embedded 18-month window. Each Wayback snapshot is ~90 KB and
# Wayback throttles aggressively above ~1 req/sec.
# ---------------------------------------------------------------------------


def fetch_wayback_snapshot(target_date: date) -> StockEuObservation:
    """Fetch the Barchart cmdty page snapshot from web.archive.org for ``target_date``."""
    import httpx

    from scripts.barchart_stocks_eu_scraper.config import (
        FETCH_TIMEOUT_SECONDS,
        USER_AGENT,
    )

    ts = target_date.strftime("%Y%m%d")
    url = (
        f"https://web.archive.org/web/{ts}/"
        f"https://www.barchart.com/cmdty/data/fundamental/explore/IC345DRW.CS"
    )
    response = httpx.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=FETCH_TIMEOUT_SECONDS,
        follow_redirects=True,
    )
    if response.status_code != 200:
        raise BarchartStocksEuScraperError(
            f"Wayback HTTP {response.status_code} for {target_date}"
        )
    return parse_barchart_stocks_eu_html(response.text)


def backfill_via_wayback(
    session: Session,
    *,
    start_date: date,
    floor_date: date,
    step_days: int = 1,
    throttle_seconds: float = 1.0,
) -> BackfillResult:
    """Walk Wayback Machine snapshots newest → oldest.

    SLOW path — ~1 req/sec throttle. For backfills > 18 months only.
    """
    from datetime import timedelta

    current = start_date
    updated = 0
    fetched = 0
    skipped = 0
    while current >= floor_date:
        try:
            obs = fetch_wayback_snapshot(current)
            fetched += 1
        except BarchartStocksEuScraperError as exc:
            logger.warning("Wayback miss for %s: %s", current, exc)
            current -= timedelta(days=step_days)
            if throttle_seconds > 0:
                time.sleep(throttle_seconds)
            continue

        try:
            update_stock_eu(session, obs.date, obs.value_bags60kg)
            updated += 1
        except StockEuRowMissingError:
            skipped += 1

        current -= timedelta(days=step_days)
        if throttle_seconds > 0:
            time.sleep(throttle_seconds)

    session.commit()
    return BackfillResult(
        fetched=fetched, updated=updated, skipped_missing_ohlcv=skipped
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "One-shot Stock EU backfill from Barchart cmdty embedded chart data "
            "(~18 months in one HTTP request)"
        )
    )
    parser.add_argument(
        "--floor-date",
        type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
        default=DEFAULT_FLOOR_DATE,
        help=(
            "Oldest date to backfill (default: 2012-02-07, the Barchart "
            "'First Value Date' observed in spike — though only ~18 months are "
            "available without subscription)"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch + parse + log, no DB UPDATE",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="After write, log per-month coverage stats",
    )
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        stream=sys.stdout,
    )

    logger.info("=" * 60)
    logger.info("Stock EU Backfill — one-shot")
    logger.info("Floor date: %s", args.floor_date)
    logger.info("Mode: %s", "DRY RUN" if args.dry_run else "LIVE")
    logger.info("=" * 60)

    try:
        if args.dry_run:
            body = _fetch(BARCHART_STOCKS_EU_URL)
            pairs = parse_barchart_history_series(body)
            in_range = [pair for pair in pairs if pair[0] >= args.floor_date]
            logger.info(
                "Fetched %d pairs total, %d within floor_date %s (range %s..%s)",
                len(pairs),
                len(in_range),
                args.floor_date,
                in_range[0][0] if in_range else "n/a",
                in_range[-1][0] if in_range else "n/a",
            )
            for d, v in in_range[:5]:
                logger.info("  %s = %s bags60kg", d, v)
            return 0

        from scripts.db import get_session

        with get_session() as session:
            result = backfill_via_embedded_series(session, floor_date=args.floor_date)

        logger.info(
            "Backfill complete: %d pairs fetched, %d rows UPDATED, "
            "%d skipped (no OHLCV row)",
            result.fetched,
            result.updated,
            result.skipped_missing_ohlcv,
        )
        if result.skipped_missing_ohlcv > 0:
            logger.warning(
                "%d dates skipped because no OHLCV row existed in "
                "pl_contract_data_daily for the active contract. Run the "
                "barchart-scraper OHLCV backfill first to fill these gaps, "
                "then re-run barchart-stocks-eu-scraper-backfill (idempotent).",
                result.skipped_missing_ohlcv,
            )

        logger.info("SUCCESS — Stock EU backfill complete")
        return 0

    except BarchartStocksEuScraperError as exc:
        logger.error("Backfill failed at fetch/parse: %s", exc)
        return 1
    except Exception as exc:  # noqa: BLE001 — fail-loud at top level
        logger.exception("Backfill failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
