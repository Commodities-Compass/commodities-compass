"""The synthesis interface, the audio plumbing, and the provider registry."""

from __future__ import annotations

import io
import json
import logging
import os
import wave
from typing import Protocol

from scripts.podcast_audio.script_writer import PodcastScript

logger = logging.getLogger(__name__)

# Gemini-TTS caps the whole payload — not the turn — at 4000 bytes. Probed
# 2026-08-26: 1 764 B passes, 4 410 B is refused. 3 500 leaves room for the
# markup around the text.
PAYLOAD_BUDGET_BYTES = 3500


class SynthesisError(RuntimeError):
    """Speech synthesis failed. No retry — see pipeline-error-handling.md."""


class SpeechSynthesizer(Protocol):
    """Turns a script into audio bytes. Implementations must not retry."""

    def synthesize(self, script: PodcastScript) -> bytes: ...


def chunk_turns(turns: list[dict[str, str]], budget: int = PAYLOAD_BUDGET_BYTES):
    """Group turns into calls that stay under the byte cap, never splitting one.

    A 5-minute episode is about 5 000 bytes, so this yields two chunks and a
    single seam — the case P0 measured.
    """
    grouped: list[list[dict[str, str]]] = []
    current: list[dict[str, str]] = []
    for turn in turns:
        trial = current + [turn]
        if current and len(json.dumps([t["text"] for t in trial]).encode()) > budget:
            grouped.append(current)
            current = [turn]
        else:
            current = trial
    if current:
        grouped.append(current)
    return grouped


def splice(parts: list[bytes]) -> bytes:
    """Join WAV payloads by writing their PCM frames under one header."""
    if not parts:
        raise SynthesisError("nothing to splice")
    out = io.BytesIO()
    params = None
    with wave.open(out, "wb") as writer:
        for part in parts:
            with wave.open(io.BytesIO(part), "rb") as reader:
                if params is None:
                    params = reader.getparams()
                    writer.setparams(params)
                writer.writeframes(reader.readframes(reader.getnframes()))
    return out.getvalue()


def duration_seconds(audio: bytes) -> float:
    with wave.open(io.BytesIO(audio), "rb") as reader:
        return reader.getnframes() / reader.getframerate()


def get_synthesizer(provider: str | None = None) -> SpeechSynthesizer:
    """Resolve the configured engine. Defaults to ``noop`` — never to spend."""
    name = (provider or os.environ.get("TTS_PROVIDER", "noop")).lower()
    if name == "gemini":
        from scripts.podcast_audio.tts.gemini import GeminiSynthesizer

        return GeminiSynthesizer()
    if name == "noop":
        from scripts.podcast_audio.tts.noop import NoopSynthesizer

        return NoopSynthesizer()
    raise SynthesisError(f"Unknown TTS_PROVIDER: {name!r} (gemini, noop)")
