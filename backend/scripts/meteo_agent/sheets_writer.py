"""Google Sheets writer for METEO_ALL weather data."""

import json
import logging
from datetime import datetime, timezone

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from scripts.meteo_agent.config import SHEET_NAME, SPREADSHEET_ID

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

    def write_row(
        self,
        parsed: dict[str, str],
        dry_run: bool = False,
    ) -> None:
        """Write meteo analysis row to METEO_ALL sheet.

        Columns: DATE | TEXTE | RESUME | MOTS-CLE | IMPACT SYNTHETIQUES
        """
        now = datetime.now(timezone.utc)

        row = [
            now.strftime("%m/%d/%Y"),
            parsed["texte"],
            parsed["resume"],
            parsed["mots_cle"],
            parsed["impact_synthetiques"],
        ]

        if dry_run:
            logger.info(
                "[DRY RUN] Would write to '%s': DATE=%s, "
                "TEXTE=%d chars, RESUME=%d chars, "
                "MOTS-CLE=%d chars, IMPACT=%d chars",
                SHEET_NAME,
                row[0],
                len(row[1]),
                len(row[2]),
                len(row[3]),
                len(row[4]),
            )
            return

        try:
            # Explicit row detection + update() instead of append().
            # append() with INSERT_ROWS misplaces rows on sheets with
            # Table objects (inserts at top instead of bottom).
            existing = (
                self.service.spreadsheets()
                .values()
                .get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!A:A")
                .execute()
            )
            next_row = len(existing.get("values", [])) + 1
            target_range = f"{SHEET_NAME}!A{next_row}:E{next_row}"

            result = (
                self.service.spreadsheets()
                .values()
                .update(
                    spreadsheetId=SPREADSHEET_ID,
                    range=target_range,
                    valueInputOption="USER_ENTERED",
                    body={"values": [row]},
                )
                .execute()
            )
            updated_range = result.get("updatedRange", "unknown")
            logger.info("Wrote to '%s' at %s", SHEET_NAME, updated_range)

        except HttpError as e:
            raise SheetsWriterError(f"Failed to write to '{SHEET_NAME}': {e}") from e
        except Exception as e:
            raise SheetsWriterError(f"Write failed: {e}") from e
