"""Audio API endpoints for streaming Google Drive audio files."""

import logging
from datetime import date, datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.core.audio_signing import sign_stream_token, verify_stream_token
from app.core.config import settings
from app.core.tenancy import require_any_entitlement
from app.core.entitlements import SECTION_PODCAST
from app.services.audio_service import get_audio_service

router = APIRouter()
logger = logging.getLogger(__name__)

_ALLOWED_AUDIO_ORIGIN = "https://drive.google.com/"


def _resolve_date(target_date: Optional[str]) -> Optional[date]:
    if not target_date:
        return None
    try:
        return datetime.strptime(target_date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid date format. Use YYYY-MM-DD"
        )


def _resolve_file_url(url: str) -> str:
    if not url.startswith(_ALLOWED_AUDIO_ORIGIN):
        raise HTTPException(status_code=500, detail="Invalid audio source URL")
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


async def _fetch_audio_info(
    parsed_date: Optional[date],
    version: Optional[str] = None,
    language: Optional[str] = None,
) -> dict:
    service = get_audio_service()
    result = await service.get_audio_file_info(
        parsed_date, version=version, language=language
    )
    if not result:
        date_str = (
            parsed_date.strftime("%Y-%m-%d")
            if parsed_date
            else datetime.now(timezone.utc).strftime("%Y-%m-%d")
        )
        raise HTTPException(
            status_code=404,
            detail=(
                f"Audio file not found for date {date_str} "
                f"(version={version or 'default'}, language={language or 'fr'})."
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
    version: Optional[str] = Query(
        default=None,
        description=(
            "Brief track: 'legacy' | 'ensemble'. Default falls back to "
            "settings.BRIEF_DEFAULT_VERSION. Used by dual-track rollout."
        ),
    ),
    language: Optional[str] = Query(
        default=None,
        description=(
            "Audio edition: 'fr' (default) | 'en'. The EN edition is "
            "ensemble-only and never serves an FR audio."
        ),
    ),
    token: Optional[str] = Query(
        default=None,
        description=(
            "Signed capability token minted by /dashboard/audio. Required only "
            "when ENTITLEMENTS_ENFORCED is on (the podcast hard boundary)."
        ),
    ),
):
    """Stream audio file from Google Drive through backend proxy.

    Supports HTTP Range requests (required by iOS Safari for audio playback).
    """
    try:
        # Hard boundary: this endpoint is unauthenticated (for the <audio> element),
        # so gate it on a signed token instead of the JWT. Dark mode leaves it open.
        if settings.ENTITLEMENTS_ENFORCED and not verify_stream_token(
            token, target_date or "", version or "", language or ""
        ):
            raise HTTPException(
                status_code=403,
                detail="Missing or invalid audio access token.",
            )

        parsed_date = _resolve_date(target_date)
        result = await _fetch_audio_info(
            parsed_date, version=version, language=language
        )
        file_url = _resolve_file_url(result["url"])
        filename = result["filename"]
        media_type = _content_type(filename)

        # First: HEAD request to get total file size (needed for Range support)
        async with httpx.AsyncClient(
            timeout=30.0, follow_redirects=True
        ) as head_client:
            head_resp = await head_client.head(file_url)
            total_size = int(head_resp.headers.get("content-length", 0))

        async def _stream_drive(
            extra_headers: dict[str, str] | None = None,
        ) -> tuple[httpx.AsyncClient, httpx.Response]:
            """Open a streaming GET to Drive, checking status.

            Returns (client, response) — caller owns cleanup.
            """
            client = httpx.AsyncClient(timeout=30.0)
            try:
                req = client.build_request("GET", file_url, headers=extra_headers or {})
                response = await client.send(req, stream=True, follow_redirects=True)
                if response.status_code >= 400:
                    await response.aclose()
                    await client.aclose()
                    raise HTTPException(
                        status_code=502,
                        detail="Failed to fetch audio from Google Drive",
                    )
                return client, response
            except HTTPException:
                raise
            except Exception:
                await client.aclose()
                raise

        async def _generate(client: httpx.AsyncClient, response: httpx.Response):
            try:
                async for chunk in response.aiter_bytes(chunk_size=8192):
                    yield chunk
            finally:
                await response.aclose()
                await client.aclose()

        common_headers = {
            "Accept-Ranges": "bytes",
            "Content-Disposition": f'inline; filename="{filename}"',
            "Cache-Control": "public, max-age=3600",
        }

        if not total_size:
            # Fallback: full stream without Range support
            client, response = await _stream_drive()
            return StreamingResponse(
                _generate(client, response),
                media_type=media_type,
                headers=common_headers,
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

            client, response = await _stream_drive(
                extra_headers={"Range": f"bytes={start}-{end}"}
            )
            return StreamingResponse(
                _generate(client, response),
                status_code=206,
                media_type=media_type,
                headers={
                    **common_headers,
                    "Content-Range": f"bytes {start}-{end}/{total_size}",
                    "Content-Length": str(content_length),
                },
            )

        # No Range header: full stream with Content-Length
        client, response = await _stream_drive()
        return StreamingResponse(
            _generate(client, response),
            media_type=media_type,
            headers={**common_headers, "Content-Length": str(total_size)},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error streaming audio file: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/info",
    dependencies=[Depends(require_any_entitlement(SECTION_PODCAST))],
)
async def get_audio_info(
    target_date: Optional[str] = Query(
        default=None,
        description="Specific date for audio file (YYYY-MM-DD format)",
    ),
    version: Optional[str] = Query(
        default=None,
        description=(
            "Brief track: 'legacy' | 'ensemble'. Default falls back to "
            "settings.BRIEF_DEFAULT_VERSION. Used by dual-track rollout."
        ),
    ),
    language: Optional[str] = Query(
        default=None,
        description=(
            "Audio edition: 'fr' (default) | 'en'. The EN edition is "
            "ensemble-only and never serves an FR audio."
        ),
    ),
):
    """Get audio file information without streaming (podcast-gated)."""
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
        audio_metadata = await service.get_audio_metadata(
            parsed_date, version=version, language=language
        )

        if not audio_metadata:
            date_str = (
                parsed_date.strftime("%Y-%m-%d")
                if parsed_date
                else datetime.now(timezone.utc).strftime("%Y-%m-%d")
            )
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Audio file not found for date {date_str} "
                    f"(version={version or 'default'}, language={language or 'fr'})."
                ),
            )

        stream_url = "/v1/audio/stream"
        params = []
        if target_date:
            params.append(f"target_date={target_date}")
        if version:
            params.append(f"version={version}")
        if language:
            params.append(f"language={language}")
        if params:
            stream_url += "?" + "&".join(params)

        if settings.ENTITLEMENTS_ENFORCED:
            stream_token = sign_stream_token(
                target_date or "", version or "", language or ""
            )
            stream_url += ("&" if "?" in stream_url else "?") + f"token={stream_token}"

        return {
            "url": stream_url,
            "title": audio_metadata["title"],
            "date": audio_metadata["date"],
            "filename": audio_metadata["filename"],
            "google_drive_url": audio_metadata["url"],
            "version": audio_metadata.get("version"),
            "language": audio_metadata.get("language"),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error getting audio info: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")
