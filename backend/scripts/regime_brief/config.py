"""Configuration for the regime+judge brief.

Reuses the Drive uploader and credentials of the legacy brief — same folder,
same service account. What distinguishes the briefs is the FILENAME, so several
tracks can coexist in one folder while they overlap.
"""

from __future__ import annotations

from scripts.compass_brief.config import (  # noqa: F401 -- re-export
    DRIVE_BRIEFS_FOLDER_ENV_VAR,
    SCOPES_DRIVE,
    get_credentials_json,
    get_drive_briefs_folder_id,
)

# The `-Regime` suffix is NOT cosmetic. The legacy brief writes
# `{date}-CompassBrief.txt` with no suffix and the Drive upload is idempotent
# (same name = overwrite), so reusing the bare name during the overlap would
# have the two jobs silently clobbering each other and the NotebookLM audio
# would become non-deterministic. Renaming to the bare form is possible later,
# once the legacy job is descheduled, and is purely cosmetic.
FILENAME_PATTERN = "{date}-CompassBrief-Regime.txt"
FILENAME_PATTERN_EN = "{date}-CompassBrief-Regime-EN.txt"


def filename_for(date_str: str, language: str) -> str:
    """Brief filename for a session-date stem and output language."""
    pattern = FILENAME_PATTERN_EN if language == "en" else FILENAME_PATTERN
    return pattern.format(date=date_str)


# The algorithm this brief speaks for. Read from pl_algorithm_version by name.
ALGORITHM_NAME = "regime"
ALGORITHM_VERSION = "1.0.0"

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"
