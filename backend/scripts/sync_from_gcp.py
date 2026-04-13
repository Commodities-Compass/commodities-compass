"""Sync local database from GCP Cloud SQL (production → local).

Copies all pl_*, ref_*, and aud_* tables from GCP to local, replacing local data.
Does NOT touch legacy tables (technicals, indicator, market_research, weather_data).

Usage:
    # Dry run — show what would change
    poetry run python scripts/sync_from_gcp.py --dry-run

    # Full sync
    poetry run python scripts/sync_from_gcp.py

    # Sync specific tables only
    poetry run python scripts/sync_from_gcp.py --tables pl_indicator_daily pl_signal_component

Requires:
    GCP_DATABASE_URL env var (or prompts for it)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text

load_dotenv(Path(__file__).parent.parent / ".env")

from app.core.config import settings  # noqa: E402

logger = logging.getLogger(__name__)

# Tables to sync, ordered by FK dependencies (parents first)
SYNC_TABLES = [
    # Reference tables (no FKs to other sync tables)
    "ref_exchange",
    "ref_commodity",
    "ref_contract",
    "ref_trading_calendar",
    # Algorithm config (ref_contract FK)
    "pl_algorithm_version",
    "pl_algorithm_config",
    # Pipeline data
    "pl_contract_data_daily",
    "pl_derived_indicators",
    "pl_indicator_daily",
    "pl_signal_component",
    "pl_fundamental_article",
    "pl_article_segment",
    "pl_weather_observation",
    # Audit tables
    "aud_pipeline_run",
    "aud_data_quality_check",
    "aud_llm_call",
]


def get_gcp_url() -> str:
    url = os.environ.get("GCP_DATABASE_URL")
    if not url:
        logger.error(
            "GCP_DATABASE_URL env var not set. "
            "Set it to the GCP Cloud SQL sync connection string."
        )
        sys.exit(1)
    return url


def sync_table(
    gcp_engine,
    local_engine,
    table: str,
    dry_run: bool,
) -> tuple[int, int]:
    """Sync a single table from GCP to local. Returns (deleted, inserted)."""
    with gcp_engine.connect() as gc:
        gcp_count = gc.execute(text(f"SELECT COUNT(*) FROM {table}")).fetchone()[0]
        if gcp_count == 0:
            logger.info("  %s: 0 rows on GCP, skipping", table)
            return 0, 0

        # Fetch all columns dynamically
        inspector = inspect(gcp_engine)
        columns = [c["name"] for c in inspector.get_columns(table)]
        col_list = ", ".join(columns)

        rows = gc.execute(text(f"SELECT {col_list} FROM {table}")).fetchall()

    with local_engine.connect() as lc:
        local_count = lc.execute(text(f"SELECT COUNT(*) FROM {table}")).fetchone()[0]

    if dry_run:
        logger.info(
            "  %s: would delete %d local rows, insert %d from GCP",
            table,
            local_count,
            len(rows),
        )
        return local_count, len(rows)

    with local_engine.begin() as lc:
        # Delete in dependency-safe order (children deleted before parents
        # because we process the full list, but within a single table this is fine)
        lc.execute(text(f"DELETE FROM {table}"))

        if rows:
            # Build parameterized INSERT
            placeholders = ", ".join(f":{c}" for c in columns)
            insert_sql = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})"
            row_dicts = [dict(zip(columns, row)) for row in rows]
            lc.execute(text(insert_sql), row_dicts)

    logger.info(
        "  %s: deleted %d, inserted %d",
        table,
        local_count,
        len(rows),
    )
    return local_count, len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync local database from GCP Cloud SQL"
    )
    parser.add_argument("--dry-run", action="store_true", help="Show changes only")
    parser.add_argument(
        "--tables",
        nargs="+",
        default=None,
        help="Sync specific tables only (default: all)",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    gcp_url = get_gcp_url()
    local_url = str(settings.DATABASE_SYNC_URL)

    gcp_engine = create_engine(gcp_url)
    local_engine = create_engine(local_url)

    tables = args.tables or SYNC_TABLES
    # Validate table names
    for t in tables:
        if t not in SYNC_TABLES:
            logger.error("Unknown table: %s (valid: %s)", t, ", ".join(SYNC_TABLES))
            return 1

    mode = "DRY RUN" if args.dry_run else "SYNC"
    logger.info("=" * 60)
    logger.info("GCP → Local Database Sync (%s)", mode)
    logger.info("Tables: %d", len(tables))
    logger.info("=" * 60)

    # Delete in reverse order (children first) to respect FKs
    if not args.dry_run:
        logger.info("Clearing local tables (FK-safe order)...")
        with local_engine.begin() as lc:
            for table in reversed(tables):
                lc.execute(text(f"DELETE FROM {table}"))
                logger.info("  Cleared %s", table)

    # Insert in forward order (parents first)
    total_inserted = 0
    logger.info("Copying from GCP...")
    for table in tables:
        if not args.dry_run:
            # Re-insert (table already cleared above)
            with gcp_engine.connect() as gc:
                inspector = inspect(gcp_engine)
                columns = [c["name"] for c in inspector.get_columns(table)]
                col_list = ", ".join(columns)
                rows = gc.execute(text(f"SELECT {col_list} FROM {table}")).fetchall()

            if rows:
                with local_engine.begin() as lc:
                    placeholders = ", ".join(f":{c}" for c in columns)
                    insert_sql = (
                        f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})"
                    )
                    row_dicts = [dict(zip(columns, row)) for row in rows]
                    lc.execute(text(insert_sql), row_dicts)

            logger.info("  %s: %d rows", table, len(rows))
            total_inserted += len(rows)
        else:
            with gcp_engine.connect() as gc:
                count = gc.execute(text(f"SELECT COUNT(*) FROM {table}")).fetchone()[0]
            with local_engine.connect() as lc:
                local_count = lc.execute(
                    text(f"SELECT COUNT(*) FROM {table}")
                ).fetchone()[0]
            diff = count - local_count
            flag = f" ({diff:+d})" if diff != 0 else ""
            logger.info("  %s: gcp=%d local=%d%s", table, count, local_count, flag)
            total_inserted += count

    logger.info("=" * 60)
    if args.dry_run:
        logger.info("DRY RUN complete — no changes made")
    else:
        logger.info("SYNC complete — %d total rows copied", total_inserted)
    logger.info("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
