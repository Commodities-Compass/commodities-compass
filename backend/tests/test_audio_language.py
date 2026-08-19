"""US-4b — audio language dimension.

The load-bearing guarantee: an EN request only ever resolves to EN files. We
degrade to no-audio rather than serve one language's audio under another
language's label (i18n decisions D3/D4). The EN edition is ensemble-only, so an
EN request prefers the ensemble-EN track regardless of the version param.
"""

from __future__ import annotations

import asyncio
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.audio_service import (
    AudioService,
    _candidate_suffixes,
    _normalize_language,
)


def _service() -> tuple[AudioService, MagicMock]:
    service = AudioService.__new__(AudioService)
    service.credentials = MagicMock()
    service._file_cache = {}
    drive = MagicMock()
    service.drive_service = drive
    return service, drive


def _drive_files(*names: str) -> list[dict]:
    return [
        {"id": str(i), "name": name, "mimeType": "audio/mp4"}
        for i, name in enumerate(names)
    ]


# ── Pure helpers ───────────────────────────────────────────────────────────
class TestNormalizeLanguage:
    def test_defaults_to_fr(self):
        assert _normalize_language(None) == "fr"
        assert _normalize_language("") == "fr"

    def test_known_language(self):
        assert _normalize_language("en") == "en"

    def test_unknown_raises(self):
        with pytest.raises(ValueError):
            _normalize_language("de")


class TestCandidateSuffixes:
    def test_english_follows_the_served_version(self):
        # EN used to hardcode the ensemble track, so every version served
        # ensemble audio. With a third track that would ship the wrong brief:
        # the suffix now follows the version, with a bare -EN as last resort
        # and never an FR ('' / '-Ensemble') suffix.
        assert _candidate_suffixes("ensemble", "en") == ["-Ensemble-EN", "-EN"]
        assert _candidate_suffixes("regime", "en") == ["-Regime-EN", "-EN"]
        # legacy's version suffix is empty, so both candidates collapse to one.
        assert _candidate_suffixes("legacy", "en") == ["-EN"]

    def test_english_never_falls_back_to_a_french_file(self):
        for version in ("legacy", "ensemble", "regime"):
            assert "" not in _candidate_suffixes(version, "en")
            assert "-Ensemble" not in _candidate_suffixes(version, "en")
            assert "-Regime" not in _candidate_suffixes(version, "en")

    def test_french_is_exact_per_version(self):
        assert _candidate_suffixes("ensemble", "fr") == ["-Ensemble"]
        assert _candidate_suffixes("legacy", "fr") == [""]


