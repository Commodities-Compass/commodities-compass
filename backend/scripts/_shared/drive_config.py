"""Google Drive credentials + target folder, shared by every brief generator.

Extracted from ``compass_brief/config.py`` when the legacy and ensemble briefs
were retired: the Drive plumbing outlived the tracks that introduced it, and
leaving it under a deleted module would have taken ``cc-regime-brief`` down with
them.

One folder, one service account, several tracks — what distinguishes the briefs
is the FILENAME, which each generator owns in its own config.
"""

from __future__ import annotations

import os

# Drive only. The Sheets scope went away with the Sheets formula engine, but the
# credentials env var still carries its historical name.
SCOPES_DRIVE = ["https://www.googleapis.com/auth/drive"]

CREDENTIALS_ENV_VAR = "GOOGLE_SHEETS_SCRAPER_CREDENTIALS_JSON"
DRIVE_BRIEFS_FOLDER_ENV_VAR = "GOOGLE_DRIVE_BRIEFS_FOLDER_ID"
DRIVE_AUDIO_FOLDER_ENV_VAR = "GOOGLE_DRIVE_AUDIO_FOLDER_ID"
DRIVE_AUDIO_SHADOW_FOLDER_ENV_VAR = "GOOGLE_DRIVE_AUDIO_SHADOW_FOLDER_ID"


def get_credentials_json() -> str:
    """Service-account JSON, or fail loud with the variable to set."""
    value = os.environ.get(CREDENTIALS_ENV_VAR, "")
    if not value:
        raise RuntimeError(f"Missing environment variable: {CREDENTIALS_ENV_VAR}")
    return value


def get_drive_briefs_folder_id() -> str:
    """Target folder id, or fail loud with how to create it."""
    value = os.environ.get(DRIVE_BRIEFS_FOLDER_ENV_VAR, "")
    if not value:
        raise RuntimeError(
            f"Missing environment variable: {DRIVE_BRIEFS_FOLDER_ENV_VAR}\n"
            "Create a 'Compass Briefs' folder in Google Drive, share it with "
            "the service account as Editor, then set the folder ID in .env."
        )
    return value


def get_drive_audio_folder_id(*, shadow: bool) -> str:
    """Target folder for a generated episode.

    Two folders, deliberately. The watched one is what ``cc-publish-session``
    polls to flip the dashboard — a stray file there would publish an episode
    nobody has listened to. Shadow output cannot reach it by accident.
    """
    var = DRIVE_AUDIO_SHADOW_FOLDER_ENV_VAR if shadow else DRIVE_AUDIO_FOLDER_ENV_VAR
    value = os.environ.get(var, "")
    if not value:
        raise RuntimeError(
            f"Missing environment variable: {var}\n"
            "Create the folder in Google Drive, share it with the service "
            "account as Editor, then set the folder ID in .env."
        )
    return value
