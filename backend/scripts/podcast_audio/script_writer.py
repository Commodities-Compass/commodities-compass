"""The podcast script — a real conversation, composed natively per language.

This is the piece the P0 listening tests identified as decisive. Feeding the
served *monologue* prose to a multi-speaker voice and flipping speaker every
sentence produces a monologue cut in half: it was audibly "each reads their
line", and the rhythm was jerky because a speaker change every sentence forces a
pause and a fresh attack. Varied turn length is what makes it breathe.

It mirrors ``regime_brief.narrator``: one LLM call per language, composing
natively rather than translating, reading the prose the narrator already wrote
onto the served row so that the podcast and the dashboard cannot disagree.

What it must never do is invent a figure. ``_assert_no_invented_figures`` is the
first mechanical check that the spoken episode matches the published decision —
until now nothing verified what the audio actually said.
"""

from __future__ import annotations

import logging
import re
import statistics
from dataclasses import dataclass

from scripts._shared.llm_client import LLMClient, LLMClientError
from scripts.llm_utils import extract_json
from scripts.podcast_audio.speech_text import normalize_for_speech, numeric_tokens
from scripts.regime_brief.db_reader import BriefData
from scripts.regime_brief.narrator import Narrative

logger = logging.getLogger(__name__)

_TEMPERATURE = 0.6  # prose, but a conversation needs more variety than the brief
_MAX_TOKENS = 3000
# Pinned rather than inherited: LLMClient still defaults to gpt-4-turbo, which
# the brief's narrator also rides on. gpt-4.1 is what the meteo agent already
# uses in this codebase, and long-form French dialogue is what it is being
# asked for here.
_MODEL = "gpt-4.1"

HOST = "Ana"
GUEST = "Marc"

# The duration window is measured, not guessed: the four NotebookLM episodes of
# 2026-08-24 and 08-25 run 237, 294, 297 and 326 s. It brackets that observed
# range with a little headroom, so a generated episode lands where the ones
# clients already listen to land.
MIN_DURATION_SECONDS = 210
MAX_DURATION_SECONDS = 360
TARGET_DURATION_SECONDS = 290

# Speech rate is per language, and it is not a matter of taste. Measured on a
# 3 394-character French excerpt of a real episode (Kore + Algieba, the style
# prompt, `speakingRate` unset): 194.8 s, i.e. 17.4 chars/s. English is slower
# per character on identical content — 8.9 vs 11.3 chars/s on a paired sample,
# a ratio of 0.79 — because its words are shorter, so the same second of speech
# spends fewer characters. One shared constant biases the English episode short.
CHARS_PER_SECOND = {"fr": 17.4, "en": 13.7}
_DEFAULT_CHARS_PER_SECOND = 17.4

OPENING = {"fr": "Bonjour les COMPASTEURS", "en": "Hello COMPASTEURS"}
CLOSING = {"fr": "À demain les COMPASTEURS", "en": "See you tomorrow COMPASTEURS"}

# Naming the machinery in a client-facing episode breaks the product. Same
# posture as the brief: this is a producer, so it fails rather than degrades.
_BANNED = (
    "intelligence artificielle",
    "artificial intelligence",
    "algorithme",
    "algorithm",
    "modèle",
    "specialist",
    "spécialiste",
    "probabilité",
    "probability",
    "openai",
    "gpt",
    " llm ",
    "z-score",
    "régime détecté",
)


class ScriptError(RuntimeError):
    """The script writer could not produce a publishable episode."""


@dataclass(frozen=True)
class Turn:
    speaker: str
    text: str


@dataclass(frozen=True)
class PodcastScript:
    language: str
    turns: tuple[Turn, ...]

    @property
    def total_chars(self) -> int:
        return sum(len(t.text) for t in self.turns)

    @property
    def estimated_seconds(self) -> float:
        rate = CHARS_PER_SECOND.get(self.language, _DEFAULT_CHARS_PER_SECOND)
        return self.total_chars / rate

    def as_markup_turns(self) -> list[dict[str, str]]:
        """The ``multiSpeakerMarkup.turns`` payload, speech-normalised."""
        return [
            {"speaker": t.speaker, "text": normalize_for_speech(t.text)}
            for t in self.turns
        ]


def source_figures(data: BriefData, narrative: Narrative) -> set[str]:
    """Every figure the episode is allowed to speak."""
    blob = " ".join(
        str(part)
        for part in (
            narrative.conclusion,
            narrative.eco,
            narrative.confidence_rationale,
            data.technicals_snapshot,
            " ".join(data.watch_lines),
            data.press_summary,
            data.press_impact,
            data.meteo_summary,
            data.weather_body,
            data.technicals.close,
            data.technicals.close_prev,
            data.technicals.volume,
            data.technicals.oi,
            data.ytd_score,
        )
        if part is not None
    )
    return numeric_tokens(blob)


