"""The podcast prompt and the brief template must stay in lock step.

The prompt navigates the brief by section header and by field label. Rename a
header on one side and NotebookLM silently skips that part of the podcast —
there is no error anywhere, the audio is simply shorter and a client notices
before we do.

These tests read the shipped prompt files and assert that every anchor they
tell NotebookLM to look for actually exists in the rendered brief.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_regime_brief import _data, _narrative

from scripts.regime_brief.brief_generator import render_brief

_DOCS = Path(__file__).resolve().parents[2] / "docs" / "operations"
_PROMPT_FR = _DOCS / "notebooklm-podcast-prompt-regime.md"
_PROMPT_EN = _DOCS / "notebooklm-podcast-prompt-regime-en.md"


def _flat(text: str) -> str:
    """Collapse whitespace runs so a wrapped line still matches.

    The prompt is hard-wrapped for readability, which splits some section
    headers across two lines. NotebookLM reads it as prose, so the wrapping is
    cosmetic — comparing on the flattened text checks the anchor without
    pinning the layout.
    """
    return " ".join(text.split())


def test_prompt_files_are_shipped() -> None:
    assert _PROMPT_FR.exists(), "prompt FR manquant"
    assert _PROMPT_EN.exists(), "prompt EN manquant"


@pytest.mark.parametrize(
    "prompt_path,language,headers",
    [
        (
            _PROMPT_FR,
            "fr",
            (
                "II — LECTURE ÉDITORIALE",
                "III — ÉCO & REVUE DE PRESSE",
                "IV — WEATHER WATCH",
                "V — PHOTO TECHNIQUE",
                "VI — RECOMMANDATIONS OPÉRATIONNELLES",
            ),
        ),
        (
            _PROMPT_EN,
            "en",
            (
                "II — EDITORIAL READ",
                "III — ECO & PRESS REVIEW",
                "IV — WEATHER WATCH",
                "V — TECHNICAL SNAPSHOT",
                "VI — OPERATIONAL RECOMMENDATIONS",
            ),
        ),
    ],
    ids=["fr", "en"],
)
def test_every_section_the_prompt_navigates_exists_in_the_brief(
    prompt_path: Path, language: str, headers: tuple[str, ...]
) -> None:
    """Sections II-VI are quoted verbatim by the prompt, so they must match.

    Section I is referenced as "Section I" rather than by its header, so it is
    checked separately below.
    """
    prompt = _flat(prompt_path.read_text(encoding="utf-8"))
    brief = render_brief(_data(language), _narrative())

    for header in headers:
        assert header in brief, f"section absente du brief : {header}"
        assert _flat(header) in prompt, f"section absente du prompt : {header}"


@pytest.mark.parametrize(
    "prompt_path,language", [(_PROMPT_FR, "fr"), (_PROMPT_EN, "en")], ids=["fr", "en"]
)
def test_signal_section_and_its_fields_are_reachable(
    prompt_path: Path, language: str
) -> None:
    """Point 3 reads the position, the confidence and its trailing sentence."""
    prompt = prompt_path.read_text(encoding="utf-8")
    brief = render_brief(_data(language), _narrative())

    assert "I — SIGNAL" in brief
    assert "Section I" in prompt
    # The "X/5 — sentence" shape the prompt tells NotebookLM to reword.
    assert "3/5 — " in brief


def test_prompts_point_at_the_regime_filenames() -> None:
    """An ensemble filename here means the wrong brief gets narrated."""
    assert "CompassBrief-Regime.txt" in _PROMPT_FR.read_text(encoding="utf-8")
    assert "CompassBrief-Regime-EN.txt" in _PROMPT_EN.read_text(encoding="utf-8")
    assert "CompassAudio-Regime.m4a" in _PROMPT_FR.read_text(encoding="utf-8")
    assert "CompassAudio-Regime-EN.m4a" in _PROMPT_EN.read_text(encoding="utf-8")


@pytest.mark.parametrize("prompt_path", [_PROMPT_FR, _PROMPT_EN], ids=["fr", "en"])
def test_prompts_announce_the_next_session_horizon(prompt_path: Path) -> None:
    """Regime decides for J+1. The ensemble text promised 4 to 5 sessions.

    The easiest thing to forget when cloning the prompt, and the most
    misleading: an audio that promises a week-long view on a next-day signal
    misrepresents the product to every listener.
    """
    prompt = prompt_path.read_text(encoding="utf-8")

    assert "4 à 5 sessions" not in prompt
    assert "4 to 5 trading sessions" not in prompt
    assert "4 to 5 sessions" not in prompt


@pytest.mark.parametrize("prompt_path", [_PROMPT_FR, _PROMPT_EN], ids=["fr", "en"])
def test_prompts_forbid_the_panel_vocabulary(prompt_path: Path) -> None:
    """No convergence, no vote counting — that was the ensemble's editorial shape."""
    prompt = prompt_path.read_text(encoding="utf-8").lower()

    assert "panel" not in prompt or "no panel" in prompt
    assert "x out of 14" not in prompt
    assert "convergent sur ce verdict" not in prompt
    assert "converge on this verdict" not in prompt
