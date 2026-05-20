"""UPSERT writer for ENSO data → pl_external_indicator.

Uses a partial UPSERT (ON CONFLICT DO UPDATE) so writing ENSO never touches
FX columns written by cc-fx-scraper. See P1-scraper-enso.md §4.3.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from scripts.enso_scraper.config import VALUE_NAME_NINO34, VALUE_NAME_ONI
from scripts.enso_scraper.parser import EnsoRecord

logger = logging.getLogger(__name__)

# value_name → DB column on pl_external_indicator.
_VALUE_NAME_TO_COLUMN: dict[str, str] = {
    VALUE_NAME_ONI: "enso_oni_month",
    VALUE_NAME_NINO34: "enso_nino34_anomaly",
}


def upsert_enso_rows(session: Session, records: Iterable[EnsoRecord]) -> int:
    """UPSERT each EnsoRecord into pl_external_indicator.

    For each ``(date, value_name, value)`` :
      * If the row for ``date`` does not exist → INSERT with the matching ENSO
        column set, FX columns left NULL.
      * If the row exists → UPDATE only the matching ENSO column; ALL other
        columns (FX especially) are left untouched.

    Returns the count of records processed (matches the input length, modulo
    unknown ``value_name`` which raises before any DB write).

    Raises:
        ValueError: if any record has a ``value_name`` not in
            ``{"oni", "nino34_anomaly"}`` (fail-loud per
            ``.claude/rules/pipeline-error-handling.md``).
    """
    records_list = list(records)
    if not records_list:
        return 0

    # Validate all records BEFORE writing any (fail-loud, no partial writes).
    for rec in records_list:
        if rec.value_name not in _VALUE_NAME_TO_COLUMN:
            msg = (
                f"Unknown value_name: {rec.value_name!r}. "
                f"Expected one of {sorted(_VALUE_NAME_TO_COLUMN)}."
            )
            raise ValueError(msg)

    for rec in records_list:
        column = _VALUE_NAME_TO_COLUMN[rec.value_name]
        # Partial UPSERT — only the matching column is set, others stay NULL on
        # INSERT and untouched on conflict. This is the key invariant for
        # multi-scraper coexistence (ENSO + FX writing to the same table).
        sql = text(
            f"""
            INSERT INTO pl_external_indicator (date, {column})
            VALUES (:date, :value)
            ON CONFLICT (date) DO UPDATE
            SET {column} = EXCLUDED.{column}
            """  # noqa: S608 -- column name comes from a fixed mapping, not user input
        )
        session.execute(sql, {"date": rec.date, "value": Decimal(str(rec.value))})

    session.flush()
    logger.info(
        "Upserted %d ENSO records (range %s..%s)",
        len(records_list),
        records_list[0].date,
        records_list[-1].date,
    )
    return len(records_list)