def _assert_formulas(script: PodcastScript) -> None:
    opening = OPENING.get(script.language, OPENING["fr"])
    closing = CLOSING.get(script.language, CLOSING["fr"])
    first, last = script.turns[0].text, script.turns[-1].text
    if opening.lower() not in first.lower():
        raise ScriptError(
            f"[{script.language}] must open with {opening!r}, got {first[:60]!r}"
        )
    if closing.lower() not in last.lower():
        raise ScriptError(
            f"[{script.language}] must close with {closing!r}, got {last[:60]!r}"
        )


def _assert_decision(script: PodcastScript, decision: str, technical: str) -> None:
    """The served call must be announced, and no third call may compete with it.

    ``technical`` is the regime's own read, which the editorial section exists to
    contrast with the macro overlay — the served prose itself says "la base
    technique HEDGE". Forbidding it would forbid the heart of the episode.
    """
    blob = " ".join(t.text for t in script.turns)
    # Announcing is checked leniently — the call was made either way.
    if decision.upper() not in blob.upper():
        raise ScriptError(
            f"[{script.language}] never announces the served decision {decision!r}"
        )
    quotable = {decision.upper(), technical.upper()}
    for other in {"OPEN", "HEDGE", "MONITOR"} - quotable:
        # Competing calls are checked STRICTLY: the signal name in capitals, as a
        # whole word. Case-insensitive substring matching flagged every English
        # episode, because "open interest" is the standard term for OI and
        # contains "open". A passing mention is fine; pushing a third call is not,
        # and the turns are quoted so the rejection can be judged.
        pattern = re.compile(rf"\b{other}\b")
        hits = [t.text for t in script.turns if pattern.search(t.text)]
        if len(hits) > 1:
            quoted = " | ".join(h[:80] for h in hits[:3])
            raise ScriptError(
                f"[{script.language}] pushes {other!r} {len(hits)}x while the served "
                f"call is {decision!r} (technical base {technical!r}) — {quoted}"
            )


def _assert_no_banned_vocabulary(script: PodcastScript) -> None:
    blob = " ".join(t.text for t in script.turns).lower()
    hits = [term for term in _BANNED if term in blob]
    if hits:
        raise ScriptError(f"[{script.language}] names the machinery: {hits}")


def _assert_no_invented_figures(script: PodcastScript, allowed: set[str]) -> None:
    """The only mechanical guarantee that the episode quotes the session.

    Observed live on 2026-08-26: the same prompt, run twice, invented a stock
    figure the second time. Under NotebookLM that reached listeners unchecked.
    """
    invented: dict[str, str] = {}
    for turn in script.turns:
        for token in numeric_tokens(turn.text) - allowed:
            invented.setdefault(token, turn.text)
    if invented:
        detail = "; ".join(
            f"{token} in {text[:90]!r}" for token, text in sorted(invented.items())
        )
        raise ScriptError(
            f"[{script.language}] speaks {len(invented)} figure(s) absent from the "
            f"session data — {detail}"
        )


def _assert_conversational_shape(script: PodcastScript) -> None:
    """Uniform turn lengths are what made pack 1 sound like a read-aloud."""
    lengths = [len(t.text) for t in script.turns]
    if len(lengths) < 8:
        raise ScriptError(
            f"[{script.language}] only {len(lengths)} turns — not a conversation"
        )
    speakers = {t.speaker for t in script.turns}
    if speakers != {HOST, GUEST}:
        raise ScriptError(
            f"[{script.language}] unexpected speakers: {sorted(speakers)}"
        )
    # Measured on three real NotebookLM episodes: cv 0.62, 0.84 and 0.98, with
    # turns from 4 to 397 characters. 0.45 is a floor between what the generator
    # produced unaided (0.18-0.27) and the reference — strict enough to reject a
    # flat episode, loose enough to be reachable.
    cv = statistics.pstdev(lengths) / statistics.mean(lengths)
    if cv < 0.45:
        raise ScriptError(
            f"[{script.language}] turn lengths are too uniform (cv={cv:.2f} < 0.45; a real "
            f"episode runs 0.62 to 0.98) — "
            "this is the shape that reads as two narrators taking turns"
        )
    if min(lengths) > 45:
        raise ScriptError(
            f"[{script.language}] no short interjection (shortest turn is "
            f"{min(lengths)} chars) — a conversation needs reactions"
        )


