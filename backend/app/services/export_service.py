"""Data series export service — honest CSV bridge before the self-service API.

Streams already-prepared ``pl_*`` series as CSV over a date range. No keys /
quotas / metering (that's the co-construct Enterprise API). Auth-gated at the
endpoint; any valid Auth0 user may export (single shared-view model).

Roll-safety: the ``ohlcv`` and ``indicators`` series read through
``v_contract_data_chained`` (front-month-by-OI/volume per date) so exported
history is continuous across contract rolls — never filtered on a single
``ref_contract.is_active`` snapshot.
"""

from __future__ import annotations

import csv
import io
import logging
from collections.abc import AsyncIterator
from datetime import date as date_cls

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Registry of exportable series → parameterized SELECT. Every query is bound on
# :dfrom / :dto (inclusive) and ordered by its natural date column. Column names
# in the CSV header are taken verbatim from the result set — no duplicated lists.
EXPORT_SERIES: dict[str, str] = {
    # OHLCV — roll-safe front-month chain (DISTINCT ON date by OI then volume).
    "ohlcv": """
        SELECT date, display_date, open, high, low, close, volume, oi,
               implied_volatility
        FROM v_contract_data_chained
        WHERE date BETWEEN :dfrom AND :dto
        ORDER BY date
    """,
    # Technical indicators, joined to the chain so each date carries the
    # front-month contract's indicators (not a stale post-roll contract).
    "indicators": """
        SELECT d.date, d.rsi_14d, d.macd, d.macd_signal, d.ema12, d.ema26,
               d.atr_14d, d.stochastic_k_14, d.stochastic_d_14,
               d.bollinger_upper, d.bollinger, d.bollinger_lower,
               d.close_pivot_ratio, d.volume_oi_ratio, d.daily_return
        FROM pl_derived_indicators d
        JOIN v_contract_data_chained v
          ON v.date = d.date AND v.contract_id = d.contract_id
        WHERE d.date BETWEEN :dfrom AND :dto
        ORDER BY d.date
    """,
    # FX (ECB business days). ENSO rows share the table with NULL fx → filtered.
    "fx": """
        SELECT date, fx_dxy_proxy, fx_gbpusd, fx_eurusd, fx_gbpeur
        FROM pl_external_indicator
        WHERE date BETWEEN :dfrom AND :dto AND fx_eurusd IS NOT NULL
        ORDER BY date
    """,
    # COT — ICE Europe (London #7) weekly positioning.
    "cot_eu": """
        SELECT report_date, release_date, contract_market,
               prod_merc_long, prod_merc_short, prod_merc_net,
               m_money_long, m_money_short, m_money_net,
               other_rept_long, other_rept_short,
               non_rept_long, non_rept_short, open_interest
        FROM pl_cot_eu_weekly
        WHERE report_date BETWEEN :dfrom AND :dto
        ORDER BY report_date
    """,
    # COT — CFTC US (NY cocoa) weekly positioning.
    "cot_us": """
        SELECT report_date, release_date, contract_market,
               prod_merc_long, prod_merc_short, prod_merc_net,
               m_money_long, m_money_short, m_money_net,
               other_rept_long, other_rept_short,
               non_rept_long, non_rept_short, open_interest
        FROM pl_cot_us_weekly
        WHERE report_date BETWEEN :dfrom AND :dto
        ORDER BY report_date
    """,
    # Certified stocks (US + EU regions), canonical tonnes + native audit.
    "stocks": """
        SELECT report_date, region, value_native, unit_native, value_tonnes,
               contract_market, source
        FROM pl_stock_observation
        WHERE report_date BETWEEN :dfrom AND :dto
        ORDER BY report_date, region
    """,
    # Weather observations (6 cocoa-growing locations, FR/EN language dim).
    "weather": """
        SELECT date, region, language, summary, keywords, impact_assessment
        FROM pl_weather_observation
        WHERE date BETWEEN :dfrom AND :dto
        ORDER BY date, region
    """,
}


def available_series() -> list[str]:
    """Sorted list of exportable series keys (for validation + docs)."""
    return sorted(EXPORT_SERIES)


async def stream_series_csv(
    db: AsyncSession,
    series: str,
    date_from: date_cls,
    date_to: date_cls,
) -> AsyncIterator[str]:
    """Yield the requested series as CSV chunks (header first, then rows).

    Raises ``KeyError`` if ``series`` is unknown — the endpoint validates before
    calling, so this is a fail-loud guard, not a user-facing path.
    """
    sql = EXPORT_SERIES[series]
    result = await db.stream(text(sql), {"dfrom": date_from, "dto": date_to})

    buffer = io.StringIO()
    writer = csv.writer(buffer)

    writer.writerow(result.keys())
    yield _drain(buffer)

    row_count = 0
    async for row in result:
        writer.writerow(list(row))
        yield _drain(buffer)
        row_count += 1

    logger.info(
        "export series=%s from=%s to=%s rows=%d",
        series,
        date_from.isoformat(),
        date_to.isoformat(),
        row_count,
    )


def _drain(buffer: io.StringIO) -> str:
    """Return the buffer's contents and reset it for the next row."""
    value = buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)
    return value
