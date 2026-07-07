"""Unit tests for the cc-publish-session decision logic.

The DB/audio/calendar lookups are mocked; these lock the release/skip rules:
  * complete + audio           → release (has_audio=True)
  * complete, no audio, early  → skip (wait for audio)
  * no audio, past 9am deadline→ release (morning fallback, has_audio=False)
  * partial data, past deadline→ release (fallback tolerates degraded sections)
  * --force                    → release now, audio-agnostic
  * no indicator row           → skip (dashboard would error)
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

import scripts.publish_session.main as pub
from scripts.publish_session.main import Decision, _decide

T = date(2026, 7, 6)  # Monday session
NOW = datetime(2026, 7, 7, 3, 0, tzinfo=timezone.utc)  # Tue 03:00 UTC (pre-9am)
DEADLINE = datetime(2026, 7, 7, 9, 0, tzinfo=timezone.utc)  # Tue 09:00 UTC


def _patch(monkeypatch, *, core=True, press=True, meteo=True, audio=True):
    monkeypatch.setattr(pub, "_completeness", lambda s, d: (core, press, meteo))
    monkeypatch.setattr(pub, "_has_audio", lambda d: audio)
    monkeypatch.setattr(pub, "_fallback_deadline", lambda d: DEADLINE)


@pytest.mark.unit
def test_complete_plus_audio_releases(monkeypatch):
    _patch(monkeypatch, audio=True)
    d = _decide(None, T, NOW, force=False)
    assert d == Decision(T, "release", True, "complete+audio")


@pytest.mark.unit
def test_complete_no_audio_before_deadline_skips(monkeypatch):
    _patch(monkeypatch, audio=False)
    d = _decide(None, T, NOW, force=False)  # NOW < DEADLINE
    assert d.action == "skip"
    assert d.has_audio is False


@pytest.mark.unit
def test_no_audio_past_deadline_falls_back(monkeypatch):
    _patch(monkeypatch, audio=False)
    past = DEADLINE  # exactly at 09:00 → fallback fires
    d = _decide(None, T, past, force=False)
    assert d.action == "release"
    assert d.has_audio is False
    assert "fallback" in d.reason


@pytest.mark.unit
def test_partial_data_past_deadline_still_releases(monkeypatch):
    # press missing → not fully complete → no same-evening release, but the
    # morning fallback tolerates degraded sections (dashboard degrades).
    _patch(monkeypatch, press=False, audio=False)
    d = _decide(None, T, DEADLINE, force=False)
    assert d.action == "release"
    assert "fallback" in d.reason


@pytest.mark.unit
def test_partial_data_before_deadline_skips(monkeypatch):
    _patch(monkeypatch, meteo=False, audio=True)  # audio present but meteo missing
    d = _decide(None, T, NOW, force=False)
    assert d.action == "skip"  # not fully complete, not past deadline


@pytest.mark.unit
def test_force_releases_regardless(monkeypatch):
    _patch(monkeypatch, press=False, meteo=False, audio=False)
    d = _decide(None, T, NOW, force=True)
    assert d.action == "release"
    assert d.reason == "manual --force"


@pytest.mark.unit
def test_no_indicator_row_skips(monkeypatch):
    _patch(monkeypatch, core=False, audio=True)
    d = _decide(None, T, DEADLINE, force=True)  # even --force can't publish
    assert d.action == "skip"
    assert "indicator" in d.reason
