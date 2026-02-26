"""Google Drive uploader for the Compass Brief generator.

Uploads the generated .txt brief to a dedicated Drive folder.
Idempotent: updates existing file if same filename already exists.
"""

import json
import logging

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload

from scripts.compass_brief.config import SCOPES_DRIVE

logger = logging.getLogger(__name__)


class DriveUploader:
    def __init__(self, credentials_json: str) -> None:
        creds = json.loads(credentials_json)
        self.credentials = Credentials.from_service_account_info(
            creds, scopes=SCOPES_DRIVE
        )
        self.service = build("drive", "v3", credentials=self.credentials)
        logger.info("DriveUploader initialised")

    def upload(self, content: str, filename: str, folder_id: str) -> str:
        """Upload text content to Drive folder. Returns file ID.

        If a file with the same name already exists in the folder, it is updated
        in place (no duplicates).
        """
        media = MediaInMemoryUpload(content.encode("utf-8"), mimetype="text/plain")

        existing_id = self._find_file(filename, folder_id)
        if existing_id:
            logger.info("Updating existing file %s (id=%s)", filename, existing_id)
            result = (
                self.service.files()
                .update(
                    fileId=existing_id,
                    media_body=media,
                )
                .execute()
            )
            return result["id"]

        metadata = {
            "name": filename,
            "parents": [folder_id],
        }
        result = (
            self.service.files()
            .create(
                body=metadata,
                media_body=media,
                fields="id",
                supportsAllDrives=True,
            )
            .execute()
        )
        file_id = result["id"]
        logger.info("Created %s (id=%s)", filename, file_id)
        return file_id

    def _find_file(self, filename: str, folder_id: str) -> str | None:
        query = f"name='{filename}' and trashed=false and '{folder_id}' in parents"
        response = (
            self.service.files()
            .list(
                q=query,
                fields="files(id)",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        files = response.get("files", [])
        return files[0]["id"] if files else None
