"""Database reader for the daily analysis pipeline.

Replaces sheets_reader.py — reads from pl_* tables instead of Google Sheets.
Produces the same PipelineInputs structure so prompts.py works unchanged.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass
class TechnicalsData:
    """Today + yesterday technical data formatted for LLM prompts.

    Matches the interface expected by build_call2_prompt():
    - today: dict of {CLOSETOD: "2057", HIGHTOD: "2162", ...}
    - yesterday: dict of {CLOSEYES: "2100", HIGHYES: "2200", ...}
    """

    today: dict[str, str]
    yesterday: dict[str, str]
    today_date: str  # MM/DD/YYYY format for LLM
    today_date_iso: date  # ISO date for DB queries


@dataclass
class ContextData:
    """Market research + weather context for LLM Call #1."""

    macronews: str  # concatenated market research summaries for target date
    meteotoday: str  # weather summary for target date
    meteonews: str  # last 100 weather summaries formatted as history


@dataclass
class PipelineInputs:
    """All inputs needed by the analysis engine."""

    technicals: TechnicalsData
    context: ContextData


# Mapping from DB column → LLM variable name prefix.
# Each produces TOD and YES pairs (e.g., close → CLOSETOD / CLOSEYES).
_DB_TO_PROMPT_VARS: dict[str, str] = {
    "close": "CLOSE",
    "high": "HIGH",
    "low": "LOW",
    "volume": "VOL",
    "oi": "OI",
    "implied_volatility": "VOLIMP",
    "stock_us": "STOCK",
    "com_net_us": "COMNET",
    "r1": "R1",
    "pivot": "PIVOT",
    "s1": "S1",
    "ema12": "EMA9",  # Sheets col Q was labeled EMA9 but was actually EMA12
    "ema26": "EMA21",  # Sheets col R was labeled EMA21 but was actually EMA26
    "macd": "MACD",
    "macd_signal": "SIGN",
    "rsi_14d": "RSI14",
    "stochastic_k_14": "%K",
    "stochastic_d_14": "%D",
    "atr_14d": "ATR",
    "bollinger_upper": "BSUP",
    "bollinger_lower": "BBINF",
}

METEO_HISTORY_LIMIT = 100


