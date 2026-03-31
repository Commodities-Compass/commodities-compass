"""Database reader for the Compass Brief generator.

Replaces sheets_reader.py — reads from pl_* tables instead of Google Sheets.
Produces the same BriefData/DayData structure so brief_generator.py works unchanged.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass
class DayData:
    """All data for a single business day (matches sheets_reader.DayData)."""

    date: str  # MM/DD/YYYY format for brief_generator
    technicals: dict[str, str] = field(default_factory=dict)
    indicators: dict[str, str] = field(default_factory=dict)
    decision: str = ""
    confiance: str = ""
    direction: str = ""
    score_text: str = ""
    press_review: str = ""
    meteo_resume: str = ""
    meteo_impact: str = ""


@dataclass
class BriefData:
    """Container for today + yesterday data."""

    today: DayData
    yesterday: DayData


# DB column → (brief label, format type)
# Format types: "int" = no decimals, "dec2" = 2 decimals, "pct" = percentage, "str" = as-is
_TECHNICALS_MAP: dict[str, tuple[str, str]] = {
    "close": ("CLOSE", "int"),
    "high": ("HIGH", "int"),
    "low": ("LOW", "int"),
    "volume": ("VOLUME", "int"),
    "oi": ("OI", "int"),
    "implied_volatility": ("IV", "pct"),
    "stock_us": ("STOCK US", "int"),
    "com_net_us": ("COM NET US", "int"),
    "r1": ("R1", "int"),
    "pivot": ("PIVOT", "int"),
    "s1": ("S1", "int"),
    "ema12": ("EMA9", "int"),  # brief uses legacy Sheets labels
    "ema26": ("EMA21", "int"),
    "macd": ("MACD", "int"),
    "macd_signal": ("SIGNAL", "int"),
    "rsi_14d": ("RSI 14D", "dec2"),
    "stochastic_k_14": ("%K", "dec2"),
    "stochastic_d_14": ("%D", "dec2"),
    "atr_14d": ("ATR", "int"),
    "bollinger_upper": ("BANDE SUP", "int"),
    "bollinger_lower": ("BANDE INF", "int"),
}

# DB column → (brief label, format type)
_INDICATOR_MAP: dict[str, tuple[str, str]] = {
    "rsi_score": ("RSI SCORE", "dec2"),
    "macd_score": ("MACD SCORE", "int"),
    "stochastic_score": ("STOCHASTIC SCORE", "dec2"),
    "atr_score": ("ATR SCORE", "dec2"),
    "close_pivot": ("CLOSE/PIVOT", "dec3"),
    "volume_oi": ("VOLUME/OI", "pct"),
    "rsi_norm": ("RSI NORM", "dec2"),
    "macd_norm": ("MACD NORM", "dec2"),
    "stoch_k_norm": ("STOCH %K NORM", "dec2"),
    "atr_norm": ("ATR NORM", "dec2"),
    "close_pivot_norm": ("CLOSE/PIVOT NORM", "dec2"),
    "vol_oi_norm": ("VOL/OI NORM", "dec2"),
    "indicator_value": ("INDICATOR", "dec3"),
    "momentum": ("MOMENTUM", "dec3"),
    "macroeco_bonus": ("MACROECO BONUS", "dec2"),
    "final_indicator": ("FINAL INDICATOR", "dec3"),
    "decision": ("CONCLUSION", "str"),
    "macroeco_score": ("MACROECO SCORE", "dec1"),
    "eco": ("ECO", "str"),
}


_INDICATOR_DAILY_FILTER = """
    JOIN pl_algorithm_version av ON i.algorithm_version_id = av.id AND av.is_active = true
