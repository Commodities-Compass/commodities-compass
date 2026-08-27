"""Gemini-TTS — the engine chosen in P0, with the corrections P0 forced.

Three things here are not obvious and each was measured rather than assumed:

* **Chunking is structural.** The 4 000-byte cap is on the whole payload, so a
  full episode cannot be sent in one call however the turns are arranged.
* **The seam is a pace change, not a click.** Every call is an independent
  generation that picks its own tempo — the same chunk sent three times came
  back at 16.9, 15.5 and 13.4 chars/s. Splicing them raw is audible.
* **The fix is relative, not absolute.** Levelling every chunk to a hard-coded
  rate imposes a tempo instead of removing a drift, because the natural rate
  depends on the content. We calibrate on the episode's own first pass.
"""

from __future__ import annotations

import base64
import json
import logging
import statistics
import urllib.error
import urllib.request

import google.auth
import google.auth.transport.requests

from scripts.podcast_audio.script_writer import GUEST, HOST, PodcastScript
from scripts.podcast_audio.speech_text import custom_pronunciations
from scripts.podcast_audio.tts.base import (
    SynthesisError,
    chunk_turns,
    duration_seconds,
    splice,
)

logger = logging.getLogger(__name__)

# Chosen by ear 2026-08-27 over 3.1-flash and 2.5-flash on the same excerpt.
# 3.1-flash — the newest, and what P0 picked without comparing — is the WORST of
# the three at holding energy to the end of an utterance: tail/body 0.92 with 13
# to 20 % of utterances collapsing, against 0.95 and 12 % here. 2.5-flash scores
# best on the metric (0.99 / 7 %) but reads flat. Thirty-second P0 clips could
# not surface this; over four minutes it becomes the dominant defect.
MODEL = "gemini-2.5-pro-tts"
ENDPOINT = "https://texttospeech.googleapis.com/v1beta1/text:synthesize"
PROJECT = "cacaooo"

# Chosen by ear in P0 over Charon (flat), Aoede, Puck, Orus, Umbriel, Iapetus and
# Schedar. Pinned: clients will associate these two voices with Compass.
VOICE_HOST = "Kore"
VOICE_GUEST = "Algieba"

LANGUAGE_CODES = {"fr": "fr-FR", "en": "en-US"}

# speakingRate is honoured and near-linear (1.0 -> 16.3 chars/s, 1.15 -> 20.5).
# Clamped so a correction can never turn into an artefact.
RATE_MIN, RATE_MAX = 0.7, 1.4
# A chunk is re-synthesised only if it drifts further than this from the
# episode's own median. Below it the difference is inaudible and a second call
# would just be spend.
RATE_TOLERANCE = 0.06

_STYLE = {
    "fr": (
        "Deux journalistes financiers français qui discutent en direct à l'antenne. "
        "Ton naturel, vivant et complice : ils se répondent, rebondissent, se coupent "
        "parfois la parole. Ce n'est PAS une lecture à tour de rôle. Débit régulier "
        "et posé. Lis les nombres comme des nombres entiers, jamais chiffre par chiffre."
    ),
    "en": (
        "Two financial journalists talking live on air. Natural, lively, easy with each "
        "other: they answer, pick up, sometimes cut in. This is NOT a read-aloud. Even, "
        "measured pace. Do NOT punch individual words — no emphatic stress, no word "
        "set apart to underline it; the tone stays a live conversation, not a "
        "demonstration. Read numbers as whole numbers, never digit by digit."
    ),
}


class GeminiSynthesizer:
    """Multi-speaker synthesis through Cloud Text-to-Speech.

    Authentication is ADC, so the Cloud Run service account is used in
    production and no API key is provisioned or rotated. ``aiplatform`` must be
    enabled alongside ``texttospeech`` — Gemini-TTS is served by Vertex
    underneath, and without it the call returns 403 SERVICE_DISABLED naming an
    API you never called.
    """

    def __init__(self) -> None:
        self._credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )

    def _token(self) -> str:
        if not self._credentials.valid:
            self._credentials.refresh(google.auth.transport.requests.Request())
        return self._credentials.token

    def _call(self, turns: list[dict[str, str]], language: str, rate: float | None):
        audio_config: dict[str, object] = {"audioEncoding": "LINEAR16"}
        if rate is not None:
            audio_config["speakingRate"] = round(rate, 3)
        body = {
            "input": {
                "multiSpeakerMarkup": {"turns": turns},
                "prompt": _STYLE.get(language, _STYLE["fr"]),
                "customPronunciations": custom_pronunciations(),
            },
            "voice": {
                "languageCode": LANGUAGE_CODES.get(language, "fr-FR"),
                "modelName": MODEL,
                "multiSpeakerVoiceConfig": {
                    "speakerVoiceConfigs": [
                        {"speakerAlias": HOST, "speakerId": VOICE_HOST},
                        {"speakerAlias": GUEST, "speakerId": VOICE_GUEST},
                    ]
                },
            },
            "audioConfig": audio_config,
        }
        request = urllib.request.Request(
            ENDPOINT,
            data=json.dumps(body).encode(),
            headers={
                "Authorization": f"Bearer {self._token()}",
                "x-goog-user-project": PROJECT,
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode()[:300]
            raise SynthesisError(f"Gemini-TTS HTTP {exc.code}: {detail}") from exc
        except OSError as exc:
            raise SynthesisError(f"Gemini-TTS unreachable: {exc}") from exc

        content = payload.get("audioContent")
        if not content:
            raise SynthesisError("Gemini-TTS returned no audioContent")
        return base64.b64decode(content)

    def synthesize(self, script: PodcastScript) -> bytes:
        groups = chunk_turns(script.as_markup_turns())
        logger.info(
            "[%s] synthesising %d turns in %d chunk(s)",
            script.language,
            len(script.turns),
            len(groups),
        )

        first_pass = [self._call(g, script.language, None) for g in groups]
        rates = [_chars(g) / duration_seconds(a) for g, a in zip(groups, first_pass)]
        target = statistics.median(rates)

        levelled: list[bytes] = []
        for index, (group, audio, rate) in enumerate(
            zip(groups, first_pass, rates), start=1
        ):
            drift = abs(rate - target) / target
            if drift <= RATE_TOLERANCE:
                levelled.append(audio)
                logger.info(
                    "  chunk %d: %.1f chars/s (%.0f%% off median, kept)",
                    index,
                    rate,
                    drift * 100,
                )
                continue
            correction = max(RATE_MIN, min(RATE_MAX, target / rate))
            corrected = self._call(group, script.language, correction)
            achieved = _chars(group) / duration_seconds(corrected)
            levelled.append(corrected)
            logger.info(
                "  chunk %d: %.1f chars/s -> rate %.3f -> %.1f chars/s (median %.1f)",
                index,
                rate,
                correction,
                achieved,
                target,
            )

        audio = splice(levelled)
        logger.info(
            "[%s] %.1fs of audio, %.1f MB",
            script.language,
            duration_seconds(audio),
            len(audio) / 1e6,
        )
        return audio


def _chars(turns: list[dict[str, str]]) -> int:
    return sum(len(t["text"]) for t in turns)
