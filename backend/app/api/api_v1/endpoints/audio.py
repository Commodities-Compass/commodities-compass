"""Audio API endpoints for streaming Google Drive audio files."""

import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.services.audio_service import get_audio_service

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/stream")
async def stream_audio(
    target_date: Optional[str] = Query(
        default=None,
        description="Specific date for audio file (YYYY-MM-DD format)",
    ),
):
    """Stream audio file from Google Drive through backend proxy.

    Streams without buffering the entire file in memory.
    """
    try:
        parsed_date = None
        if target_date:
            try:
                parsed_date = datetime.strptime(target_date, "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid date format. Use YYYY-MM-DD",
                )

        service = get_audio_service()
        result = await service.get_audio_file_info(parsed_date)

        if not result:
            date_str = (
                parsed_date.strftime("%Y-%m-%d")
                if parsed_date
                else datetime.now(timezone.utc).strftime("%Y-%m-%d")
            )
            filename_base = (
                f"{(parsed_date or datetime.now(timezone.utc).date()).strftime('%Y%m%d')}"
                "-CompassAudio"
            )
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Audio file not found for date {date_str}. "
                    f"Looking for: {filename_base}.wav, "
                    f"{filename_base}.m4a, or {filename_base}.mp4"
                ),
            )

        file_url = result["url"]

        # Ensure we have a proper download URL
        if "uc?id=" not in file_url or "export=download" not in file_url:
            if "/d/" in file_url:
                file_id = file_url.split("/d/")[1].split("/")[0]
                file_url = f"https://drive.google.com/uc?id={file_id}&export=download"
            else:
                raise HTTPException(
                    status_code=500,
                    detail="Unable to generate download URL",
                )

        filename = result["filename"]
        if filename.endswith(".wav"):
            content_type = "audio/wav"
        elif filename.endswith((".m4a", ".mp4")):
            content_type = "audio/mp4"
        else:
            content_type = "audio/mpeg"

        # True streaming: don't buffer entire file in memory
        client = httpx.AsyncClient(timeout=30.0)
        request = client.build_request("GET", file_url)
        response = await client.send(request, stream=True, follow_redirects=True)

        if response.status_code >= 400:
            await response.aclose()
            await client.aclose()
            raise HTTPException(
                status_code=502,
                detail=(
                    "Failed to fetch audio from Google Drive: "
                    f"{response.status_code}"
                ),
            )

        content_length = response.headers.get("content-length")
        headers: dict[str, str] = {
            "Accept-Ranges": "bytes",
            "Content-Disposition": f'inline; filename="{filename}"',
            "Cache-Control": "public, max-age=3600",
        }
        if content_length:
            headers["Content-Length"] = content_length

        async def generate():
            try:
                async for chunk in response.aiter_bytes(chunk_size=8192):
                    yield chunk
            finally:
                await response.aclose()
                await client.aclose()

        return StreamingResponse(
            generate(),
            media_type=content_type,
            headers=headers,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error streaming audio file: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/info")
async def get_audio_info(
    target_date: Optional[str] = Query(
        default=None,
        description="Specific date for audio file (YYYY-MM-DD format)",
    ),
):
    """Get audio file information without streaming."""
    try:
        parsed_date = None
        if target_date:
            try:
                parsed_date = datetime.strptime(target_date, "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid date format. Use YYYY-MM-DD",
                )

        service = get_audio_service()
        audio_metadata = await service.get_audio_metadata(parsed_date)

        if not audio_metadata:
            date_str = (
                parsed_date.strftime("%Y-%m-%d")
                if parsed_date
                else datetime.now(timezone.utc).strftime("%Y-%m-%d")
            )
            filename_base = (
                f"{(parsed_date or datetime.now(timezone.utc).date()).strftime('%Y%m%d')}"
                "-CompassAudio"
            )
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Audio file not found for date {date_str}. "
                    f"Looking for: {filename_base}.wav, "
                    f"{filename_base}.m4a, or {filename_base}.mp4"
                ),
            )

        stream_url = "/v1/audio/stream"
        if target_date:
            stream_url += f"?target_date={target_date}"

        return {
            "url": stream_url,
            "title": audio_metadata["title"],
            "date": audio_metadata["date"],
            "filename": audio_metadata["filename"],
            "google_drive_url": audio_metadata["url"],
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error getting audio info: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")
