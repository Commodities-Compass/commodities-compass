"""The engine that spends nothing — the default, and what CI runs."""

from __future__ import annotations

import io
import logging
import wave

from scripts.podcast_audio.script_writer import PodcastScript

logger = logging.getLogger(__name__)

_SAMPLE_RATE = 24000


class NoopSynthesizer:
    """Returns silence of the estimated length, so the plumbing is exercised.

    Being the default matters: a misconfigured job produces a silent file that
    the publication gate will not mistake for a real episode, rather than an
    unexpected bill.
    """

    def synthesize(self, script: PodcastScript) -> bytes:
        frames = int(script.estimated_seconds * _SAMPLE_RATE)
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(_SAMPLE_RATE)
            writer.writeframes(b"\x00\x00" * frames)
        logger.warning(
            "[%s] TTS_PROVIDER=noop — %0.f seconds of silence, no audio generated",
            script.language,
            script.estimated_seconds,
        )
        return buffer.getvalue()
