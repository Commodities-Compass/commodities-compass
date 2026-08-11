"""Tests for the /audio/stream signed capability token (podcast hard boundary)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.core import audio_signing as sign
from app.core.config import settings

V1 = settings.API_V1_STR
STREAM = f"{V1}/audio/stream"


@pytest.fixture
def secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "AUDIO_URL_SECRET", "unit-test-secret")


@pytest.fixture
def enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENTITLEMENTS_ENFORCED", True)
    monkeypatch.setattr(settings, "AUDIO_URL_SECRET", "unit-test-secret")


# --------------------------------------------------------------------------- #
# Unit — signer
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_sign_verify_roundtrip(secret) -> None:
    tok = sign.sign_stream_token("2026-08-03", "ensemble", "")
    assert sign.verify_stream_token(tok, "2026-08-03", "ensemble", "")


@pytest.mark.unit
def test_verify_rejects_field_mismatch(secret) -> None:
    tok = sign.sign_stream_token("2026-08-03", "ensemble", "")
    assert not sign.verify_stream_token(tok, "2026-08-04", "ensemble", "")  # date
    assert not sign.verify_stream_token(tok, "2026-08-03", "legacy", "")  # version
    assert not sign.verify_stream_token(tok, "2026-08-03", "ensemble", "en")  # lang


@pytest.mark.unit
def test_verify_rejects_tamper(secret) -> None:
    tok = sign.sign_stream_token("2026-08-03", "ensemble", "")
    body, _, sig = tok.partition(".")
    assert not sign.verify_stream_token(f"{body}.deadbeef", "2026-08-03", "ensemble", "")


@pytest.mark.unit
def test_verify_rejects_expired(secret) -> None:
    tok = sign.sign_stream_token("2026-08-03", "ensemble", "", ttl_seconds=-10)
    assert not sign.verify_stream_token(tok, "2026-08-03", "ensemble", "")


@pytest.mark.unit
def test_verify_false_without_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "AUDIO_URL_SECRET", "")
    assert not sign.verify_stream_token("anything.sig", "2026-08-03", "ensemble", "")


# --------------------------------------------------------------------------- #
# Integration — the unauthenticated stream gate (short-circuits before Drive)
# --------------------------------------------------------------------------- #
@pytest.mark.integration
@pytest.mark.asyncio
async def test_stream_denies_without_token_when_enforced(
    client: AsyncClient, enforced
) -> None:
    r = await client.get(STREAM, params={"target_date": "2026-08-03"})
    assert r.status_code == 403


@pytest.mark.integration
@pytest.mark.asyncio
async def test_stream_denies_tampered_token_when_enforced(
    client: AsyncClient, enforced
) -> None:
    tok = sign.sign_stream_token("2026-08-03", "", "")
    r = await client.get(
        STREAM, params={"target_date": "2026-08-03", "token": tok + "x"}
    )
    assert r.status_code == 403
