"""Signed capability tokens for the unauthenticated ``/audio/stream`` endpoint.

``/audio/stream`` cannot require an ``Authorization`` header (the HTML ``<audio>``
element can't send one), so a podcast-entitled client's audio would otherwise be
fetchable by anyone who guesses the date/version. Fix = a short-lived HMAC token:

- ``/dashboard/audio`` (gated behind ``read:section:podcast``) MINTS a token bound
  to the exact ``(target_date, version, language)`` it embeds in the stream URL.
- ``/audio/stream`` REQUIRES a valid, unexpired token whose bound fields match its
  own query params — but ONLY when ``ENTITLEMENTS_ENFORCED`` is on. In dark mode
  the stream stays open (today's behavior), so this is non-breaking.

The token is a capability (proves "someone with podcast access minted this"), not a
per-user identity — sharing a short-lived URL is acceptable, matching the signed-URL
model. Secret: ``settings.AUDIO_URL_SECRET`` (required when enforcement is on).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from app.core.config import settings

_DEFAULT_TTL_SECONDS = 3600  # matches the audio cache / Cache-Control max-age


class AudioSigningError(RuntimeError):
    """Raised when signing is requested but no secret is configured (fail-loud)."""


def signing_enabled() -> bool:
    """True iff a signing secret is configured."""
    return bool(settings.AUDIO_URL_SECRET)


def _secret() -> bytes:
    if not settings.AUDIO_URL_SECRET:
        raise AudioSigningError(
            "AUDIO_URL_SECRET is not configured — required to sign audio stream "
            "URLs when ENTITLEMENTS_ENFORCED is on."
        )
    return settings.AUDIO_URL_SECRET.encode()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _canonical(target_date: str, version: str, language: str, exp: int) -> bytes:
    payload = {"d": target_date, "v": version, "l": language, "e": exp}
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def sign_stream_token(
    target_date: str,
    version: str,
    language: str,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
) -> str:
    """Return ``<body>.<sig>`` binding the resolved stream params + an expiry.

    Empty strings are the canonical "absent" value — callers must sign exactly the
    query-param values they embed in the URL (an omitted param → "").
    """
    exp = int(time.time()) + ttl_seconds
    body = _b64(_canonical(target_date, version, language, exp))
    sig = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_stream_token(
    token: str | None, target_date: str, version: str, language: str
) -> bool:
    """True iff ``token`` is a valid, unexpired signature over the given params."""
    if not token or "." not in token:
        return False
    body, _, sig = token.partition(".")
    try:
        expected = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    except AudioSigningError:
        return False
    if not hmac.compare_digest(sig, expected):
        return False
    try:
        payload = json.loads(base64.urlsafe_b64decode(body + "=="))
    except (ValueError, json.JSONDecodeError):
        return False
    if int(payload.get("e", 0)) < int(time.time()):
        return False
    return (
        payload.get("d") == target_date
        and payload.get("v") == version
        and payload.get("l") == language
    )
