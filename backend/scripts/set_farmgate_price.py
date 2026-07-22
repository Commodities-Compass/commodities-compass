"""CLI to record an official / guaranteed farmgate price (CCC / COCOBOD).

Append-only: each invocation inserts ONE new row into
``pl_official_farmgate_price`` (a revision never overwrites history). A handful
of rows per year (seasonal announcements + occasional mid-season revisions).

Usage:
    poetry run set-farmgate-price \\
        --region civ --price 1800 --unit per_kg \\
        --season 2025/26 --effective-date 2025-10-01 \\
        --source-url https://www.conseilcafecacao.ci/...

    poetry run set-farmgate-price \\
        --region ghana --price 3100 --unit per_bag_64kg \\
        --season 2025/26 --effective-date 2025-09-01 --dry-run

Currency and source default from the region (CIV → XOF/ccc, Ghana → GHS/cocobod)
and can be overridden. The DB CHECK constraints are the final guard.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from dotenv import load_dotenv

from app.models.pipeline import PlOfficialFarmgatePrice
from scripts.db import get_session

load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

_REGION_DEFAULTS = {
    "civ": {"currency": "XOF", "source": "ccc"},
    "ghana": {"currency": "GHS", "source": "cocobod"},
}


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Record an official/guaranteed farmgate price (append-only row)."
    )
    parser.add_argument("--region", required=True, choices=["civ", "ghana"])
    parser.add_argument(
        "--price", required=True, help="Guaranteed price (native currency)"
    )
    parser.add_argument(
        "--unit",
        required=True,
        choices=["per_kg", "per_bag_64kg", "per_tonne"],
    )
    parser.add_argument("--season", required=True, help="Campaign label, e.g. 2025/26")
    parser.add_argument("--effective-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--announced-date", default=None, help="YYYY-MM-DD (optional)")
    parser.add_argument(
        "--currency", default=None, help="Override (default: CIV→XOF, Ghana→GHS)"
    )
    parser.add_argument(
        "--source", default=None, choices=["ccc", "cocobod"], help="Override"
    )
    parser.add_argument("--source-url", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    defaults = _REGION_DEFAULTS[args.region]
    currency = args.currency or defaults["currency"]
    source = args.source or defaults["source"]

    try:
        price = Decimal(str(args.price))
    except (InvalidOperation, ValueError):
        logger.error("Invalid --price value: %r", args.price)
        return 1
    if price <= 0:
        logger.error("--price must be positive, got %s", price)
        return 1

    try:
        effective_date = _parse_date(args.effective_date)
        announced_date = (
            _parse_date(args.announced_date) if args.announced_date else None
        )
    except ValueError:
        logger.error("Invalid date format. Use YYYY-MM-DD.")
        return 1

    logger.info(
        "Farmgate price → region=%s season=%s price=%s %s (%s) effective=%s source=%s",
        args.region,
        args.season,
        price,
        currency,
        args.unit,
        effective_date,
        source,
    )

    if args.dry_run:
        logger.info("[DRY RUN] No row written.")
        return 0

    try:
        with get_session() as session:
            session.add(
                PlOfficialFarmgatePrice(
                    region=args.region,
                    season_label=args.season,
                    effective_date=effective_date,
                    announced_date=announced_date,
                    price_native=price,
                    currency=currency,
                    unit=args.unit,
                    source=source,
                    source_url=args.source_url,
                )
            )
            session.flush()
        logger.info(
            "Inserted farmgate price row for %s (%s).", args.region, args.season
        )
    except Exception as e:  # noqa: BLE001 — fail loud, non-zero exit
        logger.exception("Failed to insert farmgate price: %s", e)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
