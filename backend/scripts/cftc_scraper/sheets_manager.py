"""Google Sheets manager for CFTC data - Simple version."""

import json
import logging

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from scripts.cftc_scraper.config import (
    COM_NET_US_COLUMN_INDEX,
    SHEET_NAME_PRODUCTION,
    SHEET_NAME_STAGING,
    SPREADSHEET_ID,
)

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


class SheetsManagerError(Exception):
    """Base exception for Sheets manager errors."""

    pass


class SheetsManager:
    """Simple manager to update CFTC data in Google Sheets."""

    def __init__(self, credentials_json: str, sheet_name: str = "staging"):
        """
        Initialize Sheets manager.

        Args:
            credentials_json: JSON string of service account credentials
            sheet_name: 'staging' or 'production'

        Raises:
            SheetsManagerError: If initialization fails
        """
        try:
            creds_dict = json.loads(credentials_json)
            self.credentials = Credentials.from_service_account_info(
                creds_dict, scopes=SCOPES
            )
            self.service = build("sheets", "v4", credentials=self.credentials)

            self.sheet_name = (
                SHEET_NAME_STAGING if sheet_name == "staging" else SHEET_NAME_PRODUCTION
            )

            logger.info(f"Sheets manager initialized for sheet: {self.sheet_name}")

        except json.JSONDecodeError as e:
            raise SheetsManagerError(f"Invalid credentials JSON: {e}") from e
        except Exception as e:
            raise SheetsManagerError(f"Failed to initialize Sheets manager: {e}") from e

    def update_latest_row(self, value: float) -> str:
        """
        Update COM NET US (column I) for the last row with a date.

        Simple logic:
        1. Find last row with date in column A
        2. Update column I of that row

        Args:
            value: COM NET US value to write

        Returns:
            Cell range updated (e.g., "TECHNICALS!I523")

        Raises:
            SheetsManagerError: If update fails
        """
        try:
            # Read column A to find last row with date
            range_name = f"{self.sheet_name}!A:A"
            result = (
                self.service.spreadsheets()
                .values()
                .get(spreadsheetId=SPREADSHEET_ID, range=range_name)
                .execute()
            )

            dates = result.get("values", [])

            if not dates or len(dates) < 2:  # Need at least header + 1 data row
                raise SheetsManagerError("No data rows found in sheet")

            # Find last non-empty row (skip header at index 0)
            last_row_index = None
            for i in range(len(dates) - 1, 0, -1):  # Iterate backwards from end
                if dates[i] and dates[i][0]:  # Row exists and has date
                    last_row_index = i + 1  # Convert to 1-based row number
                    last_date = dates[i][0]
                    break

            if not last_row_index:
                raise SheetsManagerError("No rows with dates found")

            # Update column I of last row
            column_letter = chr(65 + COM_NET_US_COLUMN_INDEX)  # I
            cell_range = f"{self.sheet_name}!{column_letter}{last_row_index}"

            logger.info(
                f"Updating {cell_range} (date: {last_date}) with COM NET US: {value:,.0f}"
            )

            self.service.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=cell_range,
                valueInputOption="RAW",
                body={"values": [[value]]},
            ).execute()

            logger.info(f"✓ Successfully updated {cell_range}")

            return cell_range

        except HttpError as e:
            raise SheetsManagerError(f"Failed to update COM NET US: {e}") from e
        except Exception as e:
            raise SheetsManagerError(f"Unexpected error during update: {e}") from e
