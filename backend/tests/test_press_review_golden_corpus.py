"""The golden corpus must stay honest — checked without a database.

``poetry run press-review-golden`` confronts the corpus with the articles the
agent actually produced, and needs real history to do it. These tests guard the
corpus itself, which is where the first bug appeared: the 2026-07-31 entry
originally matched on ANY of its markers, and "2026/27" alone hit an unrelated
StoneX sentence *in the very brief that missed the announcement*. The report
proudly said RECOVERED.

A golden set that rubber-stamps is worse than none: it converts an open wound
into a green tick. So the shape of an entry is now itself under test.
"""

from __future__ import annotations

import pytest

from scripts.press_review_agent.golden import (
    GOLDEN,
    REPLAYABLE_FROM,
    Status,
    entries_for,
    is_replayable,
)

# Tokens too common in a cocoa brief to identify anything on their own. A
# required marker drawn from this list is the rubber-stamp bug coming back.
_TOO_GENERIC = {
    "2026/27",
    "2025/26",
    "cacao",
    "cocoa",
    "ghana",
    "côte d'ivoire",
    "production",
    "offre",
    "prix",
    "marché",
}


@pytest.mark.unit
def test_the_corpus_is_not_empty() -> None:
    assert GOLDEN, "the golden corpus has been emptied"


@pytest.mark.unit
@pytest.mark.parametrize("entry", GOLDEN, ids=lambda e: str(e.session_date))
def test_every_entry_pins_its_fact_to_a_specific_actor(entry) -> None:
    """``required`` is the conjunction that makes a match mean something."""
    assert entry.required, (
        f"{entry.session_date}: no required marker — matches anything"
    )
    generic = [m for m in entry.required if m.lower() in _TOO_GENERIC]
    assert not generic, (
        f"{entry.session_date}: required marker(s) {generic} are too generic; "
        "they will match unrelated prose and report a miss as covered"
    )


@pytest.mark.unit
@pytest.mark.parametrize("entry", GOLDEN, ids=lambda e: str(e.session_date))
def test_every_entry_justifies_itself(entry) -> None:
    """An entry with no stated reason is a preference, not a specification."""
    assert entry.fact.strip(), f"{entry.session_date}: no fact"
    assert len(entry.why.strip()) > 40, (
        f"{entry.session_date}: `why` must say what a desk needed it for"
    )
    assert entry.source.strip(), f"{entry.session_date}: unsourced claim"
    assert entry.status in {Status.MUST_HOLD, Status.KNOWN_MISS}


@pytest.mark.unit
@pytest.mark.parametrize(
    "entry", entries_for(Status.KNOWN_MISS), ids=lambda e: str(e.session_date)
)
def test_a_miss_names_what_displaced_it(entry) -> None:
    """The competing item that won is the actionable half of a miss.

    "We missed COCOBOD" says nothing about what to change. "A farmgate price left
    unchanged and a seedling handout came first" points straight at a ranking
    rule.
    """
    assert entry.displaced_by, (
        f"{entry.session_date}: a KNOWN_MISS must record what the brief led with "
        "instead — otherwise there is nothing to fix"
    )


@pytest.mark.unit
def test_pre_replay_entries_are_flagged_as_unprovable() -> None:
    """Be explicit that older misses can be argued but never demonstrated.

    ``aud_llm_call.prompt`` was NULL until 2026-08-18, so no run before that date
    can be replayed — we cannot even tell whether the fetcher missed the item or
    the summariser dropped it. Entries from that era are a specification, not a
    target a change can be proved against.
    """
    old = [e for e in GOLDEN if not is_replayable(e)]
    assert old, "expected the seeded pre-replay entries to still be present"
    assert all(e.session_date < REPLAYABLE_FROM for e in old)
