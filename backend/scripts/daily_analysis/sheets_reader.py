"""Google Sheets reader for the daily analysis pipeline.

Reads from PRODUCTION sheets only (TECHNICALS, BIBLIO_ALL, METEO_ALL).
All reads use FORMATTED_VALUE render option to match Make.com behaviour.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from scripts.daily_analysis.config import (
    METEO_HISTORY_LIMIT,
    SCOPES,
    SOURCE_BIBLIO_ALL,
    SOURCE_METEO_ALL,
    SOURCE_TECHNICALS,
    SPREADSHEET_ID,
    TECHNICALS_VARIABLES,
)

logger = logging.getLogger(__name__)


class SheetsReaderError(Exception):
    """Raised on Sheets read failures."""


@dataclass
class TechnicalsData:
    """21 TOD/YES variable pairs extracted from the last 2 TECHNICALS rows."""

    today: dict[str, str] = field(default_factory=dict)
    yesterday: dict[str, str] = field(default_factory=dict)
    today_date: str = ""
    today_row_number: int = 0


@dataclass
class ContextData:
    """Aggregated text inputs for the LLM calls."""

    macronews: str  # BIBLIO_ALL RESUME values for target date
    meteonews: str  # METEO_ALL historical context (last N rows, formatted)
    meteotoday: str  # METEO_ALL RESUME for target date


@dataclass
class PipelineInputs:
    """All inputs needed for the daily analysis pipeline."""

    technicals: TechnicalsData
    context: ContextData
    target_date: datetime


class SheetsReader:
    """Reads market data from Google Sheets (production sheets only)."""

    def __init__(
        self, credentials_json: str, spreadsheet_id: str = SPREADSHEET_ID
    ) -> None:
        try:
            creds = json.loads(credentials_json)
            self.credentials = Credentials.from_service_account_info(
                creds, scopes=SCOPES
            )
            self.service = build("sheets", "v4", credentials=self.credentials)
            self.spreadsheet_id = spreadsheet_id
            logger.info("SheetsReader initialised")
        except (json.JSONDecodeError, Exception) as exc:
            raise SheetsReaderError(f"Failed to init Sheets client: {exc}") from exc

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def read_all(self, target_date: datetime) -> PipelineInputs:
        """Read all inputs for a given date.

        Args:
            target_date: The business date to read data for.

        Returns:
            PipelineInputs with technicals + context data.
        """
        technicals = self.read_technicals(target_date)
        context = self.read_context(target_date)
        return PipelineInputs(
            technicals=technicals, context=context, target_date=target_date
        )

    def read_technicals(self, target_date: datetime) -> TechnicalsData:
        """Read last 2 TECHNICALS rows and extract 21 TOD/YES variable pairs.

        Validates that the latest row matches the target date.
        """
        # Read column A to find the last row
        col_a = self._get_values(f"{SOURCE_TECHNICALS}!A:A")
        all_rows = col_a.get("values", [])
        last_row = len(all_rows)
        if last_row < 3:
            raise SheetsReaderError(f"TECHNICALS has too few rows ({last_row})")

        # Read columns A:AM for the last 2 rows (yesterday + today)
        start_row = last_row - 1
        result = self._get_values(f"{SOURCE_TECHNICALS}!A{start_row}:AM{last_row}")
        rows = result.get("values", [])
        if len(rows) < 2:
            raise SheetsReaderError(f"Expected 2 TECHNICALS rows, got {len(rows)}")

        yesterday_row = rows[0]
        today_row = rows[1]

        # Validate today's date
        today_date_str = today_row[0] if today_row else ""
        logger.info(
            "TECHNICALS: today=%s (row %d), yesterday=%s (row %d)",
            today_date_str,
            last_row,
            yesterday_row[0] if yesterday_row else "?",
            start_row,
        )

        # Extract TOD/YES pairs
        today_vars: dict[str, str] = {}
        yesterday_vars: dict[str, str] = {}

        for col_idx, var_name in TECHNICALS_VARIABLES.items():
            tod_val = _safe_get(today_row, col_idx)
            yes_val = _safe_get(yesterday_row, col_idx)
            today_vars[f"{var_name}TOD"] = tod_val
            yesterday_vars[f"{var_name}YES"] = yes_val

        logger.info(
            "TECHNICALS: extracted %d TOD + %d YES variables",
            len(today_vars),
            len(yesterday_vars),
        )

        return TechnicalsData(
            today=today_vars,
            yesterday=yesterday_vars,
            today_date=today_date_str,
            today_row_number=last_row,
        )

    def read_context(self, target_date: datetime) -> ContextData:
        """Read BIBLIO_ALL and METEO_ALL for context data."""
        macronews = self._read_macronews(target_date)
        meteonews = self._read_meteonews()
        meteotoday = self._read_meteotoday(target_date)
        return ContextData(
            macronews=macronews, meteonews=meteonews, meteotoday=meteotoday
        )

    # ------------------------------------------------------------------
    # BIBLIO_ALL
    # ------------------------------------------------------------------

    def _read_macronews(self, target_date: datetime) -> str:
        """Read BIBLIO_ALL rows for target date, aggregate RESUME → MACRONEWS."""
        date_str = target_date.strftime("%m/%d/%Y")

        # Read all rows with columns A:C (DATE, TEXTE, RESUME)
        result = self._get_values(f"{SOURCE_BIBLIO_ALL}!A:C")
        rows = result.get("values", [])

        if not rows:
            logger.warning("BIBLIO_ALL is empty")
            return ""

        # Skip header, filter by date in column A
        resumes: list[str] = []
        for row in rows[1:]:
            row_date = _safe_get(row, 0)
            if _dates_match(row_date, date_str):
                resume = _safe_get(row, 2)
                if resume:
                    resumes.append(resume)

        macronews = "\n\n".join(resumes)
        logger.info(
            "BIBLIO_ALL: %d rows for %s → MACRONEWS (%d chars)",
            len(resumes),
            date_str,
            len(macronews),
        )

        if not resumes:
            logger.warning("BIBLIO_ALL: no rows found for %s", date_str)

        return macronews

    # ------------------------------------------------------------------
    # METEO_ALL
    # ------------------------------------------------------------------

    def _read_meteonews(self) -> str:
        """Read last N METEO_ALL rows, format as 'MM/YYYY-{RESUME}' → METEONEWS."""
        result = self._get_values(f"{SOURCE_METEO_ALL}!A:C")
        rows = result.get("values", [])

        if len(rows) < 2:
            logger.warning("METEO_ALL is empty or header-only")
            return ""

        # Skip header, take last N rows, reverse (most recent first)
        data_rows = rows[1:]
        recent = data_rows[-METEO_HISTORY_LIMIT:]
        recent.reverse()

        parts: list[str] = []
        for row in recent:
            raw_date = _safe_get(row, 0)
            resume = _safe_get(row, 2)
            if not resume:
                continue
            formatted_date = _format_meteo_date(raw_date)
            parts.append(f"{formatted_date}-{resume}")

        meteonews = "\n".join(parts)
        logger.info(
            "METEO_ALL: %d rows → METEONEWS (%d chars)", len(parts), len(meteonews)
        )
        return meteonews

    def _read_meteotoday(self, target_date: datetime) -> str:
        """Read METEO_ALL row for target date → METEOTODAY."""
        date_str = target_date.strftime("%m/%d/%Y")

        result = self._get_values(f"{SOURCE_METEO_ALL}!A:C")
        rows = result.get("values", [])

        for row in rows[1:]:
            row_date = _safe_get(row, 0)
            if _dates_match(row_date, date_str):
                resume = _safe_get(row, 2)
                if resume:
                    logger.info(
                        "METEO_ALL: found METEOTODAY for %s (%d chars)",
                        date_str,
                        len(resume),
                    )
                    return resume

        logger.warning("METEO_ALL: no row found for %s", date_str)
        return ""

    # ------------------------------------------------------------------
    # Internal helpers
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
    """Safely get a cell value from a row, returning empty string if missing."""
    if idx < len(row):
        return str(row[idx]).strip()
    return ""


def _dates_match(row_date: str, target_date: str) -> bool:
    """Compare two MM/DD/YYYY dates ignoring leading zeros.

    Google Sheets FORMATTED_VALUE may return '2/24/2026' while
    strftime('%m/%d/%Y') produces '02/24/2026'.
    """
    try:
        a = datetime.strptime(row_date, "%m/%d/%Y")
        b = datetime.strptime(target_date, "%m/%d/%Y")
        return a == b
    except (ValueError, TypeError):
        return row_date == target_date


def _format_meteo_date(raw_date: str) -> str:
    """Convert MM/DD/YYYY or M/D/YYYY to MM/YYYY for METEONEWS context."""
    try:
        dt = datetime.strptime(raw_date, "%m/%d/%Y")
        return dt.strftime("%m/%Y")
    except (ValueError, TypeError):
        return raw_date
