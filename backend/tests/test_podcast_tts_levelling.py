"""Chunk levelling must never make an episode worse than leaving it alone.

Every call is an independent generation with its own ±26 % variance, so a
`speakingRate` factor is applied *on top of a fresh roll of the dice* rather
than to the audio it was computed from. Observed in production 2026-09-02: a
chunk 9 % above the median came back 13 % below it.
"""

from __future__ import annotations

import io
import wave
from unittest.mock import patch

from scripts.podcast_audio.script_writer import PodcastScript, Turn
from scripts.podcast_audio.tts.base import duration_seconds
from scripts.podcast_audio.tts.gemini import GeminiSynthesizer

_RATE = 24000


def _wav(seconds: float) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(_RATE)
        writer.writeframes(b"\x00\x00" * int(seconds * _RATE))
    return buffer.getvalue()


def _script(turns_text: list[str]) -> PodcastScript:
    return PodcastScript(
        language="fr",
        turns=tuple(
            Turn("Ana" if i % 2 == 0 else "Marc", t) for i, t in enumerate(turns_text)
        ),
    )


def _synth_with(durations: list[float]) -> tuple[bytes, list[float]]:
    """Run the synthesiser against a scripted sequence of call durations."""
    calls: list[float] = []
    synth = GeminiSynthesizer.__new__(GeminiSynthesizer)

    def fake_call(turns, language, rate):  # noqa: ANN001, ARG001
        seconds = durations[len(calls)]
        calls.append(seconds)
        return _wav(seconds)

    with patch.object(GeminiSynthesizer, "_call", side_effect=fake_call):
        audio = synth.synthesize(_script(["a" * 1900, "b" * 1900, "c" * 1900]))
    return audio, calls


class TestLevellingNeverDegrades:
    def test_a_correction_that_overshoots_is_discarded(self):
        # Three chunks of 1900 chars, one turn each. Chunk 1 is fast (85 s ->
        # 22.4 chars/s), the others sit at 100 s (19.0). Median 19.0, chunk 1
        # drifts 17.6 % — over tolerance, so a correction is attempted and comes
        # back at 130 s (14.6), further from the median than the 85 s original.
        audio, calls = _synth_with([85.0, 100.0, 100.0, 130.0])
        assert len(calls) == 4, "one correction attempted"
        # 85 + 100 + 100 = 285 if the original was kept; 330 if not.
        assert abs(duration_seconds(audio) - 285.0) < 1.0, (
            "the worse correction must be discarded"
        )

    def test_a_correction_that_helps_is_kept(self):
        # Same drift, but the correction lands at 98 s — closer to the median
        # than the 85 s original.
        audio, calls = _synth_with([85.0, 100.0, 100.0, 98.0])
        assert len(calls) == 4
        assert abs(duration_seconds(audio) - 298.0) < 1.0, (
            "a correction that helps must be kept"
        )

    def test_chunks_within_tolerance_are_never_re_synthesised(self):
        audio, calls = _synth_with([100.0, 100.0, 100.0])
        assert len(calls) == 3, "no correction, no extra spend"
        assert abs(duration_seconds(audio) - 300.0) < 1.0
