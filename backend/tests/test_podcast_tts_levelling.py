"""Chunk levelling must never make an episode worse than leaving it alone.

Every call is an independent generation with its own ±26 % variance, so a
`speakingRate` factor is applied *on top of a fresh roll of the dice* rather
than to the audio it was computed from. Observed in production 2026-09-02: a
chunk 9 % above the median came back 13 % below it.
"""

from __future__ import annotations

import io
import json
import wave
from unittest.mock import patch

import pytest

from scripts.podcast_audio.script_writer import PodcastScript, Turn
from scripts.podcast_audio.tts.base import (
    PAYLOAD_BUDGET_BYTES,
    SEAM_AFTER_CHARS,
    chunk_turns,
    duration_seconds,
    splice,
)
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


class TestSeamsAndSilence:
    """Where the seams fall, and the silence held at each one.

    Origin 2026-09-14: Hedi listened and said the episode still lacked breath.
    It had none — `splice` wrote each chunk's PCM frames straight after the
    previous one, so the only pauses were whatever Gemini produced inside a
    chunk. We cannot ask for them either: SynthesisInput takes text OR ssml OR
    multi-speaker markup, and two voices force the markup, so `<break>` is
    structurally unavailable. The silence is manufactured here or nowhere.
    """

    @staticmethod
    def _wav(seconds: float, framerate: int = 24000) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(framerate)
            w.writeframes(b"\x01\x00" * int(framerate * seconds))
        return buf.getvalue()

    def test_silence_is_held_between_parts_but_never_at_the_edges(self):
        joined = splice([self._wav(1.0), self._wav(1.0)], gap_ms=500)

        # 2 s of speech + exactly one 500 ms seam — no leading or trailing pad.
        assert duration_seconds(joined) == pytest.approx(2.5, abs=0.01)

    def test_a_zero_gap_restores_the_butt_splice(self):
        joined = splice([self._wav(1.0), self._wav(1.0)], gap_ms=0)

        assert duration_seconds(joined) == pytest.approx(2.0, abs=0.01)

    def test_a_single_part_is_returned_unpadded(self):
        assert duration_seconds(splice([self._wav(1.0)])) == pytest.approx(
            1.0, abs=0.01
        )

    def test_the_seam_lands_after_a_developed_turn_not_mid_exchange(self):
        """A pause is only a breath if it falls where a person would take one."""
        short = {"speaker": "Ana", "text": "Ah oui ?"}
        long = {"speaker": "Marc", "text": "x" * 400}
        groups = chunk_turns([short, long] * 6)

        assert len(groups) > 1
        for group in groups[:-1]:
            assert len(group[-1]["text"]) >= SEAM_AFTER_CHARS

    def test_no_chunk_exceeds_the_hard_payload_cap(self):
        turns = [{"speaker": "Ana", "text": "y" * 300} for _ in range(40)]

        for group in chunk_turns(turns):
            payload = json.dumps([t["text"] for t in group]).encode()
            assert len(payload) <= PAYLOAD_BUDGET_BYTES