class DBReader:
    """Reads pipeline inputs from the database (pl_* tables)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def read_all(self, target_date: date, contract_code: str) -> PipelineInputs:
        """Read all inputs for the daily analysis pipeline.

        Args:
            target_date: Business date to analyze.
            contract_code: Active contract code.

        Returns:
            PipelineInputs with technicals + context ready for prompts.
        """
        technicals = self._read_technicals(target_date, contract_code)
        context = self._read_context(target_date)

        return PipelineInputs(technicals=technicals, context=context)

    def _read_technicals(self, target_date: date, contract_code: str) -> TechnicalsData:
        """Read last 2 days of technicals + derived indicators from DB."""
        _technicals_sql = """
            SELECT
                d.date,
                d.close, d.high, d.low, d.volume, d.oi,
                d.implied_volatility, d.stock_us, d.com_net_us,
                di.r1, di.pivot, di.s1,
                di.ema12, di.ema26,
                di.macd, di.macd_signal,
                di.rsi_14d,
                di.stochastic_k_14, di.stochastic_d_14,
                di.atr_14d,
                di.bollinger_upper, di.bollinger_lower
            FROM pl_contract_data_daily d
            JOIN ref_contract c ON d.contract_id = c.id
            LEFT JOIN pl_derived_indicators di
                ON d.date = di.date AND d.contract_id = di.contract_id
        """
        # Primary: filter by active contract
        result = self._session.execute(
            text(
                _technicals_sql
                + " WHERE d.date <= :target_date AND c.code = :contract_code"
                " ORDER BY d.date DESC LIMIT 2"
            ),
            {"target_date": target_date, "contract_code": contract_code},
        )
        rows = result.fetchall()
        columns = result.keys()

        # Fallback for contract transition: if active contract has < 2 rows,
        # read cross-contract to bridge the gap (first days after a roll)
        if len(rows) < 2:
            logger.info(
                "Only %d rows for %s before %s — falling back to cross-contract read",
                len(rows),
                contract_code,
                target_date,
            )
            result = self._session.execute(
                text(
                    _technicals_sql + " WHERE d.date <= :target_date"
                    " ORDER BY d.date DESC LIMIT 2"
                ),
                {"target_date": target_date},
            )
            rows = result.fetchall()
            columns = result.keys()

        if len(rows) < 2:
            logger.warning("Not enough data: found %d rows, need 2", len(rows))
            empty = {f"{v}TOD": "" for v in _DB_TO_PROMPT_VARS.values()}
            empty_yes = {f"{v}YES": "" for v in _DB_TO_PROMPT_VARS.values()}
            return TechnicalsData(
                today=empty,
                yesterday=empty_yes,
                today_date=target_date.strftime("%m/%d/%Y"),
                today_date_iso=target_date,
            )

        today_row = dict(zip(columns, rows[0]))
        yesterday_row = dict(zip(columns, rows[1]))

        today_vars: dict[str, str] = {}
        yesterday_vars: dict[str, str] = {}

        for db_col, prompt_var in _DB_TO_PROMPT_VARS.items():
            today_val = today_row.get(db_col)
            yesterday_val = yesterday_row.get(db_col)
            today_vars[f"{prompt_var}TOD"] = _format_value(today_val)
            yesterday_vars[f"{prompt_var}YES"] = _format_value(yesterday_val)

        return TechnicalsData(
            today=today_vars,
            yesterday=yesterday_vars,
            today_date=today_row["date"].strftime("%m/%d/%Y"),
            today_date_iso=today_row["date"],
        )

    def _read_context(self, target_date: date) -> ContextData:
        """Read market research + weather data for LLM Call #1."""
        macronews = self._read_macronews(target_date)
        meteotoday = self._read_meteo_today(target_date)
        meteonews = self._read_meteo_history(target_date)

        return ContextData(
            macronews=macronews,
            meteotoday=meteotoday,
            meteonews=meteonews,
        )

    def _read_macronews(self, target_date: date) -> str:
        """Read market research summaries for the target date.

        Sources from pl_fundamental_article (new) with fallback to
        market_research (legacy).
        """
        # Try new table first
        result = self._session.execute(
            text("""
                SELECT summary FROM pl_fundamental_article
                WHERE date = :target_date AND is_active = true AND summary IS NOT NULL
                ORDER BY created_at DESC
            """),
            {"target_date": target_date},
        )
        rows = result.fetchall()

        if not rows:
            # Fallback to legacy table
            result = self._session.execute(
                text("""
                    SELECT summary FROM market_research
                    WHERE date = :target_date AND summary IS NOT NULL
                    ORDER BY id DESC
                """),
                {"target_date": target_date},
            )
            rows = result.fetchall()

        if not rows:
            return ""

        return "\n\n".join(row[0] for row in rows if row[0])

    def _read_meteo_today(self, target_date: date) -> str:
        """Read weather summary for the target date."""
        # Try new table first
        result = self._session.execute(
            text("""
                SELECT summary FROM pl_weather_observation
                WHERE date = :target_date AND summary IS NOT NULL
                LIMIT 1
            """),
            {"target_date": target_date},
        )
        row = result.fetchone()

        if not row:
            # Fallback to legacy table
            result = self._session.execute(
                text("""
                    SELECT summary FROM weather_data
                    WHERE date = :target_date AND summary IS NOT NULL
                    LIMIT 1
                """),
                {"target_date": target_date},
            )
            row = result.fetchone()

        return row[0] if row else ""

    def _read_meteo_history(self, target_date: date) -> str:
        """Read last 100 weather summaries formatted as history context."""
        # Try new table first
        result = self._session.execute(
            text("""
                SELECT date, summary FROM pl_weather_observation
                WHERE date <= :target_date AND summary IS NOT NULL
                ORDER BY date DESC
                LIMIT :limit
            """),
            {"target_date": target_date, "limit": METEO_HISTORY_LIMIT},
        )
        rows = result.fetchall()

        if not rows:
            # Fallback to legacy table
            result = self._session.execute(
                text("""
                    SELECT date, summary FROM weather_data
                    WHERE date <= :target_date AND summary IS NOT NULL
                    ORDER BY date DESC
                    LIMIT :limit
                """),
                {"target_date": target_date, "limit": METEO_HISTORY_LIMIT},
            )
            rows = result.fetchall()

        if not rows:
            return ""

        # Format as "MM/YYYY-{summary}" (matches Sheets reader format)
        formatted = []
        for row_date, summary in rows:
            month_year = row_date.strftime("%m/%Y")
            formatted.append(f"{month_year}-{summary}")

        return "\n".join(formatted)


def _format_value(value: object) -> str:
    """Format a DB value for prompt injection. None → empty string."""
    if value is None:
        return ""
    if isinstance(value, float):
        # Remove trailing zeros for cleaner prompts
        return f"{value:g}"
    return str(value)
