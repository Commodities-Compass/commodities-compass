"""One-shot FX backfill from R&D CSV snapshots.

Reads ``docs/onboarding/FX/{dxy_proxy_daily,gbpusd_daily}.csv`` and UPSERTs
into ``pl_external_indicator`` via the existing ``upsert_fx_rows`` writer.

These CSV snapshots already store the DERIVED values
(``fx_dxy_proxy = 1/usd_per_eur`` and ``fx_gbpusd = usd_per_eur/gbp_per_eur``)
so the backfill bypasses the formula step and writes those values directly.
``fx_eurusd`` is set as an alias of ``fx_dxy_proxy``. ``fx_gbpeur`` is left
NULL on backfill (audit-only column, not consumed by the engine).

Usage:
    # local-only smoke test
    poetry run fx-scraper-backfill --dry-run
    # actual backfill (writes to DB)
    poetry run fx-scraper-backfill
    # backfill + verify (raises on any mismatch)
    poetry run fx-scraper-backfill --verify
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.orm import Session

from scripts.fx_scraper.db_writer import upsert_fx_rows
from scripts.fx_scraper.scraper import FxRecord

# Load .env so DATABASE_SYNC_URL is available for the one-shot CLI runs.
load_dotenv(Path(__file__).parent.parent.parent / ".env")

logger = logging.getLogger(__name__)

# Default snapshot locations.
_REPO_ROOT = Path(__file__).parent.parent.parent.parent
_DEFAULT_DXY_CSV = _REPO_ROOT / "docs" / "onboarding" / "FX" / "dxy_proxy_daily.csv"
_DEFAULT_GBPUSD_CSV = _REPO_ROOT / "docs" / "onboarding" / "FX" / "gbpusd_daily.csv"

# Tolerance for the verify step (Decimal(15,6) → tighter than ENSO).
_VERIFY_TOLERANCE = 1e-5


class BackfillVerificationError(RuntimeError):
    """Raised when DB row values diverge from the CSV source beyond tolerance."""


def _read_close_csv(path: Path) -> dict[date, float]:
    """Read a (date, close) CSV and return a {date: value} mapping."""
    if not path.exists():
        raise FileNotFoundError(path)
    out: dict[date, float] = {}
    with path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                d = datetime.strptime(row["date"].strip(), "%Y-%m-%d").date()
                v = float(row["close"])
            except (KeyError, ValueError, AttributeError, TypeError):
                continue
            out[d] = v
    return out


def load_fx_csvs(
    dxy_csv: Path,
    gbpusd_csv: Path,
    *,
    start: date | None = None,
    end: date | None = None,
) -> list[FxRecord]:
    """Build FxRecord list from the 2 R&D CSV snapshots.

    Strategy: union of dates from both files. For each date:
      * dxy_proxy from dxy_csv if available → fx_dxy_proxy + fx_eurusd (alias)
      * gbpusd from gbpusd_csv if available → fx_gbpusd
      * fx_gbpeur is left None (audit column not in the R&D snapshot)

    Filters rows outside [start, end] if provided.
    """
    dxy_by_date = _read_close_csv(dxy_csv)
    gbp_by_date = _read_close_csv(gbpusd_csv)
    all_dates = sorted(set(dxy_by_date) | set(gbp_by_date))

    records: list[FxRecord] = []
    for d in all_dates:
        if start is not None and d < start:
            continue
        if end is not None and d > end:
            continue
        dxy = dxy_by_date.get(d)
        gbpusd = gbp_by_date.get(d)
        records.append(
            FxRecord(
                date=d,
                fx_dxy_proxy=dxy,
                fx_gbpusd=gbpusd,
                fx_eurusd=dxy,  # alias of dxy_proxy
                fx_gbpeur=None,  # not in CSV pair — left NULL on backfill
            )
        )
    return records


def verify_fx_against_csvs(
    session: Session,
    dxy_csv: Path,
    gbpusd_csv: Path,
) -> None:
    """Re-read DB rows and assert they match the CSV sources.

    Raises BackfillVerificationError on the first mismatch beyond tolerance.
    """
    dxy_by_date = _read_close_csv(dxy_csv)
    gbp_by_date = _read_close_csv(gbpusd_csv)

    _verify_one_series(session, dxy_by_date, column="fx_dxy_proxy")
    _verify_one_series(session, gbp_by_date, column="fx_gbpusd")
    logger.info(
        "Verify OK: %d DXY rows + %d GBPUSD rows match CSV source.",
        len(dxy_by_date),
        len(gbp_by_date),
    )


def _verify_one_series(
    session: Session,
    expected: dict[date, float],
    *,
    column: str,
) -> None:
    if not expected:
        return
    # `column` is one of two fixed names (fx_dxy_proxy, fx_gbpusd) — not user input.
    sql = text(f"SELECT {column} FROM pl_external_indicator WHERE date = :d")  # noqa: S608
    for d, expected_value in expected.items():
        row = session.execute(sql, {"d": d}).fetchone()
        if row is None:
            raise BackfillVerificationError(
                f"Verify failed: no row in DB for date={d} ({column})"
            )
        actual = row[0]
        if actual is None:
            raise BackfillVerificationError(
                f"Verify mismatch ({column}, date={d}): DB has NULL, CSV has {expected_value}"
            )
        diff = abs(float(actual) - expected_value)
        if diff > _VERIFY_TOLERANCE:
            raise BackfillVerificationError(
                f"Verify mismatch ({column}, date={d}): "
                f"DB={actual} CSV={expected_value} diff={diff}"
            )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="One-shot FX backfill from R&D CSV snapshots"
    )
    parser.add_argument(
        "--source-csv-dxy",
        type=Path,
        default=_DEFAULT_DXY_CSV,
        help=(
            "Path to dxy_proxy_daily.csv (default: "
            "docs/onboarding/FX/dxy_proxy_daily.csv)"
        ),
    )
    parser.add_argument(
        "--source-csv-gbpusd",
        type=Path,
        default=_DEFAULT_GBPUSD_CSV,
        help=(
            "Path to gbpusd_daily.csv (default: docs/onboarding/FX/gbpusd_daily.csv)"
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
    logger.info("FX Backfill — one-shot from CSV snapshots")
    logger.info("DXY CSV:    %s", args.source_csv_dxy)
    logger.info("GBPUSD CSV: %s", args.source_csv_gbpusd)
    logger.info("Mode: %s", "DRY RUN" if args.dry_run else "LIVE")
    logger.info("Verify after write: %s", args.verify)
    logger.info("=" * 60)

    try:
        records = load_fx_csvs(
            args.source_csv_dxy,
            args.source_csv_gbpusd,
            start=args.start,
            end=args.end,
        )
        logger.info("Loaded %d FX records", len(records))

        if args.dry_run:
            logger.info("[DRY RUN] Skipping DB write")
            tail = records[-5:] if len(records) >= 5 else records
            for rec in tail:
                logger.info(
                    "  %s  dxy=%s  gbpusd=%s",
                    rec.date,
                    f"{rec.fx_dxy_proxy:.6f}"
                    if rec.fx_dxy_proxy is not None
                    else "N/A",
                    f"{rec.fx_gbpusd:.6f}" if rec.fx_gbpusd is not None else "N/A",
                )
            return 0

        from scripts.db import get_session

        with get_session() as session:
            n = upsert_fx_rows(session, records)
            session.commit()
            logger.info("Upserted %d rows into pl_external_indicator", n)

            if args.verify:
                logger.info("Running verify pass...")
                verify_fx_against_csvs(
                    session, args.source_csv_dxy, args.source_csv_gbpusd
                )

        logger.info("SUCCESS — FX backfill complete")
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


if __name__ == "__main__":
    sys.exit(main())
