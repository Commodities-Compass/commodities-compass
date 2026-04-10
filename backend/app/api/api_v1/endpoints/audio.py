"""Audio API endpoints for streaming Google Drive audio files."""

import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.services.audio_service import get_audio_service

router = APIRouter()
logger = logging.getLogger(__name__)


def _resolve_date(target_date: Optional[str]) -> Optional["datetime.date"]:
    if not target_date:
        return None
    try:
        return datetime.strptime(target_date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid date format. Use YYYY-MM-DD"
        )


def _resolve_file_url(url: str) -> str:
    if "uc?id=" in url and "export=download" in url:
        return url
    if "/d/" in url:
        file_id = url.split("/d/")[1].split("/")[0]
        return f"https://drive.google.com/uc?id={file_id}&export=download"
    raise HTTPException(status_code=500, detail="Unable to generate download URL")


def _content_type(filename: str) -> str:
    if filename.endswith(".wav"):
        return "audio/wav"
    if filename.endswith((".m4a", ".mp4")):
        return "audio/mp4"
    return "audio/mpeg"


async def _fetch_audio_info(parsed_date: Optional["datetime.date"]) -> dict:
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
    return result


@router.get("/stream")
async def stream_audio(
    request: Request,
    target_date: Optional[str] = Query(
        default=None,
        description="Specific date for audio file (YYYY-MM-DD format)",
    ),
):
    """Stream audio file from Google Drive through backend proxy.

    Supports HTTP Range requests (required by iOS Safari for audio playback).
    """
    try:
        parsed_date = _resolve_date(target_date)
        result = await _fetch_audio_info(parsed_date)
        file_url = _resolve_file_url(result["url"])
        filename = result["filename"]
        media_type = _content_type(filename)

        # First: HEAD request to get total file size (needed for Range support)
        async with httpx.AsyncClient(
            timeout=30.0, follow_redirects=True
        ) as head_client:
            head_resp = await head_client.head(file_url)
            total_size = int(head_resp.headers.get("content-length", 0))

        if not total_size:
            # Fallback: full stream without Range support
            client = httpx.AsyncClient(timeout=30.0)
            req = client.build_request("GET", file_url)
            response = await client.send(req, stream=True, follow_redirects=True)
            if response.status_code >= 400:
                await response.aclose()
                await client.aclose()
                raise HTTPException(
                    status_code=502, detail="Failed to fetch audio from Google Drive"
                )

            async def generate():
                try:
                    async for chunk in response.aiter_bytes(chunk_size=8192):
                        yield chunk
                finally:
                    await response.aclose()
                    await client.aclose()

            return StreamingResponse(
                generate(),
                media_type=media_type,
                headers={
                    "Accept-Ranges": "bytes",
                    "Content-Disposition": f'inline; filename="{filename}"',
                    "Cache-Control": "public, max-age=3600",
                },
            )

        # Parse Range header
        range_header = request.headers.get("range")
        if range_header:
            range_spec = range_header.replace("bytes=", "")
            parts = range_spec.split("-")
            start = int(parts[0]) if parts[0] else 0
            end = int(parts[1]) if parts[1] else total_size - 1
            end = min(end, total_size - 1)
            content_length = end - start + 1

            client = httpx.AsyncClient(timeout=30.0)
            req = client.build_request(
                "GET", file_url, headers={"Range": f"bytes={start}-{end}"}
            )
            response = await client.send(req, stream=True, follow_redirects=True)

            async def generate_range():
                try:
                    async for chunk in response.aiter_bytes(chunk_size=8192):
                        yield chunk
                finally:
                    await response.aclose()
                    await client.aclose()

            return StreamingResponse(
                generate_range(),
                status_code=206,
                media_type=media_type,
                headers={
                    "Accept-Ranges": "bytes",
                    "Content-Range": f"bytes {start}-{end}/{total_size}",
                    "Content-Length": str(content_length),
                    "Content-Disposition": f'inline; filename="{filename}"',
                    "Cache-Control": "public, max-age=3600",
                },
            )

        # No Range header: full stream with Content-Length
        client = httpx.AsyncClient(timeout=30.0)
        req = client.build_request("GET", file_url)
        response = await client.send(req, stream=True, follow_redirects=True)

        if response.status_code >= 400:
            await response.aclose()
            await client.aclose()
            raise HTTPException(
                status_code=502, detail="Failed to fetch audio from Google Drive"
            )

        async def generate_full():
            try:
                async for chunk in response.aiter_bytes(chunk_size=8192):
                    yield chunk
            finally:
                await response.aclose()
                await client.aclose()

        return StreamingResponse(
            generate_full(),
            media_type=media_type,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(total_size),
                "Content-Disposition": f'inline; filename="{filename}"',
                "Cache-Control": "public, max-age=3600",
            },
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
