"""Turning text written for the eye into text a voice can read.

The served prose carries markdown and a hybrid number format — both invisible on
a dashboard, both audible in a podcast. The first P0 listening pack shipped them
raw and the voice said "supérieur à" for every ``>`` and read ``4 160.67`` digit
by digit. Everything stripped or rewritten here is layout, never meaning.

The lexicon is the other half: Compass has coined vocabulary ("COMPASTEURS") and
borrowed vocabulary ("momentum", contract codes) that no French voice guesses
right. Gemini-TTS takes IPA through ``customPronunciations``, which the model
cannot ignore — unlike a prompt hint, which it drops about a third of the time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Markdown that reaches us from pl_indicator_daily.conclusion.
_BLOCKQUOTE = re.compile(r"^\s*>\s?", re.MULTILINE)
_BULLET = re.compile(r"^\s*[•\-\*]\s+", re.MULTILINE)
# 4 160.67 — French thousands space, English decimal point. Unreadable as-is.
_DECIMAL_POINT = re.compile(r"(?<=\d)\.(?=\d)")
_WHITESPACE = re.compile(r"\s+")


def normalize_for_speech(text: str) -> str:
    """Strip layout markup and re-spell numbers for a French voice."""
    cleaned = _BLOCKQUOTE.sub("", text)
    cleaned = _BULLET.sub("", cleaned)
    cleaned = _DECIMAL_POINT.sub(",", cleaned)
    return _WHITESPACE.sub(" ", cleaned).strip()


@dataclass(frozen=True)
class Pronunciation:
    """One entry of the spoken lexicon."""

    phrase: str
    ipa: str


# Validated by ear 2026-08-26 (P0-quinquies): COMPASTEURS in capitals is read as
# an initialism ("C-O-M-P-asteurs") roughly one run in three. IPA fixed it 3/3.
LEXICON: tuple[Pronunciation, ...] = (
    Pronunciation("Compasteurs", "kɔ̃pastœʁ"),
    Pronunciation("COMPASTEURS", "kɔ̃pastœʁ"),
    Pronunciation("momentum", "mɔmɑ̃tɔm"),
    Pronunciation("Compass", "kɔ̃pas"),
)


def custom_pronunciations() -> dict:
    """The ``input.customPronunciations`` payload for Gemini-TTS."""
    return {
        "pronunciations": [
            {
                "phrase": entry.phrase,
                "phoneticEncoding": "PHONETIC_ENCODING_IPA",
                "pronunciation": entry.ipa,
            }
            for entry in LEXICON
        ]
    }


# Numbers below this many digits are structural, not data: the 1 in S1/R1, a
# confidence out of 5, a horizon in days. Asserting on them would fail on
# language, not on invention.
_MIN_ASSERTABLE_DIGITS = 3
# A separator only groups thousands when EXACTLY three digits follow it. A looser
# class glues neighbouring figures together — "4238 4201" became one eight-digit
# number, and every real figure then read as invented.
_DIGITS = re.compile(
    r"\d{1,3}(?:[\u00a0\u202f ,]\d{3})+(?:[.,]\d+)?"  # 36 333 · 4 160,67 · 2,438
    r"|\d+(?:[.,]\d+)?"  # 4238 · 8.3
)


def numeric_tokens(text: str) -> set[str]:
    """Canonical digit sequences in ``text``, for comparing spoken to source.

    ``2 438``, ``2438`` and ``2,438`` all reduce to ``2438`` so that a figure the
    script phrases differently from the database still matches.
    """
    tokens = set()
    for raw in _DIGITS.findall(text):
        digits = re.sub(r"\D", "", raw)
        if len(digits) >= _MIN_ASSERTABLE_DIGITS:
            tokens.add(digits.lstrip("0") or "0")
    return tokens
