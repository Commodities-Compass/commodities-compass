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


def normalize_for_speech(text: str, language: str = "fr") -> str:
    """Strip layout markup, re-spell numbers, expand abbreviations, case names."""
    cleaned = _BLOCKQUOTE.sub("", text)
    cleaned = _BULLET.sub("", cleaned)
    cleaned = _normalize_numbers(cleaned, language)
    cleaned = _expand_abbreviations(cleaned, language)
    cleaned = _apply_lexicon_casing(cleaned)
    return _WHITESPACE.sub(" ", cleaned).strip()


# Rewrite every number into the convention of the language that will speak it.
#
# `,` and `.` swap roles across the Channel, and the database mixes both:
# `4,253.00` is an English thousands comma with an English decimal point. Fed to
# a French voice unchanged it becomes "4 virgule 253"; converting every dot to a
# comma instead gives an English voice "40,858,92". The digit count settles it —
# a separator followed by exactly three digits groups thousands, one followed by
# one or two is a decimal.
#
# A trailing all-zero fraction is dropped in both: heard 2026-08-27 as "quatre
# mille deux cent cinquante-trois virgule zéro zéro" for CLOSE=4,253.00.
_NUMBER = re.compile(
    r"\d{1,3}(?:[\u00a0\u202f ,.]\d{3})+(?:[.,]\d{1,2})?" r"|\d+(?:[.,]\d{1,2})?"
)
# A plain space, not the typographic U+202F: the final whitespace collapse
# flattens a narrow space anyway, and no voice can tell them apart.
_SEPARATORS = {"fr": (" ", ","), "en": (",", ".")}


def _normalize_numbers(text: str, language: str) -> str:
    thousands, decimal = _SEPARATORS.get(language, _SEPARATORS["fr"])

    def render(match: re.Match[str]) -> str:
        raw = match.group()
        head, _, frac = re.match(r"^(.*?)(?:([.,])(\d{1,2}))?$", raw).groups()  # type: ignore[union-attr]
        digits = re.sub(r"\D", "", head)
        grouped = f"{int(digits):,}".replace(",", thousands) if digits else ""
        if frac and set(frac) != {"0"}:
            return f"{grouped}{decimal}{frac}"
        return grouped

    return _NUMBER.sub(render, text)


# Column names out of technicals_snapshot. Left as written they reach the script
# verbatim and the voice spells them — "O-I" instead of "positions ouvertes".
_ABBREVIATIONS = {
    "fr": (
        ("STOCK_US", "stocks américains"),
        ("STOCK_EU", "stocks européens"),
        ("COM_NET", "position nette commerciale"),
        ("VOLUME", "volume"),
        ("CLOSE", "clôture"),
        ("HIGH", "plus haut"),
        ("LOW", "plus bas"),
        ("OI", "positions ouvertes"),
        ("IV", "volatilité implicite"),
    ),
    "en": (
        ("STOCK_US", "US stocks"),
        ("STOCK_EU", "EU stocks"),
        ("COM_NET", "commercial net position"),
        ("VOLUME", "volume"),
        ("CLOSE", "close"),
        ("HIGH", "high"),
        ("LOW", "low"),
        ("OI", "open interest"),
        ("IV", "implied volatility"),
    ),
}


def _expand_abbreviations(text: str, language: str) -> str:
    """Spell out the column names a voice would otherwise read letter by letter."""
    for short, spoken in _ABBREVIATIONS.get(language, _ABBREVIATIONS["fr"]):
        text = re.sub(rf"\b{short}\b", spoken, text)
    return text


def _apply_lexicon_casing(text: str) -> str:
    """Rewrite lexicon words to the casing they are pronounced correctly in.

    The brief and the script both write COMPASTEURS in capitals — that is the
    brand form, and it is also exactly what made a voice read it as an
    initialism. P0-quinquies settled it: normal case plus IPA was clean 3/3,
    capitals were not. Heard live on 2026-08-26 as "compasteutuses" with the
    caps still in place. The written form stays; only the spoken one changes.
    """
    for entry in LEXICON:
        text = re.compile(rf"\b{re.escape(entry.phrase)}\b", re.IGNORECASE).sub(
            entry.phrase, text
        )
    return text


@dataclass(frozen=True)
class Pronunciation:
    """One entry of the spoken lexicon."""

    phrase: str
    ipa: str


# Validated by ear 2026-08-26 (P0-quinquies): COMPASTEURS in capitals is read as
# an initialism ("C-O-M-P-asteurs") roughly one run in three. IPA fixed it 3/3.
#
# Phrases must be unique CASE-INSENSITIVELY — the API rejects the whole request
# with INVALID_ARGUMENT if two entries differ only by capitalisation, which also
# tells us one entry covers every casing.
LEXICON: tuple[Pronunciation, ...] = (
    Pronunciation("Compasteurs", "kɔ̃pastœʁ"),
    Pronunciation("momentum", "mɔmɑ̃tɔm"),
    Pronunciation("Compass", "kɔ̃pas"),
)


def custom_pronunciations() -> dict:
    """The ``input.customPronunciations`` payload for Gemini-TTS."""
    phrases = [entry.phrase.lower() for entry in LEXICON]
    duplicates = {p for p in phrases if phrases.count(p) > 1}
    if duplicates:
        raise ValueError(
            f"lexicon phrases must be unique case-insensitively: {sorted(duplicates)}"
        )
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


# Splits a matched number into its integer part and its fractional digits.
#
# `,` and `.` mean opposite things either side of the Channel: French writes
# `4 160,67` (decimal comma) where English writes `236,110` (thousands comma).
# The digit count disambiguates without knowing the locale — a separator
# followed by exactly three digits groups thousands, one followed by one or two
# is a decimal. Reading `236,110` as "236 point 110" is what made a correctly
# quoted stock figure look invented in the English episode.
_FRACTION = re.compile(r"^(.*?)(?:([.,])(\d{1,2}))?$", re.DOTALL)


def numeric_tokens(text: str) -> set[str]:
    """Canonical digit sequences in ``text``, for comparing spoken to source.

    ``2 438``, ``2438`` and ``2,438`` all reduce to ``2438`` so that a figure the
    script phrases differently from the database still matches.
    """
    tokens = set()
    for raw in _DIGITS.findall(text):
        # A trailing all-zero fraction is formatting, not precision: the database
        # renders STOCK_US=236,110.00 where a speaker says "236 110 tonnes". Left
        # in, the two never match and every genuine figure reads as invented.
        head, _sep, frac = _FRACTION.match(raw).groups()  # type: ignore[union-attr]
        whole = re.sub(r"\D", "", head)
        # Emit the integer part on its own as well as the full-precision form. A
        # speaker rounds — the database holds STOCK_EU=40,858.92 and the episode
        # says "40 858 tonnes". That is the figure, not an invented one. A zero
        # fraction is pure formatting and collapses to the same token.
        for candidate in {
            whole,
            whole + frac if frac and set(frac) != {"0"} else whole,
        }:
            if len(candidate) >= _MIN_ASSERTABLE_DIGITS:
                tokens.add(candidate.lstrip("0") or "0")
    return tokens
