"""Database writer for CFTC US COT → pl_cot_us_weekly.

Refactored 2026-05-27: writes one row per real CFTC publication keyed on
``(release_date, contract_market)`` instead of overwriting the session
row of ``pl_contract_data_daily.com_net_us``. Mirrors the writer pattern
of ``ice_cot_eu_scraper`` (UPSERT idempotent on the release_date).
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from scripts.cftc_scraper.scraper import CocoaCotUsObservation

log = logging.getLogger(__name__)


class DbWriterError(Exception):
    pass


def upsert_cot_us_weekly(
    session: Session,
    obs: CocoaCotUsObservation,
    *,
    contract_market: str = "cocoa",
    dry_run: bool = False,
) -> bool:
    """UPSERT one CFTC US weekly observation. Idempotent on
    ``(release_date, contract_market)`` — re-running on a Friday after the
    publisher revised numbers will overwrite the row with the latest.

    GENERATED columns (``prod_merc_net``, ``m_money_net``) are never
    written directly; Postgres recomputes them from long/short.
    """
    if dry_run:
        log.info(
            "[DRY RUN] Would upsert pl_cot_us_weekly release_date=%s "
            "report_date=%s prod_merc_net=%d m_money_net=%d",
            obs.release_date,
            obs.report_date,
            obs.prod_merc_net,
            obs.m_money_net,
        )
        return False

    session.execute(
        text(
            """
            INSERT INTO pl_cot_us_weekly (
                release_date, report_date, contract_market,
                prod_merc_long, prod_merc_short,
                m_money_long, m_money_short,
                other_rept_long, other_rept_short,
                non_rept_long, non_rept_short,
                open_interest
            ) VALUES (
                :release_date, :report_date, :contract_market,
                :prod_merc_long, :prod_merc_short,
                :m_money_long, :m_money_short,
                :other_rept_long, :other_rept_short,
                :non_rept_long, :non_rept_short,
                :open_interest
            )
            ON CONFLICT (release_date, contract_market) DO UPDATE
            SET report_date       = EXCLUDED.report_date,
                prod_merc_long    = EXCLUDED.prod_merc_long,
                prod_merc_short   = EXCLUDED.prod_merc_short,
                m_money_long      = EXCLUDED.m_money_long,
                m_money_short     = EXCLUDED.m_money_short,
                other_rept_long   = EXCLUDED.other_rept_long,
                other_rept_short  = EXCLUDED.other_rept_short,
                non_rept_long     = EXCLUDED.non_rept_long,
                non_rept_short    = EXCLUDED.non_rept_short,
                open_interest     = EXCLUDED.open_interest;
            """
        ),
        {
            "release_date": obs.release_date,
            "report_date": obs.report_date,
            "contract_market": contract_market,
            "prod_merc_long": obs.prod_merc_long,
            "prod_merc_short": obs.prod_merc_short,
            "m_money_long": obs.m_money_long,
            "m_money_short": obs.m_money_short,
            "other_rept_long": obs.other_rept_long,
            "other_rept_short": obs.other_rept_short,
            "non_rept_long": obs.non_rept_long,
            "non_rept_short": obs.non_rept_short,
            "open_interest": obs.open_interest,
        },
    )
    session.flush()
    log.info(
        "Upserted pl_cot_us_weekly release_date=%s report_date=%s "
        "prod_merc_net=%d m_money_net=%d open_interest=%d",
        obs.release_date,
        obs.report_date,
        obs.prod_merc_net,
        obs.m_money_net,
        obs.open_interest,
    )
    return True
