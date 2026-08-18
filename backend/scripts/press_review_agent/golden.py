"""Golden corpus — the facts the press review had to carry, day by day.

Each entry names ONE fact that a professional cocoa desk needed from a given
session, with the source that published it. The corpus is the specification of
"good" for the agent: not a style guide, a list of things that must be in the
output.

### Why it exists

On 2026-07-31 COCOBOD cut Ghana's 2026/27 production forecast by at least 16 %.
CocoaIntel carried it that day; CocoaIntel is one of our sources. The brief
written for that date carries no trace of it — it carried the farmgate price left
unchanged, a seedling handout, and Ivorian arrivals "continuing" to slow. The
front-month moved +9,75 % the next session, and the fact only reached us on
2026-08-03 through a secondary outlet.

Nothing in the codebase said that was wrong. This file does.

### What a golden entry is worth

Two different things depending on ``status``:

* ``MUST_HOLD`` — the agent got it right. Any prompt change that loses it is a
  regression, full stop. This is what "don't lose our progress" means concretely.
* ``KNOWN_MISS`` — the agent got it wrong and we know why. It stays red until a
  change fixes it, and it is the target a change is judged against.

### The honest limit on the past

A ``KNOWN_MISS`` dated before 2026-08-18 can never be turned green by improving
the prompt, because it cannot be replayed: ``aud_llm_call.prompt`` was NULL until
that date, so the sources those runs actually saw are gone. We cannot even tell
whether the fetcher missed the item or the summariser dropped it.

They stay in the corpus anyway — as the specification, and as the measurement of
where we were. From 2026-08-18 the rendered prompt is stored, so every later
entry is replayable and a fix is provable rather than argued.

Verify with ``poetry run press-review-golden``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


class Status:
    MUST_HOLD = "MUST_HOLD"
    KNOWN_MISS = "KNOWN_MISS"


@dataclass(frozen=True)
class GoldenEntry:
    """One fact the brief for ``session_date`` had to carry."""

    session_date: date
    #: What had to be reported, in plain words — for humans reading the report.
    fact: str
    #: Lowercased substrings that must ALL appear. This is what pins the fact to
    #: its actor: "2026/27" alone matched an unrelated StoneX sentence in the very
    #: brief that missed the announcement, and reported it as recovered. A generic
    #: marker is worse than no marker — it turns the corpus into a rubber stamp.
    required: tuple[str, ...]
    #: At least one must appear. Wording tolerance around the figure, so the entry
    #: tests whether the SUBJECT was covered rather than whether the model chose
    #: our exact phrasing. Empty means "no extra condition".
    any_of: tuple[str, ...]
    #: Who published it, so the claim is checkable years later.
    source: str
    #: Why a desk needed it — the entry has to justify its own existence.
    why: str
    status: str
    #: What the brief carried instead. Only on misses, and it is the useful part:
    #: it names the competing item that won, which is what a ranking rule fixes.
    displaced_by: tuple[str, ...] = ()


GOLDEN: tuple[GoldenEntry, ...] = (
    GoldenEntry(
        session_date=date(2026, 7, 31),
        fact=(
            "COCOBOD announced Ghana's 2026/27 production would fall by at least "
            "16 %, with Côte d'Ivoire down more than 10 %"
        ),
        required=("cocobod",),
        any_of=("16 %", "16%", "16 pour cent", "repli de la production"),
        source="https://www.cocoaintel.com/cocoa-futures-rebound-sharply-as-ghana-crop-risks-intensify-31-july-2026/",
        why=(
            "The producing country's own regulator revising its national forecast "
            "down is the highest-authority supply signal there is. The front-month "
            "moved +9,75 % on the next session."
        ),
        status=Status.KNOWN_MISS,
        displaced_by=(
            "Ghana farmgate price left unchanged (light crop)",
            "400 000 seedlings distributed by an NGO — third day running",
            "Ivorian port arrivals 'continuing' to slow — restated from 30 July",
        ),
    ),
    GoldenEntry(
        session_date=date(2026, 8, 3),
        fact="COCOBOD's ~16 % production cut, finally reported",
        required=("cocobod",),
        any_of=("16 %", "16%", "16 pour cent", "repli de la production"),
        source="https://www.cocoaintel.com/",
        why=(
            "The same fact as 31 July, one session late — after the market had "
            "already repriced. Kept as the proof that the miss was a latency, not "
            "a coverage gap: the subject does reach us, just too late to be worth "
            "anything. If this one ever goes missing too, the source broke."
        ),
        status=Status.MUST_HOLD,
    ),
    GoldenEntry(
        session_date=date(2026, 7, 15),
        fact=(
            "Ivorian arrivals weighing on the market near-term, against a "
            "medium-term bullish backdrop (2026/27 crop down >10 %, 100 000 acres "
            "destroyed in Ghana)"
        ),
        required=("arrivages",),
        any_of=("abondance", "pression baissière", "peser"),
        source="press review of 2026-07-15 (pl_fundamental_article)",
        why=(
            "A day the agent got right, and the reason the fix must be additive: "
            "it separated the near-term driver from the structural one, in the "
            "same paragraph, and the near-term read was correct (-8,82 % next "
            "session) against a regime call that was wrong. Losing this kind of "
            "output to chase 'more announcements' would be a bad trade."
        ),
        status=Status.MUST_HOLD,
    ),
)


def entries_for(status: str) -> tuple[GoldenEntry, ...]:
    return tuple(e for e in GOLDEN if e.status == status)


#: Entries dated before this cannot be replayed — see the module docstring.
REPLAYABLE_FROM = date(2026, 8, 18)


def is_replayable(entry: GoldenEntry) -> bool:
    """Can a prompt change be *proved* to fix this entry, or only argued?"""
    return entry.session_date >= REPLAYABLE_FROM
