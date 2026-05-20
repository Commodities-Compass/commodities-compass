"""One-shot ENSO backfill from R&D CSV snapshots.

Reads ``docs/onboarding/ENSO/{oni_monthly,nino34_monthly}.csv`` and UPSERTs
into ``pl_external_indicator`` via the existing ``upsert_enso_rows`` writer.

Idempotent (UPSERT). Optional ``--verify`` re-reads the DB row-by-row and
asserts the stored value matches the CSV source within ``_VERIFY_TOLERANCE``
(loose enough for the Decimal(8,4) DB column round-trip).

Usage:
    # local-only smoke test
    poetry run enso-scraper-backfill --dry-run
    # actual backfill (writes to DB)
    poetry run enso-scraper-backfill
    # backfill + verify (raises on any mismatch)
    poetry run enso-scraper-backfill --verify
"""

from __future__ import annotations

import argparse
import csv
import logging
import math
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.orm import Session

from scripts.enso_scraper.config import VALUE_NAME_NINO34, VALUE_NAME_ONI
from scripts.enso_scraper.db_writer import upsert_enso_rows
from scripts.enso_scraper.parser import EnsoRecord

# Load .env so DATABASE_SYNC_URL is available for the one-shot CLI runs.
load_dotenv(Path(__file__).parent.parent.parent / ".env")

logger = logging.getLogger(__name__)

# Default snapshot locations (from R&D, checked into docs/onboarding/).
_REPO_ROOT = Path(__file__).parent.parent.parent.parent
_DEFAULT_ONI_CSV = _REPO_ROOT / "docs" / "onboarding" / "ENSO" / "oni_monthly.csv"
_DEFAULT_NIN34_CSV = _REPO_ROOT / "docs" / "onboarding" / "ENSO" / "nino34_monthly.csv"

# Tolerance for the verify step. Decimal(8,4) → 4 decimal places stored, so
# 1e-3 leaves a safe margin for float→Decimal rounding.
_VERIFY_TOLERANCE = 1e-3

# PSL missing-value sentinel (the R&D ASCII parser filters these but the CSV
# snapshot kept them for 1948-1949 Niño 3.4 history — drop here too).
_MISSING_VALUE_ABS = 99.0


class BackfillVerificationError(RuntimeError):
    """Raised when DB row values diverge from the CSV source beyond tolerance."""


def _is_sentinel(value: float) -> bool:
    return abs(value) >= _MISSING_VALUE_ABS or math.isnan(value)


def load_enso_csv(
    path: Path,
    *,
    value_name: str,
    start: date | None = None,
    end: date | None = None,
) -> list[EnsoRecord]:
    """Load ENSO records from a (date, value) CSV.

    Filters:
      * rows with bad date or non-numeric value → skipped silently
      * PSL missing sentinel (|x| >= 99) → skipped silently
      * rows outside [start, end] (if provided) → skipped

    Raises:
        FileNotFoundError: if path doesn't exist.
        ValueError: if value_name is not one of {oni, nino34_anomaly}.
    """
    if value_name not in (VALUE_NAME_ONI, VALUE_NAME_NINO34):
        msg = f"Unknown value_name: {value_name!r}"
        raise ValueError(msg)
    if not path.exists():
        raise FileNotFoundError(path)

    records: list[EnsoRecord] = []
    with path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                d = datetime.strptime(row["date"].strip(), "%Y-%m-%d").date()
            except (KeyError, ValueError, AttributeError):
                continue
            try:
                # The column name in the CSV matches value_name.
                v = float(row[value_name])
            except (KeyError, ValueError, TypeError):
                continue
            if _is_sentinel(v):
                continue
            if start is not None and d < start:
                continue
            if end is not None and d > end:
                continue
            records.append(EnsoRecord(date=d, value=v, value_name=value_name))

    records.sort(key=lambda r: r.date)
    return records


def verify_enso_against_csv(
    session: Session,
    oni_csv: Path,
    nin34_csv: Path,
) -> None:
    """Re-read DB rows and assert they match the CSV sources.

    Raises BackfillVerificationError on the first mismatch beyond tolerance.
    """
    oni = load_enso_csv(oni_csv, value_name=VALUE_NAME_ONI)
    nin = load_enso_csv(nin34_csv, value_name=VALUE_NAME_NINO34)
    _verify_one_series(session, oni, column="enso_oni_month")
    _verify_one_series(session, nin, column="enso_nino34_anomaly")
    logger.info(
        "Verify OK: %d ONI rows + %d Niño 3.4 rows match CSV source.",
        len(oni),
        len(nin),
    )


