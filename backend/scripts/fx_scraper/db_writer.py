"""UPSERT writer for FX data → pl_external_indicator.

Uses a partial UPSERT (ON CONFLICT DO UPDATE) so writing FX never touches the
ENSO columns written by cc-enso-scraper. See P1-scraper-fx.md §4.

Note: this writer ALWAYS updates the 4 fx_* columns on conflict, even if some
are None in the FxRecord. That's correct semantics — the FX scraper is the
sole producer of these columns, so a None means "no value for this date" and
must overwrite any prior cached value.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from scripts.fx_scraper.scraper import FxRecord

logger = logging.getLogger(__name__)


def _to_decimal(value: float | None) -> Decimal | None:
    """Convert float → Decimal preserving precision; pass through None."""
    if value is None:
        return None
    return Decimal(str(value))


def upsert_fx_rows(session: Session, records: Iterable[FxRecord]) -> int:
    """UPSERT each FxRecord into pl_external_indicator.

    For each row:
      * If row for ``date`` does not exist → INSERT with the 4 fx_* columns
        populated (ENSO columns left NULL).
      * If row exists → UPDATE only the 4 fx_* columns; ENSO columns are
        preserved untouched.

    Returns the count of records processed.
    """
    records_list = list(records)
    if not records_list:
        return 0

    sql = text(
        """
        INSERT INTO pl_external_indicator
            (date, fx_dxy_proxy, fx_gbpusd, fx_eurusd, fx_gbpeur)
        VALUES
            (:date, :fx_dxy_proxy, :fx_gbpusd, :fx_eurusd, :fx_gbpeur)
        ON CONFLICT (date) DO UPDATE
        SET fx_dxy_proxy = EXCLUDED.fx_dxy_proxy,
            fx_gbpusd    = EXCLUDED.fx_gbpusd,
            fx_eurusd    = EXCLUDED.fx_eurusd,
            fx_gbpeur    = EXCLUDED.fx_gbpeur
        """
    )

    for rec in records_list:
        session.execute(
            sql,
            {
                "date": rec.date,
                "fx_dxy_proxy": _to_decimal(rec.fx_dxy_proxy),
                "fx_gbpusd": _to_decimal(rec.fx_gbpusd),
                "fx_eurusd": _to_decimal(rec.fx_eurusd),
                "fx_gbpeur": _to_decimal(rec.fx_gbpeur),
            },
        )

    session.flush()
    logger.info(
        "Upserted %d FX records (range %s..%s)",
        len(records_list),
        records_list[0].date,
        records_list[-1].date,
    )
    return len(records_list)
