"""Google Sheets writer for TECHNICALS sheet."""

import json
import logging
from typing import Dict, List, Optional
from datetime import datetime

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from scripts.barchart_scraper.config import (
    SPREADSHEET_ID,
    SHEET_NAME_PRODUCTION,
)

logger = logging.getLogger(__name__)

# Google Sheets API scope (needs write access)
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


class SheetsWriterError(Exception):
    """Base exception for Sheets writer errors."""

    pass


class SheetsWriter:
    """Writes scraped data to Google Sheets TECHNICALS tab."""

    def __init__(self, credentials_json: str):
        """
        Initialize Sheets writer.

        Args:
            credentials_json: JSON string of service account credentials

        Raises:
            SheetsWriterError: If initialization fails
        """
        try:
            creds_dict = json.loads(credentials_json)
            self.credentials = Credentials.from_service_account_info(
                creds_dict, scopes=SCOPES
            )
            self.service = build("sheets", "v4", credentials=self.credentials)
            logger.info("Google Sheets API client initialized")
        except json.JSONDecodeError as e:
            raise SheetsWriterError(f"Invalid credentials JSON: {e}") from e
        except Exception as e:
            raise SheetsWriterError(f"Failed to initialize Sheets client: {e}") from e

    def _format_row(self, data: Dict[str, Optional[float]]) -> List:
        """
        Format data dict into row values matching TECHNICALS column order.

        Args:
            data: Scraped data dict with 6 fields + timestamp

        Returns:
            List of 7 values: [timestamp, close, high, low, volume, oi, iv]
        """
        # Format timestamp as MM/DD/YYYY (matches Google Form output)
        timestamp = data.get("timestamp", datetime.now())
        timestamp_str = timestamp.strftime("%m/%d/%Y")

        # Format IV as decimal for percentage display (48.99% → 0.4899)
        iv = data.get("implied_volatility")
        iv_decimal = iv / 100 if iv is not None else None

        # Build row in column order (A-G)
        row = [
            timestamp_str,  # Column A: Timestamp
            data.get("close"),  # Column B: CLOSE
            data.get("high"),  # Column C: HIGH
            data.get("low"),  # Column D: LOW
            data.get("volume"),  # Column E: VOLUME
            data.get("open_interest"),  # Column F: OPEN INTEREST
            iv_decimal,  # Column G: IMPLIED VOLATILITY (as decimal for % format)
            # Columns H-I (STOCK US, COM NET US) remain empty — Julien fills manually
        ]

        logger.debug(f"Formatted row: {row}")
        return row

    def append_row(
        self,
        data: Dict[str, Optional[float]],
        sheet_name: str = SHEET_NAME_PRODUCTION,
        dry_run: bool = False,
    ) -> None:
        """
        Append a new row to TECHNICALS sheet.

        Args:
            data: Scraped data dict with 6 fields + timestamp
            sheet_name: Target sheet name (TECHNICALS or TECHNICALS_STAGING)
            dry_run: If True, only log what would be written (no actual write)

        Raises:
            SheetsWriterError: If write fails
        """
        row = self._format_row(data)

        if dry_run:
            logger.info(f"[DRY RUN] Would append to '{sheet_name}': {row}")
            return

        try:
            # Append to end of sheet (next empty row)
            range_name = f"{sheet_name}!A:G"  # Columns A-G (7 fields)

            body = {"values": [row]}

            result = (
                self.service.spreadsheets()
                .values()
                .append(
                    spreadsheetId=SPREADSHEET_ID,
                    range=range_name,
                    valueInputOption="RAW",  # Write as raw values (not formulas)
                    insertDataOption="INSERT_ROWS",  # Insert new row, don't overwrite
                    body=body,
                )
                .execute()
            )

            updates = result.get("updates", {})
            updated_range = updates.get("updatedRange", "unknown")
            updated_rows = updates.get("updatedRows", 0)

            logger.info(
                f"Successfully wrote {updated_rows} row(s) to '{sheet_name}' at {updated_range}"
            )

        except HttpError as e:
            logger.error(f"Google Sheets API error: {e}")
            raise SheetsWriterError(
                f"Failed to write to sheet '{sheet_name}': {e}"
            ) from e
        except Exception as e:
            logger.error(f"Unexpected error writing to Sheets: {e}")
            raise SheetsWriterError(f"Write failed: {e}") from e
