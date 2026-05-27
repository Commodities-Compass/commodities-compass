"""Shared INSERT writer for ``pl_stock_observation``.

Both ICE US (region='us', native unit tonnes) and Barchart EU
(region='eu', native unit 60kg bags) share the same destination table
and the same UPSERT semantics on ``(region, report_date,
contract_market)``. Keeping the writer here avoids re-implementing the
bag→tonne conversion or the conflict policy in each scraper.

Per ``.claude/rules/pipeline-error-handling.md``: this writer is
fail-loud. A missing ``report_date`` or an unknown ``unit_native``
raises rather than silently substituting a default.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Literal

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

Region = Literal["us", "eu"]
UnitNative = Literal["tonnes", "bags_60kg"]

EU_BAG_KG = Decimal("60")
KG_PER_TONNE = Decimal("1000")


class StockObservationWriterError(RuntimeError):
    pass


def _to_tonnes(value_native: Decimal, unit_native: UnitNative) -> Decimal:
    if unit_native == "tonnes":
        return value_native
    if unit_native == "bags_60kg":
        return value_native * EU_BAG_KG / KG_PER_TONNE
    raise StockObservationWriterError(
        f"Unsupported unit_native={unit_native!r} — expected 'tonnes' or 'bags_60kg'"
    )


def upsert_stock_observation(
    session: Session,
    *,
    region: Region,
    report_date: date,
    value_native: Decimal,
    unit_native: UnitNative,
    source: str,
    contract_market: str = "cocoa",
    dry_run: bool = False,
) -> bool:
    """UPSERT one stock observation. Returns True if the row was actually
    written (INSERT or UPDATE), False if dry-run.

    Conflict policy: on ``(region, report_date, contract_market)`` collision
    we UPDATE the value + source + ingested_at. This handles legacy backfill
    rows getting replaced by precise re-scrapes carrying the same
    publication date.
    """
    value_tonnes = _to_tonnes(value_native, unit_native)

    if dry_run:
        logger.info(
            "[DRY RUN] Would upsert stock_observation region=%s report_date=%s "
            "value_native=%s unit_native=%s value_tonnes=%s source=%s",
            region,
            report_date,
            value_native,
            unit_native,
            value_tonnes,
            source,
        )
        return False

    session.execute(
        text(
            """
            INSERT INTO pl_stock_observation
                (region, report_date, value_native, unit_native, value_tonnes,
                 contract_market, source, ingested_at)
            VALUES
                (:region, :report_date, :value_native, :unit_native, :value_tonnes,
                 :contract_market, :source, now())
            ON CONFLICT (region, report_date, contract_market) DO UPDATE
            SET value_native = EXCLUDED.value_native,
                unit_native  = EXCLUDED.unit_native,
                value_tonnes = EXCLUDED.value_tonnes,
                source       = EXCLUDED.source,
                ingested_at  = now();
            """
        ),
        {
            "region": region,
            "report_date": report_date,
            "value_native": value_native,
            "unit_native": unit_native,
            "value_tonnes": value_tonnes,
            "contract_market": contract_market,
            "source": source,
        },
    )
    session.flush()
    logger.info(
        "Upserted stock_observation region=%s report_date=%s value_native=%s "
        "value_tonnes=%s source=%s",
        region,
        report_date,
        value_native,
        value_tonnes,
        source,
    )
    return True