# Acknowledgement tics. Two is conversation, three is a tell that the same token
# is being reached for automatically — heard on 2026-08-26 with "exactement" x3
# in a single episode.
_FILLERS = (
    "exactement",
    "absolument",
    "tout à fait",
    "effectivement",
    "c'est ça",
    "en effet",
    "voilà",
    "exactly",
    "absolutely",
    "indeed",
    "that's right",
    "precisely",
    "definitely",
)
# PROVISIONAL, pending a decision. At 2 the gate blocks almost every run: four
# prompt framings over ~15 generations did not move gpt-4.1 off "exactement"
# (3 to 5 per episode), including one that never named the word in case citing
# it primed it. 4 still catches the pathological case without stopping the
# pipeline on a stylistic wart. See the options recorded in the design doc.
_MAX_FILLER_REPEATS = 4


def _assert_no_repeated_filler(script: PodcastScript) -> None:
    blob = " ".join(t.text for t in script.turns).lower()
    overused = {
        filler: blob.count(filler)
        for filler in _FILLERS
        if blob.count(filler) > _MAX_FILLER_REPEATS
    }
    if overused:
        detail = ", ".join(f"{w!r} x{n}" for w, n in sorted(overused.items()))
        raise ScriptError(
            f"[{script.language}] leans on the same acknowledgement: {detail} — "
            "two journalists vary, a generator repeats"
        )


# Measured on three real NotebookLM episodes (2026-08-24 FR/EN, 08-25 FR): the
# dominant voice carries 53 %, 55 % and 57 % of the characters — never a
# host-and-expert split. Ours ran at 72 % because the prompt asked for one.
# 62 % leaves room above the observed maximum without allowing a monologue.
MAX_SPEECH_SHARE = 0.62


def _assert_balanced_speakers(script: PodcastScript) -> None:
    spoken: dict[str, int] = {}
    for turn in script.turns:
        spoken[turn.speaker] = spoken.get(turn.speaker, 0) + len(turn.text)
    total = sum(spoken.values())
    for speaker, chars in sorted(spoken.items()):
        share = chars / total
        if share > MAX_SPEECH_SHARE:
            other = ", ".join(f"{s} {c / total:.0%}" for s, c in sorted(spoken.items()))
            raise ScriptError(
                f"[{script.language}] {speaker} carries {share:.0%} of the speech "
                f"({other}) — a real episode never passes {MAX_SPEECH_SHARE:.0%}; "
                "the two are co-analysts, not host and expert"
            )


def _assert_duration(script: PodcastScript) -> None:
    seconds = script.estimated_seconds
    if not MIN_DURATION_SECONDS <= seconds <= MAX_DURATION_SECONDS:
        raise ScriptError(
            f"[{script.language}] estimated {seconds:.0f}s, outside "
            f"[{MIN_DURATION_SECONDS}, {MAX_DURATION_SECONDS}]"
        )


def validate(script: PodcastScript, data: BriefData, narrative: Narrative) -> None:
    """Every check that stands between a generated script and a client's ears."""
    _assert_conversational_shape(script)
    _assert_formulas(script)
    _assert_decision(script, data.judge.final_decision, data.regime.decision)
    _assert_no_banned_vocabulary(script)
    _assert_no_repeated_filler(script)
    _assert_balanced_speakers(script)
    _assert_no_invented_figures(script, source_figures(data, narrative))
    _assert_duration(script)


def _parse(payload: dict, language: str) -> PodcastScript:
    raw_turns = payload.get("turns")
    if not isinstance(raw_turns, list) or not raw_turns:
        raise ScriptError(f"[{language}] response carries no turns")
    turns = []
    for i, item in enumerate(raw_turns):
        speaker = str(item.get("speaker", "")).strip()
        text = str(item.get("text", "")).strip()
        if not speaker or not text:
            raise ScriptError(f"[{language}] turn {i} is incomplete: {item!r}")
        turns.append(Turn(speaker=speaker, text=text))
    return PodcastScript(language=language, turns=tuple(turns))


def write_script(
    data: BriefData,
    narrative: Narrative,
    client: LLMClient | None = None,
    *,
    prompt_builder=None,
) -> PodcastScript:
    """Compose the episode natively in ``data.language``, then refuse it if wrong."""
    from scripts.podcast_audio.prompts import build_prompt

    client = client or LLMClient(model=_MODEL)
    prompt = (prompt_builder or build_prompt)(data, narrative)
    try:
        response = client.call(prompt, temperature=_TEMPERATURE, max_tokens=_MAX_TOKENS)
    except LLMClientError as exc:
        raise ScriptError(f"Script [{data.language}] failed: {exc}") from exc

    script = _parse(extract_json(response.raw_text), data.language)
    validate(script, data, narrative)
    logger.info(
        "script [%s]: %d turns, %d chars, ~%.0fs (model=%s)",
        data.language,
        len(script.turns),
        script.total_chars,
        script.estimated_seconds,
        response.model,
    )
    return script
