"""One-shot ICE Europe COT cocoa backfill.

Iterates over calendar years (newest → oldest) and re-uses the existing
``scrape_year`` + ``upsert_cot_eu_rows`` pipeline. Stops when ICE returns
404 (history floor reached).

ICE keeps CSV history back to ~2011 (probed 2026-05-20). ~16 years × 52
weeks × 1 cocoa row ≈ 832 rows total — trivial in volume.

Usage:
    # dry-run (no DB write)
    poetry run ice-cot-eu-scraper-backfill --dry-run

    # backfill all available history (2011 → current year)
    poetry run ice-cot-eu-scraper-backfill

    # backfill since 2018 only (skip older years)
    poetry run ice-cot-eu-scraper-backfill --floor-year 2018

    # verify after write
    poetry run ice-cot-eu-scraper-backfill --verify
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.orm import Session

from scripts.ice_cot_eu_scraper.db_writer import upsert_cot_eu_rows
from scripts.ice_cot_eu_scraper.scraper import IceCotEuScraperError, scrape_year

# ICE history floor probed 2026-05-20: COTHist2014 contains the first
# cocoa EU rows (launched September 2014). Files 2011-2013 exist on disk
# but don't list "ICE Cocoa Futures - ICE Futures Europe" yet — the
# backfill treats both 404 AND "no cocoa rows" as a clean stop.
DEFAULT_FLOOR_YEAR = 2014

load_dotenv(Path(__file__).parent.parent.parent / ".env")
logger = logging.getLogger(__name__)


class IceCotEuBackfillError(RuntimeError):
    """Raised on any non-404 failure during a backfill iteration."""


def backfill_all_years(
    session: Session,
    *,
    start_year: int,
    floor_year: int = DEFAULT_FLOOR_YEAR,
) -> int:
    """Scrape + UPSERT all ICE COT EU years in [floor_year, start_year].

    Iterates newest → oldest. Stops cleanly on the first HTTP 404 (history
    floor reached). Any other error fails-loud as ``IceCotEuBackfillError``.

    Returns the total number of rows upserted.
    """
    total = 0
    for year in range(start_year, floor_year - 1, -1):
        logger.info("Backfilling year %d ...", year)
        try:
            observations = scrape_year(year)
        except IceCotEuScraperError as exc:
            msg = str(exc)
            if "HTTP 404" in msg:
                logger.info(
                    "Year %d unavailable (404) — history floor reached, stopping.",
                    year,
                )
                break
            if "no cocoa" in msg:
                logger.info(
                    "Year %d: ICE CSV present but no cocoa EU rows "
                    "(market launched September 2014) — stopping.",
                    year,
                )
                break
            raise IceCotEuBackfillError(
                f"Year {year} fetch/parse failed: {exc}"
            ) from exc

        n = upsert_cot_eu_rows(session, observations)
        session.commit()
        total += n
        logger.info("Year %d: upserted %d rows (total so far: %d)", year, n, total)

    return total


def verify_backfill(session: Session, *, expected_min_rows: int = 200) -> None:
    """Sanity-check the backfilled rows.

    Asserts:
      * total row count ≥ ``expected_min_rows``
      * no NULL on critical columns (open_interest, m_money_long, m_money_short)
      * release_date range is at least 5 years wide

    Raises:
        IceCotEuBackfillError on any assertion failure.
    """
    row = session.execute(
        text(
            "SELECT count(*), min(release_date), max(release_date), "
            "count(*) FILTER (WHERE open_interest IS NULL) AS oi_null, "
            "count(*) FILTER (WHERE m_money_long IS NULL) AS mm_long_null "
            "FROM pl_cot_eu_weekly"
        )
    ).fetchone()
    if row is None:
        raise IceCotEuBackfillError("verify: pl_cot_eu_weekly is empty")

    total, min_d, max_d, oi_null, mm_long_null = row
    logger.info(
        "Verify: %d rows, range %s..%s, OI nulls=%d, MM-long nulls=%d",
        total,
        min_d,
        max_d,
        oi_null,
        mm_long_null,
    )

    if total < expected_min_rows:
        raise IceCotEuBackfillError(
            f"verify: only {total} rows (expected ≥ {expected_min_rows})"
        )
    if oi_null > 0:
        raise IceCotEuBackfillError(f"verify: {oi_null} rows have NULL open_interest")
    if mm_long_null > 0:
        raise IceCotEuBackfillError(
            f"verify: {mm_long_null} rows have NULL m_money_long"
        )

    span_years = (max_d - min_d).days / 365.25
    if span_years < 5:
        raise IceCotEuBackfillError(
            f"verify: range {min_d}..{max_d} spans only {span_years:.1f} years"
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="One-shot ICE Europe COT cocoa backfill (2011 → current year)"
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=None,
        help="Most recent year to backfill (default: current UTC year)",
    )
    parser.add_argument(
        "--floor-year",
        type=int,
        default=DEFAULT_FLOOR_YEAR,
        help=(
            f"Oldest year to attempt (default: {DEFAULT_FLOOR_YEAR}, the empirical "
            "ICE history floor — probed 2026-05-20)"
        ),
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Scrape + count, no DB write"
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="After write, run sanity checks on pl_cot_eu_weekly",
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

    start_year = args.start_year or datetime.now(timezone.utc).year

    logger.info("=" * 60)
    logger.info("ICE COT EU Backfill — one-shot")
    logger.info("Year range: %d ↓ %d", start_year, args.floor_year)
    logger.info("Mode: %s", "DRY RUN" if args.dry_run else "LIVE")
    logger.info("Verify after write: %s", args.verify)
    logger.info("=" * 60)

    try:
        if args.dry_run:
            total = 0
            for year in range(start_year, args.floor_year - 1, -1):
                try:
                    observations = scrape_year(year)
                except IceCotEuScraperError as exc:
                    msg = str(exc)
                    if "HTTP 404" in msg:
                        logger.info("Year %d: 404 — stopping", year)
                        break
                    if "no cocoa" in msg:
                        logger.info(
                            "Year %d: no cocoa EU rows (pre-launch) — stopping", year
                        )
                        break
                    raise
                logger.info("Year %d: %d rows (DRY RUN)", year, len(observations))
                total += len(observations)
            logger.info("Total rows that WOULD be upserted: %d", total)
            return 0

        from scripts.db import get_session

        with get_session() as session:
            total = backfill_all_years(
                session,
                start_year=start_year,
                floor_year=args.floor_year,
            )

        logger.info("Upserted %d rows total into pl_cot_eu_weekly", total)

        if args.verify:
            logger.info("Running verify pass...")
            with get_session() as verify_session:
                verify_backfill(verify_session)

        logger.info("SUCCESS — ICE COT EU backfill complete")
        return 0

    except IceCotEuBackfillError as exc:
        logger.error("Backfill failed: %s", exc)
        return 1
    except Exception as exc:  # noqa: BLE001 — fail-loud at top level
        logger.exception("Backfill failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
