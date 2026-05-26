"""UPSERT writer for ECA records → pl_supply_demand_observation.

Two responsibilities:
  1. Insert (or update) one row per ``EcaRecord`` keyed on
     ``(publication_date, category, source, region, period_label,
     metric_name)``.
  2. Mark the corresponding ``ref_publication_calendar`` row as ingested by
     setting ``actual_publication_date`` to the PDF's publication date.

Both operations run in the same session so the caller can commit atomically
(or roll back the whole batch on error).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session

from scripts.eca_grindings_scraper.config import (
    CATEGORY,
    PARSER_VERSION,
    REGION,
    SOURCE,
)
from scripts.eca_grindings_scraper.parser import EcaRecord

logger = logging.getLogger(__name__)


def upsert_eca_records(
    session: Session,
    records: Iterable[EcaRecord],
    *,
    pdf_url: str | None = None,
) -> int:
    """UPSERT each EcaRecord into ``pl_supply_demand_observation``.

    Args:
        session: SQLAlchemy sync session (caller commits).
        records: parsed records for one PDF (volume_tonnes + yoy_pct).
        pdf_url: optional URL to embed in metadata_json for traceability.

    Returns:
        Count of records written (matches input length).

    Raises:
        ValueError: if ``records`` references multiple period_labels — the
            scraper writes one PDF per call to keep the calendar update
            atomic.
    """
    records_list = list(records)
    if not records_list:
        return 0

    periods = {r.period_label for r in records_list}
    if len(periods) != 1:
        raise ValueError(
            f"upsert_eca_records expects records from one PDF, got periods={periods}"
        )

    metadata_payload = {"parser_version": PARSER_VERSION}
    if pdf_url:
        metadata_payload["url"] = pdf_url

    sql = text(
        """
        INSERT INTO pl_supply_demand_observation (
            publication_date, period_date, period_label,
            category, source, region, metric_name, value, metadata_json
        )
        VALUES (
            :publication_date, :period_date, :period_label,
            :category, :source, :region, :metric_name, :value,
            CAST(:metadata_json AS JSONB)
        )
        ON CONFLICT (
            publication_date, category, source, region, period_label, metric_name
        ) DO UPDATE
        SET value = EXCLUDED.value,
            metadata_json = EXCLUDED.metadata_json
        """
    )

    for rec in records_list:
        session.execute(
            sql,
            {
                "publication_date": rec.publication_date,
                "period_date": rec.period_date,
                "period_label": rec.period_label,
                "category": CATEGORY,
                "source": SOURCE,
                "region": REGION,
                "metric_name": rec.metric_name,
                "value": rec.value,
                "metadata_json": json.dumps(metadata_payload),
            },
        )

    # Mark the calendar row as ingested (idempotent — re-runs harmless).
    period_label = records_list[0].period_label
    publication_date = records_list[0].publication_date
    session.execute(
        text(
            """
            UPDATE ref_publication_calendar
            SET actual_publication_date = :publication_date
            WHERE source = :source
              AND category = :category
              AND period_label = :period_label
            """
        ),
        {
            "publication_date": publication_date,
            "source": SOURCE,
            "category": CATEGORY,
            "period_label": period_label,
        },
    )

    session.flush()
    logger.info(
        "Upserted %d ECA records for %s (published %s)",
        len(records_list),
        period_label,
        publication_date,
    )
    return len(records_list)
