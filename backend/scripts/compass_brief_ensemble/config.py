"""Configuration for the Compass Brief Ensemble generator.

Reuses the legacy compass_brief Drive uploader + credentials env var. Filename
distinguishes ensemble briefs from legacy ones so both can coexist in the
same Drive folder.
"""

from __future__ import annotations

# Reuses the legacy config (same Drive folder, same credentials). The
# distinction between legacy and ensemble briefs is the FILENAME, not the
# folder, so editors / NotebookLM users can see both side by side.
from scripts.compass_brief.config import (  # noqa: F401 -- re-export
    DRIVE_BRIEFS_FOLDER_ENV_VAR,
    SCOPES_DRIVE,
    get_credentials_json,
    get_drive_briefs_folder_id,
)

# Filename pattern. Legacy is `YYYYMMDD-CompassBrief.txt`. Ensemble adds the
# `-Ensemble` suffix so the audio fetch path can distinguish them. The EN
# (Ghana) edition adds a further `-EN` suffix; the dashboard audio resolver
# matches on `(version, language)` → these exact stems (see
# audio_service._VERSION_FILENAME_SUFFIX and
# docs/runbooks/brief-multilingual-management.md).
FILENAME_PATTERN = "{date}-CompassBrief-Ensemble.txt"
FILENAME_PATTERN_EN = "{date}-CompassBrief-Ensemble-EN.txt"


def filename_for(date_str: str, language: str) -> str:
    """Return the brief filename for a session date stem and output language.

    ``en`` → ``YYYYMMDD-CompassBrief-Ensemble-EN.txt``; anything else (incl.
    ``fr``) → ``YYYYMMDD-CompassBrief-Ensemble.txt`` (fail-safe default).
    """
    pattern = FILENAME_PATTERN_EN if language == "en" else FILENAME_PATTERN
    return pattern.format(date=date_str)


# Algorithm version that this brief reads from (must match the ensemble row).
ALGORITHM_NAME = "ensemble_v1_softgate_wrapper"
ALGORITHM_VERSION = "1.0.0"

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"
