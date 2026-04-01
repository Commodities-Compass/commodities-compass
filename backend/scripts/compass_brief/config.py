"""Configuration for the Compass Brief generator.

Reads market data from PostgreSQL and uploads a structured text brief
to Google Drive for NotebookLM audio podcast generation.
"""

import os

# Google API scopes (Drive only — Sheets removed)
SCOPES_DRIVE = ["https://www.googleapis.com/auth/drive"]

# Environment variable names
CREDENTIALS_ENV_VAR = "GOOGLE_SHEETS_SCRAPER_CREDENTIALS_JSON"
DRIVE_BRIEFS_FOLDER_ENV_VAR = "GOOGLE_DRIVE_BRIEFS_FOLDER_ID"


def get_credentials_json() -> str:
    value = os.environ.get(CREDENTIALS_ENV_VAR, "")
    if not value:
        raise RuntimeError(f"Missing environment variable: {CREDENTIALS_ENV_VAR}")
    return value


def get_drive_briefs_folder_id() -> str:
    value = os.environ.get(DRIVE_BRIEFS_FOLDER_ENV_VAR, "")
    if not value:
        raise RuntimeError(
            f"Missing environment variable: {DRIVE_BRIEFS_FOLDER_ENV_VAR}\n"
            "Create a 'Compass Briefs' folder in Google Drive, share it with "
            "the service account as Editor, then set the folder ID in .env."
        )
    return value
