"""UPSERT writer for ICE COT EU data → pl_cot_eu_weekly.

The table has Postgres GENERATED columns (``prod_merc_net``, ``m_money_net``)
which we never set explicitly. The INSERT lists only the raw position
integers; Postgres computes the nets on its own.

UPSERT semantics: re-publishing the same Tuesday's data (e.g., ICE corrects a
prior snapshot) updates in place. Idempotent.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session

from scripts.ice_cot_eu_scraper.config import DEFAULT_CONTRACT_MARKET
from scripts.ice_cot_eu_scraper.parser import CotEuObservation

logger = logging.getLogger(__name__)


def upsert_cot_eu_rows(
    session: Session,
    records: Iterable[CotEuObservation],
    *,
    contract_market: str = DEFAULT_CONTRACT_MARKET,
) -> int:
    """UPSERT CotEuObservation rows into pl_cot_eu_weekly.

    For each record:
      * INSERT new row keyed on (release_date, contract_market).
      * ON CONFLICT → UPDATE all raw integer columns (GENERATED nets auto-recompute).
    """
    records_list = list(records)
    if not records_list:
        return 0

    sql = text(
        """
        INSERT INTO pl_cot_eu_weekly (
            release_date, report_date, contract_market,
            open_interest,
            prod_merc_long, prod_merc_short,
            m_money_long, m_money_short,
            other_rept_long, other_rept_short,
            non_rept_long, non_rept_short
        )
        VALUES (
            :release_date, :report_date, :contract_market,
            :open_interest,
            :prod_merc_long, :prod_merc_short,
            :m_money_long, :m_money_short,
            :other_rept_long, :other_rept_short,
            :non_rept_long, :non_rept_short
        )
        ON CONFLICT (release_date, contract_market) DO UPDATE
        SET report_date     = EXCLUDED.report_date,
            open_interest   = EXCLUDED.open_interest,
            prod_merc_long  = EXCLUDED.prod_merc_long,
            prod_merc_short = EXCLUDED.prod_merc_short,
            m_money_long    = EXCLUDED.m_money_long,
            m_money_short   = EXCLUDED.m_money_short,
            other_rept_long = EXCLUDED.other_rept_long,
            other_rept_short = EXCLUDED.other_rept_short,
            non_rept_long   = EXCLUDED.non_rept_long,
            non_rept_short  = EXCLUDED.non_rept_short
        """
    )

    for rec in records_list:
        session.execute(
            sql,
            {
                "release_date": rec.release_date,
                "report_date": rec.report_date,
                "contract_market": contract_market,
                "open_interest": rec.open_interest,
                "prod_merc_long": rec.prod_merc_long,
                "prod_merc_short": rec.prod_merc_short,
                "m_money_long": rec.m_money_long,
                "m_money_short": rec.m_money_short,
                "other_rept_long": rec.other_rept_long,
                "other_rept_short": rec.other_rept_short,
                "non_rept_long": rec.non_rept_long,
                "non_rept_short": rec.non_rept_short,
            },
        )

    session.flush()
    logger.info(
        "Upserted %d ICE COT EU rows (range %s..%s, market=%s)",
        len(records_list),
        records_list[0].release_date,
        records_list[-1].release_date,
        contract_market,
    )
    return len(records_list)
