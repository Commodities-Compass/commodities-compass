"""Audio service for Google Drive integration."""

import asyncio
import json
import logging
import time
from datetime import date, datetime, timezone
from typing import Optional

import google_auth_httplib2
import httplib2
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.core.config import settings

logger = logging.getLogger(__name__)


_FILE_CACHE_TTL = 3600  # 1 hour — audio for a given date doesn't change once uploaded
_MISS_CACHE_TTL = 300  # 5 min — file may not be uploaded yet (pipeline timing)

# Brief version → filename suffix used by NotebookLM audio output. The legacy
# brief produces `YYYYMMDD-CompassAudio.{ext}` (no suffix). The ensemble brief
# produces `YYYYMMDD-CompassAudio-Ensemble.{ext}`. Both can coexist in the same
# Drive folder.
_VERSION_FILENAME_SUFFIX = {
    "legacy": "",
    "ensemble": "-Ensemble",
}

# Content language → filename suffix. FR (default) has no suffix; the English
# (Ghana) edition appends `-EN`, e.g. `YYYYMMDD-CompassAudio-Ensemble-EN.{ext}`.
_LANGUAGE_FILENAME_SUFFIX = {
    "fr": "",
    "en": "-EN",
}


def _normalize_version(version: Optional[str]) -> str:
    if version is None or version == "":
        return settings.BRIEF_DEFAULT_VERSION
    if version not in _VERSION_FILENAME_SUFFIX:
        raise ValueError(
            f"Unknown brief version {version!r}; expected one of {list(_VERSION_FILENAME_SUFFIX)}"
        )
    return version


def _normalize_language(language: Optional[str]) -> str:
    if language is None or language == "":
        return "fr"
    if language not in _LANGUAGE_FILENAME_SUFFIX:
        raise ValueError(
            f"Unknown language {language!r}; expected one of {list(_LANGUAGE_FILENAME_SUFFIX)}"
        )
    return language


def _candidate_suffixes(version: str, language: str) -> list[str]:
    """Ordered filename-suffix candidates for a (version, language) request.

    The list is **language-consistent by construction** — an EN request only
    ever resolves to EN files, an FR request only to FR files. This is the
    load-bearing guarantee: we degrade to no-audio rather than serve one
    language's audio under another language's label (i18n decisions D3/D4).

      * EN — ensemble-only per US-4 scope. Prefer the ensemble-EN track, keep a
        bare `-EN` as a forward-compatible second choice if a legacy-EN audio is
        ever produced. Never falls back to an FR ('-Ensemble' / '') file.
      * FR — exact per-version resolution, unchanged: one candidate, no
        cross-version fallback (the two tracks stay independent).
    """
    if language == "en":
        return ["-Ensemble-EN", "-EN"]
    return [_VERSION_FILENAME_SUFFIX[version]]


