"""Seed GCP DB from the scraped historical CSV.

Inserts:
  - 1 ref_exchange  (IFEU — ICE Futures Europe)
  - 1 ref_commodity (CC   — London Cocoa #7)
  - 44 ref_contract  rows (CAH16 → CAU24)
  - 2208 pl_contract_data_daily rows (raw OHLCV from CSV)

Idempotent: skips rows that already exist (unique constraints).

Usage:
    poetry run seed-historical-csv                         # target GCP proxy :5434
    poetry run seed-historical-csv --dry-run               # preview, no write
    poetry run seed-historical-csv --target-url "postgresql+psycopg2://..."
    poetry run seed-historical-csv --csv path/to/file.csv
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.pipeline import PlContractDataDaily
from app.models.reference import RefCommodity, RefContract, RefExchange

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_TARGET_URL = (
    "postgresql+psycopg2://postgres:password@localhost:5434/commodities_compass"
)
DEFAULT_CSV = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "london_cocoa_2016-01-01_2024-09-15.csv"
)

EXCHANGE_CODE = "IFEU"
EXCHANGE_NAME = "ICE Futures Europe"
EXCHANGE_TZ = "Europe/London"

COMMODITY_CODE = "CC"
COMMODITY_NAME = "London Cocoa #7"

# Delivery month letter → calendar month number
MONTH_MAP = {"H": 3, "K": 5, "N": 7, "U": 9, "Z": 12}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def contract_expiry(code: str) -> date:
    """Approximate expiry: 16th of the delivery month.

    e.g. CAH16 → 2016-03-16, CAZ23 → 2023-12-16
    Contract code format: CA<letter><2-digit-year>
    """
    letter = code[2]
    year = 2000 + int(code[3:])
    month = MONTH_MAP[letter]
    return date(year, month, 16)


def decimal_or_none(val: str) -> Decimal | None:
    val = val.strip()
    if not val:
        return None
    try:
        return Decimal(val)
    except Exception:
        return None


def int_or_none(val: str) -> int | None:
    val = val.strip()
    if not val:
        return None
    try:
        return int(float(val))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------


def seed_exchange(session: Session) -> uuid.UUID:
    existing = session.execute(
        select(RefExchange).where(RefExchange.code == EXCHANGE_CODE)
    ).scalar_one_or_none()
    if existing:
        log.info("Exchange already exists: %s", EXCHANGE_CODE)
        return existing.id
    exchange = RefExchange(code=EXCHANGE_CODE, name=EXCHANGE_NAME, timezone=EXCHANGE_TZ)
    session.add(exchange)
    session.flush()
    log.info("Created exchange: %s", EXCHANGE_CODE)
    return exchange.id


def seed_commodity(session: Session, exchange_id: uuid.UUID) -> uuid.UUID:
    existing = session.execute(
        select(RefCommodity).where(RefCommodity.code == COMMODITY_CODE)
    ).scalar_one_or_none()
    if existing:
        log.info("Commodity already exists: %s", COMMODITY_CODE)
        return existing.id
    commodity = RefCommodity(
        code=COMMODITY_CODE, name=COMMODITY_NAME, exchange_id=exchange_id
    )
    session.add(commodity)
    session.flush()
    log.info("Created commodity: %s", COMMODITY_CODE)
    return commodity.id


def seed_contracts(
    session: Session,
    commodity_id: uuid.UUID,
    contract_months: dict[str, str],  # code → contract_month string e.g. "2016-03"
) -> dict[str, uuid.UUID]:
    """Upsert-by-check all 44 contracts. Returns {code: id}."""
    contract_ids: dict[str, uuid.UUID] = {}
    created = 0

    for code in sorted(contract_months):
        existing = session.execute(
            select(RefContract).where(RefContract.code == code)
        ).scalar_one_or_none()
        if existing:
            contract_ids[code] = existing.id
            continue

        contract = RefContract(
            commodity_id=commodity_id,
            code=code,
            contract_month=contract_months[code],
            expiry_date=contract_expiry(code),
            is_active=False,  # all historical contracts are expired
        )
        session.add(contract)
        session.flush()
        contract_ids[code] = contract.id
        created += 1

    log.info(
        "Contracts: %d created, %d already existed",
        created,
        len(contract_months) - created,
    )
    return contract_ids


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------


def seed_ohlcv(
    session: Session,
    csv_path: Path,
    contract_ids: dict[str, uuid.UUID],
) -> int:
    """Bulk insert pl_contract_data_daily from CSV. Skips existing (date, contract_id) pairs."""
    # Pre-fetch existing (date, contract_id) pairs to avoid unique constraint errors
    existing_pairs: set[tuple[date, uuid.UUID]] = set()
    rows_db = session.execute(
        select(PlContractDataDaily.date, PlContractDataDaily.contract_id)
    ).all()
    for r in rows_db:
        existing_pairs.add((r.date, r.contract_id))

    log.info("Pre-existing pl_contract_data_daily rows: %d", len(existing_pairs))

    inserted = 0
    skipped = 0
    unknown_contracts: set[str] = set()

    with csv_path.open(newline="") as f:
        reader = csv.DictReader(f)
        batch: list[PlContractDataDaily] = []

        for row in reader:
            code = row["contract_code"].strip()
            contract_id = contract_ids.get(code)
            if contract_id is None:
                unknown_contracts.add(code)
                skipped += 1
                continue

            row_date = date.fromisoformat(row["date"].strip())

            if (row_date, contract_id) in existing_pairs:
                skipped += 1
                continue

            batch.append(
                PlContractDataDaily(
                    date=row_date,
                    contract_id=contract_id,
                    open=decimal_or_none(row["open"]),
                    high=decimal_or_none(row["high"]),
                    low=decimal_or_none(row["low"]),
                    close=decimal_or_none(row["close"]),
                    volume=int_or_none(row["volume"]),
                    oi=int_or_none(row["oi"]),
                    implied_volatility=None,
                    stock_us=None,
                    com_net_us=None,
                )
            )
            inserted += 1

            # Flush in batches to avoid memory pressure
            if len(batch) >= 500:
                session.add_all(batch)
                session.flush()
                batch = []

        if batch:
            session.add_all(batch)
            session.flush()

    if unknown_contracts:
        log.warning("Unknown contract codes (skipped): %s", sorted(unknown_contracts))

    log.info("OHLCV rows inserted=%d skipped=%d", inserted, skipped)
    return inserted


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run(
    target_url: str = DEFAULT_TARGET_URL,
    csv_path: Path = DEFAULT_CSV,
    dry_run: bool = False,
) -> None:
    if not csv_path.exists():
        log.error("CSV not found: %s", csv_path)
        sys.exit(1)

    # Collect contract metadata from CSV
    contract_months: dict[str, str] = {}
    with csv_path.open(newline="") as f:
        for row in csv.DictReader(f):
            code = row["contract_code"].strip()
            month = row["contract_month"].strip()
            contract_months[code] = month

    log.info("CSV contracts found: %d", len(contract_months))

    engine = create_engine(target_url)

    with Session(engine) as session:
        log.info("=== Seeding reference data ===")
        exchange_id = seed_exchange(session)
        commodity_id = seed_commodity(session, exchange_id)
        contract_ids = seed_contracts(session, commodity_id, contract_months)

        log.info("=== Seeding OHLCV rows ===")
        count = seed_ohlcv(session, csv_path, contract_ids)

        if dry_run:
            log.info("DRY RUN — rolling back")
            session.rollback()
        else:
            session.commit()
            log.info(
                "Done — %d contract rows committed to %s",
                count,
                target_url.split("@")[-1],
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed GCP DB from historical London Cocoa CSV"
    )
    parser.add_argument(
        "--target-url",
        default=DEFAULT_TARGET_URL,
        help="Target DB URL (default: GCP proxy :5434)",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=DEFAULT_CSV,
        help="Path to CSV file",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview without writing",
    )
    args = parser.parse_args()
    run(target_url=args.target_url, csv_path=args.csv, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
