"""The press review must rank an official announcement above the recurring.

### The day this exists for

On 2026-07-31 COCOBOD announced that Ghana's 2026/27 production would fall by at
least 16 %, with Côte d'Ivoire down more than 10 %. CocoaIntel carried it that
day and CocoaIntel is one of our sources. The brief written for that date — on
Sunday 2026-08-02, since Friday is not the eve of a trading session — contains
no trace of it. What it contains instead: the Ghanaian farmgate price left
unchanged, 400 000 seedlings distributed by an NGO for the third day running,
and Ivorian arrivals "continuing" to slow.

The fact reached us on 2026-08-03, attributed to a secondary outlet, one session
after the front-month moved +9,75 %.

The prompt ranked SECTIONS (OFFRE > FONDAMENTAUX > MARCHÉ > SENTIMENT) but
nothing ranked items WITHIN a section, so a regulator's forecast cut and a
seedling handout competed on equal terms across 600-1500 words.

### What these tests do, and what they cannot do

They pin the contract, not the behaviour. Whether the model actually obeys the
ranking is an LLM question that needs a replay corpus — which does not exist yet
for past dates, because the rendered prompt was never stored (fixed in the same
change: ``write_llm_call(prompt=...)``). From now on every run is replayable, and
the corpus grows on its own.

Until then these are the cheap half: the instruction is present, in both
editions, and it names the anti-patterns that actually filled the 31 July brief.
A prompt rewrite that drops them fails here rather than silently six weeks later.
"""

from __future__ import annotations

import pytest

from scripts.press_review_agent import config

# The exact items that crowded out the COCOBOD announcement on 2026-07-31. The
# prompt must name them as low-priority, or the next rewrite reinvents the bug.
_FR_ANTI_PATTERNS = ("bord-champ", "plants", "replantation", "continuent")
_EN_ANTI_PATTERNS = ("farmgate", "seedling", "replanting", "continue to slow")


@pytest.mark.unit
@pytest.mark.parametrize(
    "prompt,label",
    [(config.SYSTEM_PROMPT, "fr"), (config.SYSTEM_PROMPT_EN, "en")],
    ids=["fr", "en"],
)
def test_both_editions_rank_items_inside_a_section(prompt: str, label: str) -> None:
    """Section ordering is not enough — the ranking must reach inside one."""
    marker = "HIÉRARCHIE À L'INTÉRIEUR" if label == "fr" else "RANKING WITHIN A SECTION"
    assert marker in prompt, f"{label}: intra-section ranking rule missing"


@pytest.mark.unit
@pytest.mark.parametrize(
    "prompt,label",
    [(config.SYSTEM_PROMPT, "fr"), (config.SYSTEM_PROMPT_EN, "en")],
    ids=["fr", "en"],
)
def test_regulators_are_named_as_the_top_rank(prompt: str, label: str) -> None:
    """A regulator's own announcement outranks everything else in its section."""
    for actor in ("COCOBOD", "ICCO"):
        assert actor in prompt, f"{label}: {actor} not named in the ranking"


@pytest.mark.unit
@pytest.mark.parametrize(
    "prompt,patterns,label",
    [
        (config.SYSTEM_PROMPT, _FR_ANTI_PATTERNS, "fr"),
        (config.SYSTEM_PROMPT_EN, _EN_ANTI_PATTERNS, "en"),
    ],
    ids=["fr", "en"],
)
def test_the_31_july_distractors_are_named_as_low_priority(
    prompt: str, patterns: tuple[str, ...], label: str
) -> None:
    """Naming the anti-pattern is what makes the rule operational.

    "Prioritise important news" is advice. "A farmgate price left unchanged and a
    seedling distribution never come before a regulator's forecast cut" is an
    instruction, and it is the one that would have changed the 31 July brief.
    """
    lowered = prompt.lower()
    missing = [p for p in patterns if p.lower() not in lowered]
    assert not missing, f"{label}: anti-patterns no longer named: {missing}"


@pytest.mark.unit
def test_the_ghanaian_regulator_is_polled_first_hand() -> None:
    """We were reading COCOBOD through a relay, two days late."""
    urls = [s["url"] for s in config.NEWS_SOURCES]
    assert any("cocobod.gh" in u for u in urls), "COCOBOD is not a source"


@pytest.mark.unit
def test_no_source_disables_tls_verification() -> None:
    """The Ivorian regulator was left out for exactly this reason.

    conseilcafecacao.ci serves an incomplete certificate chain. Adding it would
    have meant turning verification off for the whole fetcher — a real hole for
    a marginal gain, since its communiqués are relayed by Abidjan.net, which we
    already poll. If a future source ever needs `verify=False`, this fails.
    """
    for source in config.NEWS_SOURCES:
        assert source.get("verify", True) is not False, (
            f"{source['name']} disables TLS verification"
        )
        assert str(source["url"]).startswith("https://"), (
            f"{source['name']} is fetched over plain HTTP"
        )
