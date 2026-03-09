"""Audio service for Google Drive integration."""

import asyncio
import json
import logging
from datetime import date, datetime
from typing import Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.core.config import settings
from app.utils.date_utils import get_business_date

logger = logging.getLogger(__name__)


class AudioService:
    """Service for handling audio files from Google Drive."""

    def __init__(self):
        """Initialize Google Drive service."""
        self.drive_service = None
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
            credentials = service_account.Credentials.from_service_account_info(
                credentials_dict,
                scopes=["https://www.googleapis.com/auth/drive.readonly"],
            )

            self.drive_service = build("drive", "v3", credentials=credentials)
            logger.info("Google Drive service initialized successfully")

        except Exception as e:
            logger.error("Failed to initialize Google Drive service: %s", e)
            self.drive_service = None

    async def get_audio_metadata(
        self, target_date: Optional[date] = None
    ) -> Optional[dict]:
        """Get metadata for audio file including URL and title."""
        result = await self.get_audio_file_info(target_date)

        if not result:
            return None

        display_date = target_date if target_date else datetime.now().date()

        return {
            "url": result["url"],
            "title": f"Compass Bulletin - {display_date.strftime('%B %d, %Y')}",
            "date": display_date.isoformat(),
            "filename": result["filename"],
        }

    async def get_audio_file_info(
        self, target_date: Optional[date] = None
    ) -> Optional[dict]:
        """Get audio file info including URL and filename.

        Returns dict with url and filename, or None if not found.
        """
        if not self.drive_service:
            logger.error("Google Drive service not initialized")
            return None

        if target_date is None:
            target_date = datetime.now().date()

        business_date = get_business_date(target_date)
        if business_date != target_date:
            logger.info(
                "Weekend date %s converted to %s for audio lookup",
                target_date,
                business_date,
            )

        filename_base = f"{business_date.strftime('%Y%m%d')}-CompassAudio"

        try:
            query = (
                f"(name='{filename_base}.wav' or name='{filename_base}.m4a' or name='{filename_base}.mp4') and "
                f"(mimeType='audio/wav' or mimeType='audio/x-wav' or mimeType='audio/x-m4a' or mimeType='audio/mp4' or mimeType='audio/mpeg' or mimeType='video/mp4') and "
                f"trashed=false and "
                f"'{settings.GOOGLE_DRIVE_AUDIO_FOLDER_ID}' in parents"
            )

            # Run sync Google API in thread to avoid blocking event loop
            request = self.drive_service.files().list(
                q=query,
                fields="files(id, name, mimeType)",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            response = await asyncio.to_thread(request.execute)

            files = response.get("files", [])

            if not files:
                logger.warning(
                    "Audio file not found: %s.wav, %s.m4a, or %s.mp4",
                    filename_base,
                    filename_base,
                    filename_base,
                )
                return None

            file = files[0]
            file_id = file.get("id")
            actual_filename = file.get("name")

            logger.info("Found audio file: %s", actual_filename)

            audio_url = f"https://drive.google.com/uc?id={file_id}&export=download"

            return {"url": audio_url, "filename": actual_filename}

        except HttpError as e:
            logger.error("Google Drive API error: %s", e)
            return None
        except Exception as e:
            logger.error("Unexpected error retrieving audio file: %s", e)
            return None


# Lazy singleton — won't crash if env vars are missing at import time
_audio_service: Optional[AudioService] = None


def get_audio_service() -> AudioService:
    """Get or create the AudioService singleton."""
    global _audio_service
    if _audio_service is None:
        _audio_service = AudioService()
    return _audio_service