def _verify_one_series(
    session: Session,
    expected: list[EnsoRecord],
    *,
    column: str,
) -> None:
    if not expected:
        return
    # _VALUE_NAME_TO_COLUMN guarantees `column` is one of two fixed names,
    # not user input — safe to interpolate.
    sql = text(f"SELECT {column} FROM pl_external_indicator WHERE date = :d")  # noqa: S608
    for rec in expected:
        row = session.execute(sql, {"d": rec.date}).fetchone()
        if row is None:
            raise BackfillVerificationError(
                f"Verify failed: no row in DB for date={rec.date} ({column})"
            )
        actual = row[0]
        if actual is None:
            raise BackfillVerificationError(
                f"Verify mismatch ({column}, date={rec.date}): DB has NULL, CSV has {rec.value}"
            )
        diff = abs(float(actual) - rec.value)
        if diff > _VERIFY_TOLERANCE:
            raise BackfillVerificationError(
                f"Verify mismatch ({column}, date={rec.date}): "
                f"DB={actual} CSV={rec.value} diff={diff}"
            )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="One-shot ENSO backfill from R&D CSV snapshots"
    )
    parser.add_argument(
        "--source-csv-oni",
        type=Path,
        default=_DEFAULT_ONI_CSV,
        help="Path to oni_monthly.csv (default: docs/onboarding/ENSO/oni_monthly.csv)",
    )
    parser.add_argument(
        "--source-csv-nin34",
        type=Path,
        default=_DEFAULT_NIN34_CSV,
        help=(
            "Path to nino34_monthly.csv (default: "
            "docs/onboarding/ENSO/nino34_monthly.csv)"
        ),
    )
    parser.add_argument(
        "--start", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(), default=None
    )
    parser.add_argument(
        "--end", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(), default=None
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Parse + log, no DB write"
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="After write, re-read DB and assert value match against CSV",
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
    logger.info("ENSO Backfill — one-shot from CSV snapshots")
    logger.info("ONI CSV:    %s", args.source_csv_oni)
    logger.info("Niño34 CSV: %s", args.source_csv_nin34)
    logger.info("Mode: %s", "DRY RUN" if args.dry_run else "LIVE")
    logger.info("Verify after write: %s", args.verify)
    logger.info("=" * 60)

    try:
        oni = load_enso_csv(
            args.source_csv_oni,
            value_name=VALUE_NAME_ONI,
            start=args.start,
            end=args.end,
        )
        nin = load_enso_csv(
            args.source_csv_nin34,
            value_name=VALUE_NAME_NINO34,
            start=args.start,
            end=args.end,
        )
        records = oni + nin
        logger.info(
            "Loaded %d records (ONI=%d, Niño34=%d)", len(records), len(oni), len(nin)
        )

        if args.dry_run:
            logger.info("[DRY RUN] Skipping DB write")
            tail = records[-5:] if len(records) >= 5 else records
            for rec in tail:
                logger.info("  %s %s=%s", rec.date, rec.value_name, rec.value)
            return 0

        from scripts.db import get_session

        with get_session() as session:
            n = upsert_enso_rows(session, records)
            session.commit()
            logger.info("Upserted %d rows into pl_external_indicator", n)

            if args.verify:
                logger.info("Running verify pass...")
                verify_enso_against_csv(
                    session, args.source_csv_oni, args.source_csv_nin34
                )

        logger.info("SUCCESS — ENSO backfill complete")
        return 0

    except BackfillVerificationError as exc:
        logger.error("Verify failed: %s", exc)
        return 1
    except FileNotFoundError as exc:
        logger.error("Missing CSV: %s", exc)
        return 1
    except Exception as exc:  # noqa: BLE001 — fail-loud at top level
        logger.exception("Backfill failed: %s", exc)
        return 1


# Tame an unused-import warning while keeping Decimal in scope for the type
# checker (used implicitly via the db_writer / SQL round-trip).
_ = Decimal


if __name__ == "__main__":
    sys.exit(main())