"""


class DBBriefReader:
    """Reads brief data from the database (pl_* tables)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def read_all(self) -> BriefData:
        """Read last 2 days of data for brief generation."""
        dates = self._get_last_two_dates()
        if len(dates) < 2:
            raise ValueError(f"Need at least 2 days of data, found {len(dates)}")

        today_date = dates[0]
        yesterday_date = dates[1]

        today = self._read_day(today_date)
        yesterday = self._read_day(yesterday_date)

        return BriefData(today=today, yesterday=yesterday)

    def _get_last_two_dates(self) -> list[date]:
        """Get the last 2 distinct dates from pl_contract_data_daily."""
        result = self._session.execute(
            text("""
                SELECT DISTINCT date FROM pl_contract_data_daily
                ORDER BY date DESC LIMIT 2
            """),
        )
        return [row[0] for row in result]

    def _read_day(self, target_date: date) -> DayData:
        """Read all data for a single day."""
        technicals = self._read_technicals(target_date)
        indicators = self._read_indicators(target_date)
        press_review = self._read_press_review(target_date)
        meteo_resume, meteo_impact = self._read_meteo(target_date)

        return DayData(
            date=target_date.strftime("%m/%d/%Y"),
            technicals=technicals,
            indicators=indicators,
            decision=indicators.get("CONCLUSION", ""),
            confiance=str(self._read_confidence(target_date)),
            direction=self._read_direction(target_date),
            score_text=self._read_score_text(target_date),
            press_review=press_review,
            meteo_resume=meteo_resume,
            meteo_impact=meteo_impact,
        )

    def _read_technicals(self, target_date: date) -> dict[str, str]:
        """Read raw market data + derived indicators for a date."""
        result = self._session.execute(
            text("""
                SELECT
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
                LEFT JOIN pl_derived_indicators di
                    ON d.date = di.date AND d.contract_id = di.contract_id
                WHERE d.date = :target_date
                ORDER BY d.date DESC
                LIMIT 1
            """),
            {"target_date": target_date},
        )
        row = result.fetchone()
        if not row:
            return {}

        columns = result.keys()
        row_dict = dict(zip(columns, row))

        technicals: dict[str, str] = {}
        for db_col, (label, fmt_type) in _TECHNICALS_MAP.items():
            val = row_dict.get(db_col)
            technicals[label] = _fmt(val, fmt_type)

        return technicals

    def _read_indicators(self, target_date: date) -> dict[str, str]:
        """Read indicator scores + norms + composite for a date."""
        result = self._session.execute(
            text(f"""
                SELECT
                    i.rsi_score, i.macd_score, i.stochastic_score, i.atr_score,
                    i.close_pivot, i.volume_oi,
                    i.rsi_norm, i.macd_norm, i.stoch_k_norm, i.atr_norm,
                    i.close_pivot_norm, i.vol_oi_norm,
                    i.indicator_value, i.momentum,
                    i.macroeco_bonus, i.macroeco_score,
                    i.final_indicator, i.decision, i.eco
                FROM pl_indicator_daily i
                {_INDICATOR_DAILY_FILTER}
                WHERE i.date = :target_date
                ORDER BY i.created_at DESC
                LIMIT 1
            """),
            {"target_date": target_date},
        )
        row = result.fetchone()
        if not row:
            return {}

        columns = result.keys()
        row_dict = dict(zip(columns, row))

        indicators: dict[str, str] = {}
        for db_col, (label, fmt_type) in _INDICATOR_MAP.items():
            val = row_dict.get(db_col)
            indicators[label] = _fmt(val, fmt_type)

        return indicators

    def _read_confidence(self, target_date: date) -> str:
        """Read LLM confidence for a date."""
        result = self._session.execute(
            text(f"""
                SELECT i.confidence FROM pl_indicator_daily i
                {_INDICATOR_DAILY_FILTER}
                WHERE i.date = :target_date
                ORDER BY i.created_at DESC LIMIT 1
            """),
            {"target_date": target_date},
        )
        row = result.fetchone()
        return _fmt(row[0], "int") if row and row[0] else ""

    def _read_direction(self, target_date: date) -> str:
        """Read LLM direction for a date."""
        result = self._session.execute(
            text(f"""
                SELECT i.direction FROM pl_indicator_daily i
                {_INDICATOR_DAILY_FILTER}
                WHERE i.date = :target_date
                ORDER BY i.created_at DESC LIMIT 1
            """),
            {"target_date": target_date},
        )
        row = result.fetchone()
        return str(row[0]) if row and row[0] else ""

    def _read_score_text(self, target_date: date) -> str:
        """Read LLM conclusion/score text for a date."""
        result = self._session.execute(
            text(f"""
                SELECT i.conclusion FROM pl_indicator_daily i
                {_INDICATOR_DAILY_FILTER}
                WHERE i.date = :target_date
                ORDER BY i.created_at DESC LIMIT 1
            """),
            {"target_date": target_date},
        )
        row = result.fetchone()
        return str(row[0]) if row and row[0] else ""

    def _read_press_review(self, target_date: date) -> str:
        """Read press review summaries for a date."""
        # Try new table first, fallback to legacy
        result = self._session.execute(
            text("""
                SELECT summary FROM pl_fundamental_article
                WHERE date = :target_date AND summary IS NOT NULL
                ORDER BY created_at DESC
            """),
            {"target_date": target_date},
        )
        rows = result.fetchall()

        if not rows:
            result = self._session.execute(
                text("""
                    SELECT summary FROM market_research
                    WHERE date = :target_date AND summary IS NOT NULL
                    ORDER BY id DESC
                """),
                {"target_date": target_date},
            )
            rows = result.fetchall()

        return "\n".join(row[0] for row in rows if row[0])

    def _read_meteo(self, target_date: date) -> tuple[str, str]:
        """Read weather summary + impact for a date. Returns (resume, impact)."""
        # Try new table first
        result = self._session.execute(
            text("""
                SELECT summary, impact_assessment FROM pl_weather_observation
                WHERE date = :target_date AND summary IS NOT NULL
                ORDER BY created_at DESC
                LIMIT 1
            """),
            {"target_date": target_date},
        )
        row = result.fetchone()

        if not row:
            result = self._session.execute(
                text("""
                    SELECT summary, impact_synthesis FROM weather_data
                    WHERE date = :target_date AND summary IS NOT NULL
                    LIMIT 1
                """),
                {"target_date": target_date},
            )
            row = result.fetchone()

        if not row:
            return "", ""
        return str(row[0] or ""), str(row[1] or "")


def _fmt(value: object, fmt_type: str = "str") -> str:
    """Format a DB value to match Sheets FORMATTED_VALUE display style.

    Format types:
        int  - round to integer, no decimals (e.g. 2414)
        dec1 - 1 decimal place (e.g. 1.0)
        dec2 - 2 decimal places (e.g. 69.48)
        dec3 - 3 decimal places (e.g. -9.559)
        pct  - percentage display (e.g. 36.34%)
        str  - as-is string
    """
    if value is None:
        return ""
    try:
        num = float(value)
    except (ValueError, TypeError):
        return str(value)

    if fmt_type == "str":
        return str(value)
    if fmt_type == "int":
        return str(round(num))
    if fmt_type == "dec1":
        return f"{num:.1f}"
    if fmt_type == "dec2":
        return f"{num:.2f}"
    if fmt_type == "dec3":
        return f"{num:.3f}"
    if fmt_type == "pct":
        return f"{num * 100:.2f}%"
    return str(value)
