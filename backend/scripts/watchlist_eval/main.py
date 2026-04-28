"""CLI entry point for watchlist evaluation.

Usage:
    poetry run watchlist-eval [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD]
                              [--csv output.csv] [--verbose] [--dry-run]
"""

import argparse
import logging
import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import text

from scripts.db import get_session

from .evaluator import build_date_sequence, evaluate_item, load_market_data
from .extractor import extract_watchlist_section, parse_item
from .report import export_csv, print_by_indicator, print_global_stats, print_timeline
from .types import EvalResult, WatchlistItem

_logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate 'À surveiller' watchlist recommendations against market data."
    )
    parser.add_argument(
        "--start-date",
        type=date.fromisoformat,
        default=None,
        help="Start date (YYYY-MM-DD). Default: all available data.",
    )
    parser.add_argument(
        "--end-date",
        type=date.fromisoformat,
        default=None,
        help="End date (YYYY-MM-DD). Default: all available data.",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="Export detailed results to CSV file.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed timeline of each item.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Extract and show parsed items without evaluating against market data.",
    )
    return parser.parse_args()


def _load_conclusions(
    session,
    start_date: date | None,
    end_date: date | None,
) -> list[tuple[date, str, str]]:
    """Load conclusion rows from pl_indicator_daily.

    Returns list of (date, contract_id_hex, conclusion_text).
    """
    where_clauses = ["conclusion IS NOT NULL", "length(conclusion) > 0"]
    params: dict = {}

    if start_date:
        where_clauses.append("i.date >= :start_date")
        params["start_date"] = start_date
    if end_date:
        where_clauses.append("i.date <= :end_date")
        params["end_date"] = end_date

    where_sql = " AND ".join(where_clauses)

    rows = session.execute(
        text(
            f"SELECT i.date, i.contract_id, i.conclusion "
            f"FROM pl_indicator_daily i "
            f"WHERE {where_sql} "
            f"ORDER BY i.date"
        ),
        params,
    ).fetchall()

    return [(r.date, r.contract_id, r.conclusion) for r in rows]


def main() -> int:
    load_dotenv()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    args = _parse_args()

    # If DATABASE_SYNC_URL not set, derive from DATABASE_URL (local dev)
    if not os.getenv("DATABASE_SYNC_URL"):
        db_url = os.getenv("DATABASE_URL", "")
        if db_url:
            sync_url = db_url.replace("+asyncpg", "+psycopg2")
            os.environ["DATABASE_SYNC_URL"] = sync_url

    with get_session() as session:
        # Step 1: Load conclusions
        _logger.info("Loading conclusions from pl_indicator_daily...")
        conclusions = _load_conclusions(session, args.start_date, args.end_date)
        _logger.info("Found %d conclusion rows", len(conclusions))

        # Step 2: Extract watchlist items
        all_items: list[WatchlistItem] = []
        unparsed_count = 0

        for row_date, contract_id, conclusion in conclusions:
            raw_lines = extract_watchlist_section(conclusion)
            for raw_text in raw_lines:
                item = parse_item(raw_text, row_date, contract_id)
                if item is not None:
                    all_items.append(item)
                else:
                    unparsed_count += 1
                    _logger.debug("Could not parse: %s", raw_text[:60])

        _logger.info(
            "Extracted %d items (%d unparseable lines skipped)",
            len(all_items),
            unparsed_count,
        )

        # Dry run: just show parsed items
        if args.dry_run:
            print(f"\n{'=' * 70}")
            print("  DRY RUN — Parsed Watchlist Items")
            print(f"{'=' * 70}")
            print(f"\n  Total: {len(all_items)} items from {len(conclusions)} days")
            print(f"  Unparsed: {unparsed_count} lines")
            print()

            current_date = None
            for item in sorted(all_items, key=lambda i: i.date):
                if item.date != current_date:
                    current_date = item.date
                    print(f"\n  --- {current_date} ---")
                threshold_str = f"{item.threshold:.2f}" if item.threshold else "?"
                print(
                    f"    [{item.parse_confidence:6s}] "
                    f"{item.indicator:<12s} {item.comparator:<12s} {threshold_str:>10s}  "
                    f"{item.implied_direction:10s}"
                )
                print(f'            raw: "{item.raw_text[:70]}"')
            return 0

        # Step 3: Load market data
        _logger.info("Loading market data...")
        market_data = load_market_data(session)
        date_sequences = build_date_sequence(market_data)

        # Step 4: Evaluate each item
        _logger.info("Evaluating %d items...", len(all_items))
        results: list[EvalResult] = []
        for item in all_items:
            result = evaluate_item(item, market_data, date_sequences)
            if result is not None:
                results.append(result)

        _logger.info(
            "Evaluated %d items (skipped %d with missing data)",
            len(results),
            len(all_items) - len(results),
        )

        # Step 5: Report
        print_global_stats(all_items, results)
        print_by_indicator(results)

        if args.verbose:
            print_timeline(results, verbose=True)

        if args.csv:
            export_csv(results, args.csv)

    return 0