# ── Resolution against a mocked Drive ──────────────────────────────────────
class TestAudioResolution:
    def test_english_prefers_ensemble_en(self):
        service, drive = _service()
        files = _drive_files(
            "20260715-CompassAudio-EN.m4a",
            "20260715-CompassAudio-Ensemble-EN.m4a",
        )
        with patch("asyncio.to_thread", new=AsyncMock(return_value={"files": files})):
            result = asyncio.run(
                service.get_audio_file_info(
                    date(2026, 7, 15), version="ensemble", language="en"
                )
            )
        assert result is not None
        assert result["filename"] == "20260715-CompassAudio-Ensemble-EN.m4a"

    def test_english_query_never_requests_french_names(self):
        service, drive = _service()
        with patch("asyncio.to_thread", new=AsyncMock(return_value={"files": []})):
            asyncio.run(
                service.get_audio_file_info(
                    date(2026, 7, 15), version="ensemble", language="en"
                )
            )
        query = drive.files.return_value.list.call_args.kwargs["q"]
        # Only EN candidate names are requested…
        assert "20260715-CompassAudio-Ensemble-EN.wav" in query
        assert "20260715-CompassAudio-EN.wav" in query
        # …never the FR ensemble/legacy names (no mislabel possible).
        assert "name='20260715-CompassAudio.wav'" not in query
        assert "name='20260715-CompassAudio-Ensemble.wav'" not in query

    def test_english_degrades_to_none_when_absent(self):
        # Only FR audio exists on Drive → the EN request finds nothing (the
        # query never asked for FR) → None, so the player shows no audio rather
        # than an FR track under the EN label.
        service, drive = _service()
        with patch("asyncio.to_thread", new=AsyncMock(return_value={"files": []})):
            result = asyncio.run(
                service.get_audio_file_info(
                    date(2026, 7, 15), version="ensemble", language="en"
                )
            )
        assert result is None

    def test_french_ensemble_unchanged(self):
        service, drive = _service()
        files = _drive_files("20260715-CompassAudio-Ensemble.m4a")
        with patch("asyncio.to_thread", new=AsyncMock(return_value={"files": files})):
            result = asyncio.run(
                service.get_audio_file_info(
                    date(2026, 7, 15), version="ensemble", language="fr"
                )
            )
        query = drive.files.return_value.list.call_args.kwargs["q"]
        assert result is not None
        assert result["filename"] == "20260715-CompassAudio-Ensemble.m4a"
        assert "-EN" not in query

    def test_metadata_reports_language_and_label(self):
        service, drive = _service()
        files = _drive_files("20260715-CompassAudio-Ensemble-EN.m4a")
        with patch("asyncio.to_thread", new=AsyncMock(return_value={"files": files})):
            meta = asyncio.run(
                service.get_audio_metadata(
                    date(2026, 7, 15), version="ensemble", language="en"
                )
            )
        assert meta is not None
        assert meta["language"] == "en"
        assert "(Ensemble)" in meta["title"]  # label derived from the filename

    def test_cache_key_separates_languages(self):
        service, drive = _service()
        fr_files = _drive_files("20260715-CompassAudio-Ensemble.m4a")
        en_files = _drive_files("20260715-CompassAudio-Ensemble-EN.m4a")
        with patch(
            "asyncio.to_thread", new=AsyncMock(return_value={"files": fr_files})
        ):
            fr = asyncio.run(
                service.get_audio_file_info(
                    date(2026, 7, 15), version="ensemble", language="fr"
                )
            )
        with patch(
            "asyncio.to_thread", new=AsyncMock(return_value={"files": en_files})
        ):
            en = asyncio.run(
                service.get_audio_file_info(
                    date(2026, 7, 15), version="ensemble", language="en"
                )
            )
        assert fr is not None and en is not None
        assert fr["filename"].endswith("-Ensemble.m4a")
        assert en["filename"].endswith("-Ensemble-EN.m4a")


# ── The default version is load-bearing, not cosmetic ──────────────────────


class TestDefaultVersionIsTheServedTrack:
    """`BRIEF_DEFAULT_VERSION` must name a track that still writes files.

    Regression for the 2026-08-19 publish-gate blackout. The default was
    ``"legacy"`` — correct while legacy ran, a landmine the day it was deleted.
    The backend *service* carried `BRIEF_DEFAULT_VERSION=regime` as an env var;
    the `cc-publish-session` *job* did not, so it fell through to the default and
    looked for ``YYYYMMDD-CompassAudio.m4a`` — a file no producer writes any
    more. The gate reported ``audio=False`` all night while
    ``-CompassAudio-Regime.m4a`` sat in Drive, and the dashboard could only ever
    be released by the 09:00 morning fallback, data-only.

    Env-var parity between a service and a job is not enforced anywhere, so the
    default itself has to be right.
    """

    def test_default_resolves_to_the_regime_suffix(self) -> None:
        from app.core.config import settings
        from app.services.audio_service import (
            _VERSION_FILENAME_SUFFIX,
            _normalize_version,
        )

        resolved = _normalize_version(None)

        assert resolved == "regime"
        assert _VERSION_FILENAME_SUFFIX[resolved] == "-Regime"
        assert settings.BRIEF_DEFAULT_VERSION == "regime"

    def test_default_never_names_a_retired_track(self) -> None:
        """The check that survives the next flip.

        Whatever the default becomes, it must not be a track whose producer was
        deleted — that is the failure mode, not the specific string 'legacy'.
        """
        from app.services.audio_service import _normalize_version

        retired = {"legacy", "ensemble"}

        assert _normalize_version(None) not in retired

    def test_a_consumer_with_no_env_var_finds_the_regime_file(self) -> None:
        """End-to-end shape of the gate's lookup, with no version passed."""
        service, drive = _service()
        drive.files.return_value.list.return_value.execute.return_value = {
            "files": _drive_files("20260819-CompassAudio-Regime.m4a")
        }

        info = asyncio.run(service.get_audio_file_info(date(2026, 8, 19)))

        assert info is not None
        assert info["filename"] == "20260819-CompassAudio-Regime.m4a"
