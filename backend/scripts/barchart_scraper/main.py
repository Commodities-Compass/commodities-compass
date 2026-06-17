"""CLI entry point for Barchart scraper."""

import logging
import sys

import sentry_sdk
from sentry_sdk.crons import monitor

from scripts._shared.cli import build_base_argparser
from scripts._shared.sentry import bootstrap_scraper
from scripts.barchart_scraper.config import LOG_FORMAT
from scripts.barchart_scraper.scraper import BarchartScraper, BarchartScraperError
from scripts.barchart_scraper.validator import DataValidator

logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# Load env + init Sentry BEFORE @monitor-decorated function
bootstrap_scraper("barchart-scraper", script_file=__file__)


@monitor(monitor_slug="barchart-scraper")
def main() -> int:
    parser = build_base_argparser("Barchart scraper for London cocoa futures")
    parser.add_argument(
        "--headful",
        action="store_true",
        help="Run browser in non-headless mode (visible, for debugging)",
    )

    args = parser.parse_args()

    # Skip on non-trading days unless --force
    from scripts.db import should_skip_non_trading_day

    if should_skip_non_trading_day(force=args.force):
        return 0

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    logger.info("=" * 60)
    logger.info("Barchart Scraper - London Cocoa #7 (CA*0)")
    logger.info(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    logger.info(f"Browser: {'HEADFUL (visible)' if args.headful else 'HEADLESS'}")
    logger.info("=" * 60)

    try:
        from sqlalchemy import select

        from app.models.reference import RefContract
        from scripts.barchart_scraper.config import BACK_MONTHS_TO_SCRAPE
        from scripts.barchart_scraper.db_writer import write_ohlcv
        from scripts.contract_resolver import ensure_contract, next_contract_code
        from scripts.db import get_display_date, get_session

        # Step 1: resolve the active front-month + derive the back-month(s) to
        # also capture. With both contracts present, v_contract_data_chained
        # (front-month-by-OI) auto-switches at the true crossover, so a roll
        # becomes a data-layer non-event — no manual backfill, no rewrite.
        logger.info("Step 1: Resolving contracts (front + back-months)...")
        with get_session() as session:
            active = session.execute(
                select(RefContract).where(RefContract.is_active.is_(True))
            ).scalar_one_or_none()
            if active is None:
                raise BarchartScraperError("No active contract in ref_contract")
            commodity_id = active.commodity_id
            codes = [active.code]
            code = active.code
            for _ in range(BACK_MONTHS_TO_SCRAPE):
                code = next_contract_code(code)
                ensure_contract(session, code, commodity_id=commodity_id)
                codes.append(code)
        logger.info(
            "Contracts to scrape (front + %d back): %s", BACK_MONTHS_TO_SCRAPE, codes
        )

        display_date = get_display_date()
        logger.info("Display date (next trading day): %s", display_date)

        # Step 2: scrape each contract in ONE browser session. The front-month
        # is the daily-critical output (fail-loud). Back-months are roll-smoothing
        # and best-effort: an illiquid back-month can fail validation (e.g. zero
        # volume) — skip it (it's not front-month yet; the next run retries).
        logger.info("Step 2: Scraping Barchart.com...")
        scraped: dict[str, dict] = {}
        degraded: list[str] = []
        with BarchartScraper(headless=not args.headful) as scraper:
            for i, scrape_code in enumerate(codes):
                is_front = i == 0
                try:
                    data = scraper.scrape_all(contract_code=scrape_code)
                    errors = DataValidator.validate_all(data)
                    if errors:
                        raise BarchartScraperError(f"validation failed: {errors}")
                    scraped[scrape_code] = data
                except BarchartScraperError:
                    if is_front:
                        raise  # front-month is critical — fail loud
                    logger.warning(
                        "Back-month %s skipped (illiquid / not yet front-month) "
                        "— no row this run",
                        scrape_code,
                    )
                    degraded.append(scrape_code)
                except Exception as exc:  # noqa: BLE001 — front re-raises, back logged
                    if is_front:
                        raise
                    logger.error("Back-month %s scrape error: %s", scrape_code, exc)
                    sentry_sdk.capture_message(
                        f"Barchart back-month {scrape_code} scrape error: {exc}",
                        level="error",
                    )
                    degraded.append(scrape_code)

        # Step 3: write every successfully-scraped contract.
        logger.info("Step 3: Writing to GCP PostgreSQL...")
        with get_session() as session:
            for write_code, data in scraped.items():
                write_ohlcv(
                    session,
                    data,
                    write_code,
                    dry_run=args.dry_run,
                    display_date=display_date,
                )

        front_code = codes[0]
        front = scraped.get(front_code, {})
        sentry_sdk.set_context(
            "scrape_result",
            {
                "display_date": str(display_date),
                "front_contract": front_code,
                "back_written": [c for c in codes[1:] if c in scraped],
                "degraded": degraded,
                "close": str(front.get("close")),
                "volume": str(front.get("volume")),
                "oi": str(front.get("open_interest")),
                "iv": str(front.get("implied_volatility")),
                "dry_run": args.dry_run,
            },
        )

        logger.info("=" * 60)
        logger.info(
            "SUCCESS: scraped %d/%d contracts (front=%s%s)",
            len(scraped),
            len(codes),
            front_code,
            f", degraded={degraded}" if degraded else "",
        )
        logger.info("=" * 60)
        return 0

    except BarchartScraperError as e:
        logger.error(f"Scraper error: {e}")
        sentry_sdk.capture_exception(e)
        return 1
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        sentry_sdk.capture_exception(e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
