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
