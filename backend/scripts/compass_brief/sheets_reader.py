"""Google Sheets reader for the Compass Brief generator.

Reads from PRODUCTION sheets only: TECHNICALS, INDICATOR, BIBLIO_ALL, METEO_ALL.
All reads use FORMATTED_VALUE to match Make.com behaviour.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from scripts.compass_brief.config import (
    INDICATOR_COLS,
    SCOPES_SHEETS,
    SOURCE_BIBLIO_ALL,
    SOURCE_INDICATOR,
    SOURCE_METEO_ALL,
    SOURCE_TECHNICALS,
    SPREADSHEET_ID,
    TECHNICALS_COLS,
)

logger = logging.getLogger(__name__)


class SheetsReaderError(Exception):
    pass


@dataclass
class DayData:
    """All data for a single business day."""

    date: str
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
    """Combined data for today and yesterday."""

    today: DayData
    yesterday: DayData


class SheetsReader:
    """Reads market data from Google Sheets (production sheets only)."""

    def __init__(
        self, credentials_json: str, spreadsheet_id: str = SPREADSHEET_ID
    ) -> None:
        creds = json.loads(credentials_json)
        self.credentials = Credentials.from_service_account_info(
            creds, scopes=SCOPES_SHEETS
        )
        self.service = build("sheets", "v4", credentials=self.credentials)
        self.spreadsheet_id = spreadsheet_id
        logger.info("SheetsReader initialised")

    def read_all(self) -> BriefData:
        """Read all data needed for the brief."""
        today_tech, yesterday_tech, today_date, yesterday_date = self._read_technicals()
        today_ind, yesterday_ind = self._read_indicator()

        # Read press and meteo once, filter for both dates
        press_map = self._read_press_by_dates([today_date, yesterday_date])
        meteo_map = self._read_meteo_by_dates([today_date, yesterday_date])

        today = self._build_day(today_date, today_tech, today_ind, press_map, meteo_map)
        yesterday = self._build_day(
            yesterday_date, yesterday_tech, yesterday_ind, press_map, meteo_map
        )

        return BriefData(today=today, yesterday=yesterday)

    def _build_day(
        self,
        date_str: str,
        tech: dict[str, str],
        ind: dict[str, str],
        press_map: dict[str, str],
        meteo_map: dict[str, tuple[str, str]],
    ) -> DayData:
        """Build a DayData from raw dicts, extracting decision fields from technicals."""
        return DayData(
            date=date_str,
            technicals={
                k: v
                for k, v in tech.items()
                if k not in ("DECISION", "CONFIANCE", "DIRECTION", "SCORE")
            },
            indicators=ind,
            decision=tech.get("DECISION", ""),
            confiance=tech.get("CONFIANCE", ""),
            direction=tech.get("DIRECTION", ""),
            score_text=tech.get("SCORE", ""),
            press_review=press_map.get(date_str, ""),
            meteo_resume=meteo_map.get(date_str, ("", ""))[0],
            meteo_impact=meteo_map.get(date_str, ("", ""))[1],
        )

    # ------------------------------------------------------------------
    # TECHNICALS
    # ------------------------------------------------------------------

    def _read_technicals(
        self,
    ) -> tuple[dict[str, str], dict[str, str], str, str]:
        """Read last 2 TECHNICALS rows (A:AR). Returns (today, yesterday, today_date, yesterday_date)."""
        col_a = self._get_values(f"{SOURCE_TECHNICALS}!A:A")
        all_rows = col_a.get("values", [])
        last_row = len(all_rows)
        if last_row < 3:
            raise SheetsReaderError(f"TECHNICALS has too few rows ({last_row})")

        start_row = last_row - 1
        result = self._get_values(f"{SOURCE_TECHNICALS}!A{start_row}:AR{last_row}")
        rows = result.get("values", [])
        if len(rows) < 2:
            raise SheetsReaderError(f"Expected 2 TECHNICALS rows, got {len(rows)}")

        yesterday_row, today_row = rows[0], rows[1]
        today_date = _safe_get(today_row, 0)
        yesterday_date = _safe_get(yesterday_row, 0)

        today_data = {
            label: _safe_get(today_row, idx) for idx, label in TECHNICALS_COLS.items()
        }
        yesterday_data = {
            label: _safe_get(yesterday_row, idx)
            for idx, label in TECHNICALS_COLS.items()
        }

        logger.info("TECHNICALS: today=%s, yesterday=%s", today_date, yesterday_date)
        return today_data, yesterday_data, today_date, yesterday_date

    # ------------------------------------------------------------------
    # INDICATOR
    # ------------------------------------------------------------------

    def _read_indicator(self) -> tuple[dict[str, str], dict[str, str]]:
        """Read last 2 INDICATOR rows (A:T). Returns (today, yesterday)."""
        col_a = self._get_values(f"{SOURCE_INDICATOR}!A:A")
        all_rows = col_a.get("values", [])
        last_row = len(all_rows)
        if last_row < 3:
            raise SheetsReaderError(f"INDICATOR has too few rows ({last_row})")

        start_row = last_row - 1
        result = self._get_values(f"{SOURCE_INDICATOR}!A{start_row}:T{last_row}")
        rows = result.get("values", [])
        if len(rows) < 2:
            raise SheetsReaderError(f"Expected 2 INDICATOR rows, got {len(rows)}")

        yesterday_row, today_row = rows[0], rows[1]

        today_data = {
            label: _safe_get(today_row, idx) for idx, label in INDICATOR_COLS.items()
        }
        yesterday_data = {
            label: _safe_get(yesterday_row, idx)
            for idx, label in INDICATOR_COLS.items()
        }

        logger.info(
            "INDICATOR: today=%s, yesterday=%s",
            today_data.get("CONCLUSION", "?"),
            yesterday_data.get("CONCLUSION", "?"),
        )
        return today_data, yesterday_data

    # ------------------------------------------------------------------
    # BIBLIO_ALL
    # ------------------------------------------------------------------

    def _read_press_by_dates(self, dates: list[str]) -> dict[str, str]:
        """Read BIBLIO_ALL once, return {date_str: aggregated_resume} for matching dates."""
        result = self._get_values(f"{SOURCE_BIBLIO_ALL}!A:C")
        rows = result.get("values", [])

        by_date: dict[str, list[str]] = {d: [] for d in dates}

        for row in rows[1:]:
            row_date = _safe_get(row, 0)
            for target_date in dates:
                if _dates_match(row_date, target_date):
                    resume = _safe_get(row, 2)
                    if resume:
                        by_date[target_date].append(resume)

        press_map: dict[str, str] = {}
        for d, resumes in by_date.items():
            text = "\n\n".join(resumes)
            logger.info(
                "BIBLIO_ALL [%s]: %d entries, %d chars", d, len(resumes), len(text)
            )
            press_map[d] = text

        return press_map

    # ------------------------------------------------------------------
    # METEO_ALL
    # ------------------------------------------------------------------

    def _read_meteo_by_dates(self, dates: list[str]) -> dict[str, tuple[str, str]]:
        """Read METEO_ALL once, return {date_str: (resume, impact)} for matching dates."""
        result = self._get_values(f"{SOURCE_METEO_ALL}!A:E")
        rows = result.get("values", [])

        meteo_map: dict[str, tuple[str, str]] = {}

        for row in rows[1:]:
            row_date = _safe_get(row, 0)
            for target_date in dates:
                if _dates_match(row_date, target_date):
                    resume = _safe_get(row, 2)
                    impact = _safe_get(row, 4)
                    logger.info(
                        "METEO_ALL [%s]: resume=%d chars, impact=%d chars",
                        target_date,
                        len(resume),
                        len(impact),
                    )
                    meteo_map[target_date] = (resume, impact)

        for d in dates:
            if d not in meteo_map:
                logger.warning("METEO_ALL: no row for %s", d)
                meteo_map[d] = ("", "")

        return meteo_map

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_values(
        self, range_: str, *, value_render_option: str = "FORMATTED_VALUE"
    ) -> dict:
        try:
            return (
                self.service.spreadsheets()
                .values()
                .get(
                    spreadsheetId=self.spreadsheet_id,
                    range=range_,
                    valueRenderOption=value_render_option,
                )
                .execute()
            )
        except HttpError as exc:
            raise SheetsReaderError(f"Sheets read failed ({range_}): {exc}") from exc


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _safe_get(row: list, idx: int) -> str:
    if idx < len(row):
        return str(row[idx]).strip()
    return ""


def _dates_match(a: str, b: str) -> bool:
    """Compare MM/DD/YYYY dates ignoring leading zeros."""
    try:
        da = datetime.strptime(a, "%m/%d/%Y")
        db = datetime.strptime(b, "%m/%d/%Y")
        return da == db
    except (ValueError, TypeError):
        return a == b
