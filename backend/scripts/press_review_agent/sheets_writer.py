"""Google Sheets writer for BIBLIO_ALL press review data."""

import json
import logging
from datetime import datetime

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from scripts.press_review_agent.config import (
    AUTHOR_LABELS,
    SHEET_NAMES,
    SPREADSHEET_ID,
    Provider,
)

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


class SheetsWriterError(Exception):
    pass


class SheetsWriter:
    def __init__(self, credentials_json: str) -> None:
        try:
            creds_dict = json.loads(credentials_json)
            self.credentials = Credentials.from_service_account_info(
                creds_dict, scopes=SCOPES
            )
            self.service = build("sheets", "v4", credentials=self.credentials)
            logger.info("Google Sheets writer initialized")
        except json.JSONDecodeError as e:
            raise SheetsWriterError(f"Invalid credentials JSON: {e}") from e
        except Exception as e:
            raise SheetsWriterError(f"Failed to init Sheets client: {e}") from e

    def append_row(
        self,
        provider: Provider,
        parsed: dict[str, str],
        sheet_mode: str,
        dry_run: bool = False,
    ) -> None:
        """Append press review row to the appropriate BIBLIO_ALL sheet.

        Columns: DATE | AUTEUR | RESUME | MOTS-CLE | IMPACT SYNTHETIQUES | DATE TEXT
        """
        sheet_name = SHEET_NAMES[sheet_mode][provider]
        now = datetime.now()

        row = [
            now.strftime("%m/%d/%Y"),
            AUTHOR_LABELS[provider],
            parsed["resume"],
            parsed["mots_cle"],
            parsed["impact_synthetiques"],
            '=TEXT(INDIRECT("A"&ROW()),"MM/DD/YYYY")',
        ]

        if dry_run:
            logger.info(
                f"[DRY RUN] [{provider.value}] Would append to '{sheet_name}': "
                f"DATE={row[0]}, AUTEUR={row[1]}, "
                f"RESUME={len(row[2])} chars, MOTS-CLE={len(row[3])} chars, "
                f"IMPACT={len(row[4])} chars, DATE_TEXT={row[5]}"
            )
            return

        try:
            result = (
                self.service.spreadsheets()
                .values()
                .append(
                    spreadsheetId=SPREADSHEET_ID,
                    range=f"{sheet_name}!A:F",
                    valueInputOption="USER_ENTERED",
                    insertDataOption="INSERT_ROWS",
                    body={"values": [row]},
                )
                .execute()
            )
            updates = result.get("updates", {})
            updated_range = updates.get("updatedRange", "unknown")
            logger.info(
                f"[{provider.value}] Wrote to '{sheet_name}' at {updated_range}"
            )

        except HttpError as e:
            raise SheetsWriterError(
                f"[{provider.value}] Failed to write to '{sheet_name}': {e}"
            ) from e
        except Exception as e:
            raise SheetsWriterError(f"[{provider.value}] Write failed: {e}") from e
