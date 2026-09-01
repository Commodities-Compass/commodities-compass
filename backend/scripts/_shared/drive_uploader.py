"""Google Drive uploader for the Compass Brief generator.

Uploads the generated .txt brief to a dedicated Drive folder.
Idempotent: updates existing file if same filename already exists.
"""

import json
import logging

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload

from scripts._shared.drive_config import SCOPES_DRIVE

logger = logging.getLogger(__name__)

# Briefs are kilobytes, episodes are tens of megabytes.
_RESUMABLE_THRESHOLD_BYTES = 5_000_000


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
        return self.upload_bytes(
            content.encode("utf-8"), filename, "text/plain", folder_id
        )

    def upload_bytes(
        self, data: bytes, filename: str, mimetype: str, folder_id: str
    ) -> str:
        """Upload binary content to a Drive folder. Returns file ID.

        Same idempotence as the text path: a file of the same name in the same
        folder is updated in place, so re-running a job never leaves two
        episodes for one session.
        """
        # Resumable above a few megabytes: a single-shot PUT of a 16 MB episode
        # times out on the socket, where a 3 KB brief never does. Found the
        # first time the merged job tried to upload real audio.
        resumable = len(data) > _RESUMABLE_THRESHOLD_BYTES
        media = MediaInMemoryUpload(data, mimetype=mimetype, resumable=resumable)

        existing_id = self._find_file(filename, folder_id)
        if existing_id:
            logger.info("Updating existing file %s (id=%s)", filename, existing_id)
            request = self.service.files().update(
                fileId=existing_id,
                media_body=media,
                fields="id",
                supportsAllDrives=True,
            )
            return self._run(request, resumable, filename)["id"]

        metadata = {
            "name": filename,
            "parents": [folder_id],
        }
        request = self.service.files().create(
            body=metadata,
            media_body=media,
            fields="id",
            supportsAllDrives=True,
        )
        file_id = self._run(request, resumable, filename)["id"]
        logger.info("Created %s (id=%s)", filename, file_id)
        return file_id

    def _run(self, request, resumable: bool, filename: str) -> dict:  # noqa: ANN001
        """Execute an upload, chunk by chunk when the payload warrants it."""
        if not resumable:
            return request.execute()
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                logger.info(
                    "  %s: %d%% uploaded", filename, int(status.progress() * 100)
                )
        return response

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
