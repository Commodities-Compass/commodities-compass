"""Google Sheets reader for TECHNICALS data (close price)."""

import json
import logging

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from scripts.press_review_agent.config import (
    CLOSE_COLUMN_INDEX,
    SPREADSHEET_ID,
    TECHNICALS_SHEET,
)

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


class SheetsReaderError(Exception):
    pass


class SheetsReader:
    def __init__(self, credentials_json: str) -> None:
        try:
            creds_dict = json.loads(credentials_json)
            self.credentials = Credentials.from_service_account_info(
                creds_dict, scopes=SCOPES
            )
            self.service = build("sheets", "v4", credentials=self.credentials)
            logger.info("Google Sheets reader initialized")
        except json.JSONDecodeError as e:
            raise SheetsReaderError(f"Invalid credentials JSON: {e}") from e
        except Exception as e:
            raise SheetsReaderError(f"Failed to init Sheets client: {e}") from e

    def read_latest_close(self, sheet_mode: str = "staging") -> tuple[str, str]:
        """Read CLOSE price and date from the last row of TECHNICALS.

        Always reads from production TECHNICALS sheet regardless of mode.

        Returns:
            Tuple of (close_price_str, date_str) from last row.

        Raises:
            SheetsReaderError: If no data found or CLOSE is empty.
        """
        sheet_name = TECHNICALS_SHEET
        try:
            result = (
                self.service.spreadsheets()
                .values()
                .get(spreadsheetId=SPREADSHEET_ID, range=f"{sheet_name}!A:B")
                .execute()
            )
            values = result.get("values", [])
            if not values or len(values) < 2:
                raise SheetsReaderError(f"No data rows in {sheet_name}")

            for i in range(len(values) - 1, 0, -1):
                row = values[i]
                if row and row[0]:
                    date_str = row[0]
                    close_str = (
                        row[CLOSE_COLUMN_INDEX]
                        if len(row) > CLOSE_COLUMN_INDEX
                        else None
                    )
                    if not close_str:
                        raise SheetsReaderError(
                            f"Last row (date={date_str}) has no CLOSE value"
                        )
                    logger.info(f"Read CLOSE={close_str} for date={date_str}")
                    return close_str, date_str

            raise SheetsReaderError(f"No rows with dates found in {sheet_name}")

        except HttpError as e:
            raise SheetsReaderError(f"Sheets API error: {e}") from e
