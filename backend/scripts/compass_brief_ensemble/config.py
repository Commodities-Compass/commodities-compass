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
# `-Ensemble` suffix so the audio fetch path can distinguish them.
FILENAME_PATTERN = "{date}-CompassBrief-Ensemble.txt"

# Algorithm version that this brief reads from (must match the ensemble row).
ALGORITHM_NAME = "ensemble_v1_softgate_wrapper"
ALGORITHM_VERSION = "1.0.0"

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"
