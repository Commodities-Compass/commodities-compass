"""Google Sheets manager for ICE STOCK US data.

Updates column H (STOCK US) of the last row with a date in TECHNICALS.
Same pattern as CFTC scraper's sheets_manager (column I).
"""

import json
import logging

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from scripts.ice_stocks_scraper.config import (
    SHEET_NAME_PRODUCTION,
    SHEET_NAME_STAGING,
    SPREADSHEET_ID,
    STOCK_US_COLUMN_INDEX,
)

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


class SheetsManagerError(Exception):
    pass


class SheetsManager:
    """Updates STOCK US (column H) in TECHNICALS sheet."""

    def __init__(self, credentials_json: str, sheet_name: str = "staging"):
        try:
            creds_dict = json.loads(credentials_json)
            self.credentials = Credentials.from_service_account_info(
                creds_dict, scopes=SCOPES
            )
            self.service = build("sheets", "v4", credentials=self.credentials)
            self.sheet_name = (
                SHEET_NAME_STAGING if sheet_name == "staging" else SHEET_NAME_PRODUCTION
            )
            logger.info(f"Sheets manager initialized for: {self.sheet_name}")
        except json.JSONDecodeError as e:
            raise SheetsManagerError(f"Invalid credentials JSON: {e}") from e
        except Exception as e:
            raise SheetsManagerError(f"Failed to initialize Sheets client: {e}") from e

    def update_latest_row(self, value: int, dry_run: bool = False) -> str:
        """Update STOCK US (column H) for the last row with a date.

        Args:
            value: US certified stocks value (bags) to write
            dry_run: If True, only log what would be written

        Returns:
            Cell range updated (e.g., "TECHNICALS!H523")
        """
        try:
            # Read column A to find last row with a date
            range_name = f"{self.sheet_name}!A:A"
            result = (
                self.service.spreadsheets()
                .values()
                .get(spreadsheetId=SPREADSHEET_ID, range=range_name)
                .execute()
            )

            dates = result.get("values", [])
            if not dates or len(dates) < 2:
                raise SheetsManagerError("No data rows found in sheet")

            # Find last non-empty row (skip header at index 0)
            last_row_index = None
            last_date = None
            for i in range(len(dates) - 1, 0, -1):
                if dates[i] and dates[i][0]:
                    last_row_index = i + 1  # 1-based row number
                    last_date = dates[i][0]
                    break

            if not last_row_index:
                raise SheetsManagerError("No rows with dates found")

            # Column H
            column_letter = chr(65 + STOCK_US_COLUMN_INDEX)  # H
            cell_range = f"{self.sheet_name}!{column_letter}{last_row_index}"

            logger.info(
                f"Target: {cell_range} (date: {last_date}) — STOCK US: {value:,}"
            )

            if dry_run:
                logger.info(f"[DRY RUN] Would write {value:,} to {cell_range}")
                return cell_range

            self.service.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=cell_range,
                valueInputOption="RAW",
                body={"values": [[value]]},
            ).execute()

            logger.info(f"Successfully updated {cell_range} with {value:,}")
            return cell_range

        except HttpError as e:
            raise SheetsManagerError(f"Google Sheets API error: {e}") from e
        except SheetsManagerError:
            raise
        except Exception as e:
            raise SheetsManagerError(f"Unexpected error: {e}") from e
