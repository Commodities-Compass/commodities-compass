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

# Where the seams land, and how long we hold them.
#
# The episode had no silence in it anywhere: `splice` wrote the PCM frames of
# each chunk back to back, so the only pauses were whatever Gemini produced
# inside a chunk. Two voices, six minutes, no room to breathe — the one thing
# Hedi still heard missing on 2026-09-14.
#
# We cannot ask for the pauses. `SynthesisInput` takes text OR ssml OR
# multi-speaker markup, and two voices force the markup, so `<break time=…>`
# is structurally unavailable. A style hint in the prompt is dropped about a
# third of the time (see speech_text). So the silence is manufactured here,
# deterministically, and it is the only lever that always works.
#
# A seam is only a breath if it falls where a person would take one. Cutting on
# the byte budget alone drops it mid-exchange; SEAM_AFTER_CHARS makes the
# chunker prefer to cut just after a long analysis turn — the natural beat
# before a new idea. SEAM_TARGET_BYTES is a soft floor, well under the hard cap,
# so the episode yields a seam roughly every minute rather than two in six.
#
# Both numbers are calibrated, not guessed: on a 46-turn reference-shaped script
# only ONE turn reaches 180 characters but ten reach 140, so an over-tight
# SEAM_AFTER_CHARS silently collapses back to two seams. 140/800 gives 4 seams
# there and more on a production-length episode. Re-measure before moving them.
SEAM_TARGET_BYTES = 800
SEAM_AFTER_CHARS = 140
SEAM_SILENCE_MS = 450


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
            continue
        current = trial
        # Past the soft floor, close the chunk on the first long turn: the seam
        # (and the silence spliced into it) then lands after a developed idea
        # rather than in the middle of an exchange.
        size = len(json.dumps([t["text"] for t in current]).encode())
        if size >= SEAM_TARGET_BYTES and len(turn["text"]) >= SEAM_AFTER_CHARS:
            grouped.append(current)
            current = []
    if current:
        grouped.append(current)
    return grouped


def splice(parts: list[bytes], gap_ms: int = SEAM_SILENCE_MS) -> bytes:
    """Join WAV payloads under one header, holding ``gap_ms`` at each seam.

    The silence is written in the stream's own format, so it stays inaudible as
    an artefact and audible as a pause. ``gap_ms=0`` restores a butt splice.
    """
    if not parts:
        raise SynthesisError("nothing to splice")
    out = io.BytesIO()
    params = None
    silence = b""
    with wave.open(out, "wb") as writer:
        for index, part in enumerate(parts):
            with wave.open(io.BytesIO(part), "rb") as reader:
                if params is None:
                    params = reader.getparams()
                    writer.setparams(params)
                    frames = int(params.framerate * gap_ms / 1000)
                    silence = b"\x00" * (frames * params.sampwidth * params.nchannels)
                if index and silence:
                    writer.writeframes(silence)
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