class AudioService:
    """Service for handling audio files from Google Drive."""

    def __init__(self):
        """Initialize Google Drive service."""
        self.drive_service = None
        self.credentials = None
        self._file_cache: dict[str, tuple[Optional[dict], float]] = {}
        self._initialize_drive_service()

    def _initialize_drive_service(self):
        """Initialize Google Drive API service.

        Logs warnings instead of raising if env vars are missing,
        so the web app can start without Google Drive configured.
        """
        try:
            if not settings.GOOGLE_DRIVE_AUDIO_FOLDER_ID:
                logger.warning(
                    "GOOGLE_DRIVE_AUDIO_FOLDER_ID not configured — audio disabled"
                )
                return

            if not settings.GOOGLE_DRIVE_CREDENTIALS_JSON:
                logger.warning(
                    "Google Drive credentials not configured — audio disabled"
                )
                return

            credentials_dict = json.loads(settings.GOOGLE_DRIVE_CREDENTIALS_JSON)
            self.credentials = service_account.Credentials.from_service_account_info(
                credentials_dict,
                scopes=["https://www.googleapis.com/auth/drive.readonly"],
            )

            self.drive_service = build(
                "drive", "v3", credentials=self.credentials, cache_discovery=False
            )
            logger.info("Google Drive service initialized successfully")

        except Exception as e:
            logger.error("Failed to initialize Google Drive service: %s", e)
            self.drive_service = None
            self.credentials = None

    def _authorized_http(self) -> google_auth_httplib2.AuthorizedHttp:
        """Build a fresh, single-use HTTP transport for one Drive call.

        google-api-python-client rides on httplib2, whose ``Http`` object keeps
        TLS connections alive on the service instance for the whole process
        lifetime and is not thread-safe. Because audio lookups are cache-gated
        (rare, long-idle), Google closes the idle keep-alive socket; the next
        reuse reads EOF → ``SSL: UNEXPECTED_EOF_WHILE_READING``. Handing each
        ``execute()`` its own ``Http`` removes both the stale reuse and the
        cross-thread sharing (calls run in ``asyncio.to_thread``).
        """
        return google_auth_httplib2.AuthorizedHttp(
            self.credentials, http=httplib2.Http(timeout=30)
        )

    async def get_audio_metadata(
        self,
        target_date: Optional[date] = None,
        version: Optional[str] = None,
        language: Optional[str] = None,
    ) -> Optional[dict]:
        """Get metadata for audio file including URL and title.

        ``version`` selects which brief track's audio to fetch:
          - ``"legacy"`` (default from settings): ``YYYYMMDD-CompassAudio.{ext}``
          - ``"ensemble"``: ``YYYYMMDD-CompassAudio-Ensemble.{ext}``
        If ``version`` is None, falls back to ``settings.BRIEF_DEFAULT_VERSION``.

        ``language`` selects the edition (``"fr"`` default | ``"en"``). The EN
        edition is ensemble-only and resolves to ``-Ensemble-EN`` files; it
        never falls back to an FR audio (see ``_candidate_suffixes``).
        """
        resolved_version = _normalize_version(version)
        resolved_language = _normalize_language(language)
        result = await self.get_audio_file_info(
            target_date, version=resolved_version, language=resolved_language
        )

        if not result:
            return None

        display_date = target_date if target_date else datetime.now(timezone.utc).date()

        # Label from the resolved filename (accurate even when the EN edition
        # served an ensemble file under a legacy default version).
        version_label = "Ensemble" if "-Ensemble" in result["filename"] else ""
        title_suffix = f" ({version_label})" if version_label else ""
        return {
            "url": result["url"],
            "title": (
                f"Compass Bulletin{title_suffix} - {display_date.strftime('%B %d, %Y')}"
            ),
            "date": display_date.isoformat(),
            "filename": result["filename"],
            "version": resolved_version,
            "language": resolved_language,
        }

    async def get_audio_file_info(
        self,
        target_date: Optional[date] = None,
        version: Optional[str] = None,
        language: Optional[str] = None,
    ) -> Optional[dict]:
        """Get audio file info including URL and filename.

        ``version`` is the brief track to fetch (``legacy`` or ``ensemble``),
        defaulting to ``settings.BRIEF_DEFAULT_VERSION``. ``language`` is the
        edition (``fr`` default | ``en``). The cache is keyed on
        ``(date, version, language)`` so every track/edition coexists.

        Resolution walks the language-consistent candidate list (see
        ``_candidate_suffixes``) in preference order and returns the first file
        present on Drive — never an out-of-language file.

        Returns dict with url and filename, or None if not found.
        """
        if not self.drive_service:
            logger.error("Google Drive service not initialized")
            return None

        if target_date is None:
            target_date = datetime.now(timezone.utc).date()

        resolved_version = _normalize_version(version)
        resolved_language = _normalize_language(language)

        cache_key = (
            f"{target_date.isoformat()}::{resolved_version}::{resolved_language}"
        )
        cached = self._file_cache.get(cache_key)
        if cached is not None:
            result, cached_at = cached
            ttl = _FILE_CACHE_TTL if result is not None else _MISS_CACHE_TTL
            if time.monotonic() - cached_at < ttl:
                return result
            del self._file_cache[cache_key]

        stem = target_date.strftime("%Y%m%d")
        # Ordered, language-consistent candidate bases (preference first).
        candidate_bases = [
            f"{stem}-CompassAudio{suffix}"
            for suffix in _candidate_suffixes(resolved_version, resolved_language)
        ]

        try:
            name_clauses = " or ".join(
                f"name='{base}.{ext}'"
                for base in candidate_bases
                for ext in ("wav", "m4a", "mp4")
            )
            query = (
                f"({name_clauses}) and "
                f"(mimeType='audio/wav' or mimeType='audio/x-wav' or mimeType='audio/x-m4a' or mimeType='audio/mp4' or mimeType='audio/mpeg' or mimeType='video/mp4') and "
                f"trashed=false and "
                f"'{settings.GOOGLE_DRIVE_AUDIO_FOLDER_ID}' in parents"
            )

            # Run sync Google API in thread to avoid blocking event loop.
            # A fresh per-call Http (see _authorized_http) prevents reusing a
            # stale keep-alive socket; num_retries=3 still covers transient
            # 5xx/network blips via the SDK's exponential backoff.
            request = self.drive_service.files().list(
                q=query,
                fields="files(id, name, mimeType)",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            response = await asyncio.to_thread(
                request.execute, num_retries=3, http=self._authorized_http()
            )

            files = response.get("files", [])

            if not files:
                logger.warning(
                    "Audio file not found for any candidate: %s",
                    ", ".join(candidate_bases),
                )
                self._file_cache[cache_key] = (None, time.monotonic())
                return None

            # Pick by preference order — the first candidate base with a file on
            # Drive wins (ensemble-EN before a bare -EN, etc.).
            by_stem: dict[str, dict] = {}
            for f in files:
                name = f.get("name", "")
                stem_only = name.rsplit(".", 1)[0]
                by_stem.setdefault(stem_only, f)

            file = next(
                (by_stem[base] for base in candidate_bases if base in by_stem),
                files[0],
            )
            file_id = file.get("id")
            actual_filename = file.get("name")

            logger.info("Found audio file: %s", actual_filename)

            audio_url = f"https://drive.google.com/uc?id={file_id}&export=download"
            result = {"url": audio_url, "filename": actual_filename}
            self._file_cache[cache_key] = (result, time.monotonic())

            return result

        except HttpError as e:
            if e.resp and e.resp.status in (404,):
                logger.warning("Audio file not found (Drive 404): %s", e)
                self._file_cache[cache_key] = (None, time.monotonic())
                return None
            # 403, 429, 500, etc. = service issue, not "file missing"
            logger.error(
                "Google Drive API error (status=%s): %s",
                getattr(e.resp, "status", "?"),
                e,
            )
            raise
        except Exception as e:
            logger.error("Unexpected error retrieving audio file: %s", e)
            raise


# Lazy singleton — won't crash if env vars are missing at import time
_audio_service: Optional[AudioService] = None


def get_audio_service() -> AudioService:
    """Get or create the AudioService singleton."""
    global _audio_service
    if _audio_service is None:
        _audio_service = AudioService()
    return _audio_service
