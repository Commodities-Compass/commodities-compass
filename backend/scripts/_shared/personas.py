"""The two named voices Compass uses to describe its own reading.

Compass produces a decision in two distinct passes: a purely technical read
(regime router + frozen per-regime specialist) and a macro arbitration that
crosses it with press, weather and macro news. Until now the published text
collapsed both into one flat abstract line ("la lecture macro confirme la
position technique"), so the arbitration — the most interesting thing the
product does each day, and the pass that REVERSES the technical call on a
material share of sessions — was invisible to the reader.

Naming them fixes that. "L'algorithme Compass" and "notre spécialiste cacao"
are a persona layer: they make the two passes legible while hiding the
machinery behind a human metaphor, which is the opposite of leaking it.

This module exists so the two consumers cannot drift apart. The brief RENDERS
these personas and the podcast SPEAKS them, and both police a list of banned
mechanism words. If one side allowed a persona the other still banned, the
brief would emit a sentence the podcast then refuses — and the podcast is a
producer, so it fails the job rather than degrading. One tuple, both sides.

Matching is done on lowercased text, so every entry is lowercase.
"""

from __future__ import annotations

import re

ALLOWED_PERSONAS: tuple[str, ...] = (
    "algorithme compass",
    "compass algorithm",
    "spécialiste cacao",
    "cocoa specialist",
)


def strip_personas(blob: str) -> str:
    """Remove the allowed personas from lowercased text before a banned-word scan.

    The bare mechanism words stay forbidden everywhere else: "the macro
    specialist said" still fails, "notre spécialiste cacao a tranché" does not.
    """
    for persona in ALLOWED_PERSONAS:
        blob = blob.replace(persona, " ")
    return blob


# Shortening on second mention is what language does: an episode told to talk
# about "the Compass algorithm" and "our cocoa specialist" says "the algorithm"
# three turns later. The banned-word gate is absolute and killed the whole
# English episode for it on 2026-09-09 and 2026-09-13 — a producer, so no
# degradation, no audio at all. Naming the two voices made those words far more
# likely to be written without loosening anything about what happens when the
# model slips.
#
# These patterns restore the full form before the gate runs. This is rendering,
# not silent recovery: the rewrite is deterministic, it happens before anything
# is published, it invents nothing the prompt did not already sanction, and
# every firing is logged so the slip rate stays visible. What it deliberately
# does NOT do is rescue a real leak — the words must be adjacent, so "the macro
# specialist" and "the ML algorithm" match nothing here and still fail the gate.
_NORMALISATIONS: dict[str, tuple[tuple[re.Pattern[str], str], ...]] = {
    "fr": (
        (re.compile(r"\bl'algorithme\b(?!\s+Compass)", re.I), "l'algorithme Compass"),
        (
            re.compile(r"\b(?:notre|le)\s+spécialiste\b(?!\s+cacao)", re.I),
            "notre spécialiste cacao",
        ),
    ),
    "en": (
        (re.compile(r"\bthe\s+algorithm\b", re.I), "the Compass algorithm"),
        (re.compile(r"\b(?:our|the)\s+specialist\b", re.I), "our cocoa specialist"),
    ),
}


def normalise_personas(text: str, language: str) -> tuple[str, int]:
    """Restore the full persona wherever the text used the bare form.

    Returns the rewritten text and how many rewrites fired, so the caller can
    log the slip rate rather than hide it.
    """
    rewrites = 0

    def _apply(match: re.Match[str], replacement: str) -> str:
        nonlocal rewrites
        rewrites += 1
        # Keep sentence case: "The algorithm" must not come back lowercased.
        if match.group(0)[:1].isupper():
            return replacement[:1].upper() + replacement[1:]
        return replacement

    for pattern, replacement in _NORMALISATIONS.get(language, ()):
        text = pattern.sub(lambda m, r=replacement: _apply(m, r), text)
    return text, rewrites
